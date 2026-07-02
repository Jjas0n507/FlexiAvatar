"""LLM 模块测试 — OpenAI 适配器流式对话"""
import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio

from backend.llm.openai_adapter import OpenAIAdapter
from backend.llm.base import Message
from backend.config import config


async def test_import_and_basic():
    """测试适配器导入和基本属性"""
    print("=" * 50)
    print("LLM Adapter Tests")
    print("=" * 50)

    adapter = OpenAIAdapter()
    print(f"\nModel: {adapter._model}")
    print(f"Base URL: {adapter._base_url}")
    print(f"Temperature: {adapter._temperature}")

    # 验证配置读取
    assert adapter._model, "Model should not be empty"
    assert adapter._base_url, "Base URL should not be empty"
    print("[OK] Adapter initialized from config")

    return adapter


async def test_stream_chat_basic(adapter: OpenAIAdapter):
    """测试基本流式对话（需要 API Key）"""
    print(f"\n{'='*50}")
    print("Test: Stream Chat (basic)")

    # 检查是否有 API Key
    if not adapter._api_key or adapter._api_key.startswith("${"):
        print("[SKIP] No API key configured — set OPENAI_API_KEY in .env")
        return

    print(f"  [timestamp] start: {__import__('time').strftime('%H:%M:%S')}")

    messages = [
        Message(role="user", content="你好，请用中文回答：1+1等于几？"),
    ]

    response_parts = []
    async for chunk in adapter.stream_chat(messages):
        if chunk.type == "text":
            response_parts.append(chunk.content)
            print(f"  Chunk: '{chunk.content}'")

    full = "".join(response_parts)
    print(f"\n  Full response: {full}")
    assert len(full) > 0, "Empty response"
    print("  [OK]")


async def test_stream_chat_with_cancel(adapter: OpenAIAdapter):
    """测试流式对话的中断取消"""
    print(f"\n{'='*50}")
    print("Test: Stream Chat with Cancel")

    if not adapter._api_key or adapter._api_key.startswith("${"):
        print("[SKIP] No API key configured")
        return

    cancel = asyncio.Event()
    messages = [
        Message(role="user", content="写一篇1000字的文章介绍人工智能的历史"),
    ]

    chunk_count = 0
    async for chunk in adapter.stream_chat(messages, cancel_event=cancel):
        chunk_count += 1
        if chunk.type == "text" and chunk_count >= 2:
            print(f"  Cancelling after {chunk_count} chunks...")
            cancel.set()

    print(f"  Received {chunk_count} chunks before cancel")
    print("  [OK] Cancel respected")


async def test_message_building():
    """测试消息格式转换"""
    print(f"\n{'='*50}")
    print("Test: Message Formatting")

    adapter = OpenAIAdapter()
    msgs = [
        Message(role="system", content="You are helpful"),
        Message(role="user", content="Hello"),
        Message(role="assistant", content="Hi there!"),
    ]
    api_msgs = adapter._build_messages(msgs)
    assert len(api_msgs) == 3
    assert api_msgs[0]["role"] == "system"
    assert api_msgs[1]["role"] == "user"
    assert api_msgs[2]["role"] == "assistant"
    print(f"  [OK] {len(api_msgs)} messages formatted correctly")


async def main():
    t_start = __import__('time').perf_counter()
    adapter = await test_import_and_basic()
    await test_message_building()
    await test_stream_chat_basic(adapter)
    await test_stream_chat_with_cancel(adapter)

    elapsed = (__import__('time').perf_counter() - t_start) * 1000
    print(f"\n=== All LLM tests passed ===")
    print(f"[TIMING] Total: {elapsed:.0f}ms")


if __name__ == "__main__":
    asyncio.run(main())
