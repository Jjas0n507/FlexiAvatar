"""
OpenAI LLM 适配器。

支持:
- 流式对话 (stream_chat): SSE streaming，逐 token 产出
- 工具调用 (chat_with_tools): 原生 function calling + 自动工具执行循环
- 可中断: 通过 cancel_event 在打断时中止生成
"""

import asyncio
import json
import logging
import os
from typing import AsyncIterator

from openai import AsyncOpenAI

from backend.llm.base import BaseLLM, Message, ToolDefinition, LLMChunk
from backend.config import config

logger = logging.getLogger("llm.openai")


class OpenAIAdapter(BaseLLM):
    """OpenAI LLM 适配器 (GPT-4o, GPT-4.1, etc.)"""

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ):
        """
        初始化 OpenAI 客户端。

        Args:
            model: 模型名，默认从配置读取
            base_url: API 地址，默认从配置读取
            api_key: API Key，默认从配置读取
            temperature: 温度，默认从配置读取
            max_tokens: 最大 token，默认从配置读取
        """
        self._model = model or config.get("llm.openai.model", "gpt-4o")
        self._base_url = base_url or os.environ.get(
            "OPENAI_BASE_URL",
            config.get("llm.openai.base_url", "https://api.openai.com/v1"),
        )
        self._api_key = api_key or os.environ.get(
            "OPENAI_API_KEY",
            config.get("llm.openai.api_key", ""),
        )
        self._temperature = temperature if temperature is not None else config.get("llm.openai.temperature", 0.7)
        self._max_tokens = max_tokens if max_tokens is not None else config.get("llm.openai.max_tokens", 1024)

        self._client: AsyncOpenAI | None = None

    @property
    def client(self) -> AsyncOpenAI:
        """懒初始化客户端"""
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
            )
        return self._client

    # ── 流式对话 ──────────────────────────────────

    async def stream_chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[LLMChunk]:
        """
        流式对话，逐步产出 LLMChunk。

        每个 chunk 是增量文本或工具调用声明。
        """
        openai_messages = self._build_messages(messages)
        openai_tools = self._build_tools(tools)

        # 第一次尝试：不带 tools 参数（当 tools 为空时，传 empty list 会导致 API 错误）
        kwargs = {
            "model": self._model,
            "messages": openai_messages,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "stream": True,
        }
        if openai_tools:
            kwargs["tools"] = openai_tools
            kwargs["tool_choice"] = "auto"

        stream = await self.client.chat.completions.create(**kwargs)

        tool_calls_accumulator: dict[int, dict] = {}

        async for chunk in stream:
            if cancel_event and cancel_event.is_set():
                await stream.close()
                logger.info("LLM stream cancelled by interrupt")
                return

            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            # 文本增量
            if delta.content:
                yield LLMChunk(type="text", content=delta.content)

            # 工具调用增量
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_accumulator:
                        tool_calls_accumulator[idx] = {
                            "id": tc.id or "",
                            "function": {"name": "", "arguments": ""},
                        }
                    if tc.id:
                        tool_calls_accumulator[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls_accumulator[idx]["function"]["name"] += tc.function.name
                        if tc.function.arguments:
                            tool_calls_accumulator[idx]["function"]["arguments"] += tc.function.arguments

        # 如果有工具调用，产出最终的 tool_call chunk
        if tool_calls_accumulator:
            for tc_data in tool_calls_accumulator.values():
                yield LLMChunk(
                    type="tool_call",
                    content="",
                    tool_call={
                        "id": tc_data["id"],
                        "function": tc_data["function"],
                    },
                )

    # ── 非流式对话 ────────────────────────────────

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> Message:
        """非流式对话，返回完整回复"""
        openai_messages = self._build_messages(messages)
        openai_tools = self._build_tools(tools)

        kwargs = {
            "model": self._model,
            "messages": openai_messages,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        if openai_tools:
            kwargs["tools"] = openai_tools
            kwargs["tool_choice"] = "auto"

        response = await self.client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        msg = choice.message

        return Message(
            role="assistant",
            content=msg.content or "",
            tool_calls=(
                [tc.model_dump() for tc in msg.tool_calls]
                if msg.tool_calls else None
            ),
        )

    # ── 工具调用循环 ──────────────────────────────

    async def chat_with_tools(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        tool_registry: "ToolRegistry",
        cancel_event: asyncio.Event | None = None,
        max_rounds: int = 5,
    ) -> AsyncIterator[LLMChunk]:
        """
        带自动工具执行循环的流式对话。

        1. 流式生成 → yield 文本 chunk
        2. 如果 LLM 产出 tool_call → 执行工具 → 把结果追加到消息历史
        3. 再次调用 LLM（可能继续调用工具或给出最终回复）
        4. 循环直到无 tool_call 或达到 max_rounds
        """
        local_messages = list(messages)  # 不修改原始消息列表
        system_prompt = config.get("llm.system_prompt", "")
        if system_prompt and not any(m.role == "system" for m in local_messages):
            local_messages.insert(0, Message(role="system", content=system_prompt))

        for round_num in range(max_rounds):
            if cancel_event and cancel_event.is_set():
                return

            # 收集本轮产生的 tool call
            pending_tool_calls: list[dict] = []
            has_any_output = False

            openai_messages = self._build_messages(local_messages)

            kwargs = {
                "model": self._model,
                "messages": openai_messages,
                "temperature": self._temperature,
                "max_tokens": self._max_tokens,
                "stream": True,
                "tools": self._build_tools(tools),
                "tool_choice": "auto",
            }

            stream = await self.client.chat.completions.create(**kwargs)

            tool_calls_accumulator: dict[int, dict] = {}

            async for chunk in stream:
                if cancel_event and cancel_event.is_set():
                    await stream.close()
                    return

                delta = chunk.choices[0].delta if chunk.choices else None
                if delta is None:
                    continue

                if delta.content:
                    has_any_output = True
                    yield LLMChunk(type="text", content=delta.content)

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_accumulator:
                            tool_calls_accumulator[idx] = {
                                "id": tc.id or "",
                                "function": {"name": "", "arguments": ""},
                            }
                        if tc.id:
                            tool_calls_accumulator[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls_accumulator[idx]["function"]["name"] += tc.function.name
                            if tc.function.arguments:
                                tool_calls_accumulator[idx]["function"]["arguments"] += tc.function.arguments

            # 无工具调用 → 对话结束
            if not tool_calls_accumulator:
                return

            # 收集并执行工具调用
            pending_tool_calls = [
                {
                    "id": tc["id"],
                    "function": tc["function"],
                }
                for tc in tool_calls_accumulator.values()
            ]

            # 将 assistant 的消息追加到历史
            assistant_msg = Message(
                role="assistant",
                content="",
                tool_calls=pending_tool_calls,
            )
            local_messages.append(assistant_msg)

            # 执行每个工具调用
            for tc in pending_tool_calls:
                if cancel_event and cancel_event.is_set():
                    return

                tool_name = tc["function"]["name"]
                try:
                    tool_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    tool_args = {}

                logger.info(f"Tool call: {tool_name}({tool_args})")
                yield LLMChunk(
                    type="tool_call",
                    content=f"调用工具: {tool_name}",
                    tool_call=tc,
                )

                try:
                    result = await tool_registry.execute_tool(tool_name, **tool_args)
                except Exception as e:
                    result = f"工具执行错误: {e}"
                    logger.error(f"Tool {tool_name} error: {e}")

                local_messages.append(Message(
                    role="tool",
                    content=str(result) if not isinstance(result, str) else result,
                    tool_call_id=tc["id"],
                ))

        logger.warning(f"Reached max tool rounds ({max_rounds}), stopping")

    # ── 内部方法 ──────────────────────────────────

    @staticmethod
    def _build_messages(messages: list[Message]) -> list[dict]:
        """将内部 Message 转为 OpenAI API 格式"""
        api_messages = []
        for msg in messages:
            api_msg: dict = {"role": msg.role, "content": msg.content}
            if msg.tool_calls:
                api_msg["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                api_msg["tool_call_id"] = msg.tool_call_id
            api_messages.append(api_msg)
        return api_messages

    @staticmethod
    def _build_tools(tools: list[ToolDefinition] | None) -> list[dict] | None:
        """将内部 ToolDefinition 转为 OpenAI function calling 格式"""
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    @classmethod
    def get_info(cls) -> dict:
        return {
            "name": "OpenAIAdapter",
            "version": "1.0",
            "backend": "OpenAI API",
            "models": ["gpt-4o", "gpt-4.1", "gpt-4o-mini"],
        }
