"""
LLM (Large Language Model) 抽象基类。

所有 LLM 适配器必须继承此基类。
支持 OpenAI、Claude、Ollama 等，通过配置切换。

关键设计：
- 流式输出: stream_chat() 返回 AsyncIterator
- 工具调用: 通过 ToolDefinition 注入可用工具
- 可中断: 通过 cancel_event 在打断时取消生成
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Literal


@dataclass
class Message:
    """对话消息"""
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None
    tool_calls: list[dict] | None = None


@dataclass
class ToolDefinition:
    """供 LLM function-calling 使用的工具定义"""
    name: str
    description: str
    parameters: dict  # JSON Schema


@dataclass
class LLMChunk:
    """流式输出的增量块"""
    type: Literal["text", "tool_call"]
    content: str              # text 类型: 增量文本
    tool_call: dict | None = None  # tool_call 类型的调用信息


class BaseLLM(ABC):
    """
    LLM 适配器抽象基类。

    每个适配器必须实现:
    - stream_chat(): 流式对话 (async generator)
    - chat(): 非流式对话

    可选覆盖:
    - chat_with_tools(): 带工具调用的流式对话 (子类可实现原生 function calling)
    """

    @abstractmethod
    async def stream_chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[LLMChunk]:
        """
        流式对话，逐步产出 LLMChunk。

        Args:
            messages: 对话历史
            tools: 可用工具列表
            cancel_event: 外部取消信号（打断时设置），子类应在每次迭代前检查
        """
        ...

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> Message:
        """
        非流式对话，返回完整的 assistant 回复。

        Args:
            messages: 对话历史
            tools: 可用工具列表

        Returns:
            Message with role="assistant"，可能包含 tool_calls
        """
        ...

    async def chat_with_tools(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        tool_registry: "ToolRegistry",
        cancel_event: asyncio.Event | None = None,
        max_rounds: int = 5,
    ) -> AsyncIterator[LLMChunk]:
        """
        带自动工具调用循环的流式对话。

        子类覆盖此方法可获得平台原生的 tool-use 支持。
        默认实现使用 chat() 做简单的单轮对话。
        """
        # 默认实现：简单调用 chat()，子类应覆盖以获得真正的流式+工具调用
        async for chunk in self.stream_chat(messages, tools, cancel_event):
            yield chunk

    @classmethod
    def get_info(cls) -> dict:
        return {"name": cls.__name__, "version": "unknown"}
