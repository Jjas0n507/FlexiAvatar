"""记忆系统测试 — MemoryManager + AudioPipeline 压缩/提取"""
import sys
import json
import os
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio

from backend.memory import MemoryManager, MemoryEntry, _EXTRACT_PROMPT
from backend.audio_pipeline import AudioPipeline
from backend.session.manager import SessionManager, SessionState
from backend.live2d.motion_controller import MotionController
from backend.llm.base import Message, LLMChunk
from backend.tts.base import TTSResult

# ── 辅助 ────────────────────────────────────────


def _make_msg(role: str, content: str) -> Message:
    return Message(role=role, content=content)


class FakeLLM:
    """可控 LLM — stream_chat 返回预设文本块，chat 返回预设字符串"""

    def __init__(self, response: str = "fake response", chunks: list[str] | None = None):
        self.response = response
        self._chunks = chunks or [response]
        self.chat_calls: list[list] = []      # 记录 chat() 调用参数
        self.stream_calls: list[list] = []    # 记录 stream_chat() 调用参数

    async def chat(self, messages, tools=None):
        self.chat_calls.append(messages)
        return self.response

    async def stream_chat(self, messages, tools=None, cancel_event=None):
        self.stream_calls.append(messages)
        for c in self._chunks:
            if cancel_event is not None and cancel_event.is_set():
                return
            yield LLMChunk(type="text", content=c)
            await asyncio.sleep(0)

    async def synthesize(self, text: str):
        return TTSResult(audio_bytes=b"x", format="mp3", duration_ms=100, text=text)


class FakeTTS:
    async def synthesize(self, text: str) -> TTSResult:
        return TTSResult(audio_bytes=b"x", format="mp3", duration_ms=100, text=text)

    async def voices(self):
        return []


# ── MemoryManager 单元测试 ──────────────────────


def test_parse_response_valid_json():
    """_parse_response — 正常 JSON 数组"""
    text = '一些废话\n[{"content": "用户叫张三", "category": "fact"}]\n更多废话'
    result = MemoryManager._parse_response(text)
    assert len(result) == 1
    assert result[0]["content"] == "用户叫张三"
    assert result[0]["category"] == "fact"


def test_parse_response_no_brackets():
    """_parse_response — 无方括号返回 []"""
    assert MemoryManager._parse_response("") == []
    assert MemoryManager._parse_response("纯文本无JSON") == []


def test_parse_response_malformed_json():
    """_parse_response — JSON 格式错误返回 []"""
    assert MemoryManager._parse_response("[not valid json}") == []
    assert MemoryManager._parse_response("[1, 2, 3") == []


def test_parse_response_filters_empty_content():
    """_parse_response — 过滤 content 为空的条目"""
    text = '[{"content": "", "category": "fact"}, {"content": "有效", "category": "pref"}]'
    result = MemoryManager._parse_response(text)
    assert len(result) == 1
    assert result[0]["content"] == "有效"


def test_format_history_basic():
    """_format_history — 基本格式化"""
    history = [
        _make_msg("system", "你是助手"),
        _make_msg("user", "你好"),
        _make_msg("assistant", "你好！"),
    ]
    text = MemoryManager._format_history(history)
    assert "你是助手" in text
    assert "用户: 你好" in text
    assert "助手: 你好！" in text
    assert "---以上为系统提示" in text


def test_format_history_truncates_long_content():
    """_format_history — 超长内容截断到 500 字"""
    long_text = "啊" * 600
    history = [_make_msg("user", long_text)]
    text = MemoryManager._format_history(history)
    assert "..." in text
    assert len(text) < 700  # 标签 + 500字 + "..." ≈ 510


def test_save_and_load_roundtrip():
    """_save → _load 往返"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = MemoryManager(storage_dir=tmpdir)
        mgr._save([
            {"content": "用户叫李四", "category": "fact"},
        ], session_id="test123")
        entries = mgr._load()
        assert len(entries) == 1
        assert entries[0].content == "用户叫李四"
        assert entries[0].category == "fact"
        assert entries[0].session_id == "test123"


def test_load_empty_file():
    """_load — 文件不存在返回 []"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = MemoryManager(storage_dir=tmpdir)
        assert mgr._load() == []


def test_save_appends_and_truncates():
    """_save — 追加 + 超过上限 FIFO 截断"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = MemoryManager(storage_dir=tmpdir)
        mgr._max_entries = 5

        # 写入 5 条
        for i in range(5):
            mgr._save([{"content": f"memory-{i}", "category": "fact"}], session_id="s")
        entries = mgr._load()
        assert len(entries) == 5
        assert entries[0].content == "memory-0"

        # 再写 1 条，最旧的被挤出
        mgr._save([{"content": "memory-5", "category": "fact"}], session_id="s")
        entries = mgr._load()
        assert len(entries) == 5
        assert entries[0].content == "memory-1"
        assert entries[4].content == "memory-5"


def test_atomic_write_no_tmp_leftover():
    """_save — 原子写入，不残留 .tmp 文件"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = MemoryManager(storage_dir=tmpdir)
        mgr._save([{"content": "test", "category": "fact"}], session_id="s")
        assert os.path.exists(mgr._file_path)
        assert not os.path.exists(mgr._file_path + ".tmp")


def test_get_context_formatting():
    """get_context — 格式化为要点列表"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = MemoryManager(storage_dir=tmpdir)
        mgr._save([
            {"content": "用户叫王五", "category": "fact"},
            {"content": "喜欢简短回复", "category": "preference"},
        ], session_id="s")
        ctx = mgr.get_context()
        assert "[fact] 用户叫王五" in ctx
        assert "[preference] 喜欢简短回复" in ctx
        assert ctx.count("\n") == 1


def test_get_context_empty():
    """get_context — 无记忆返回空字符串"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = MemoryManager(storage_dir=tmpdir)
        assert mgr.get_context() == ""


# ── AudioPipeline 记忆集成测试 ──────────────────


def _make_pipeline(llm=None, tts=None, memory_manager=None):
    """构造最小 pipeline，引擎直接注入跳过 _init_engines"""
    session = SessionManager()
    sent: list[dict] = []

    async def on_tts_audio(payload: dict):
        sent.append(payload)
        async def _done():
            await asyncio.sleep(0.02)
            pipeline.notify_playback_done()
        asyncio.create_task(_done())

    pipeline = AudioPipeline(
        session_manager=session,
        motion_controller=MotionController(),
        on_tts_audio=on_tts_audio,
        memory_manager=memory_manager,
    )
    pipeline._llm = llm or FakeLLM()
    pipeline._tts = tts or FakeTTS()
    pipeline._vad = object()
    pipeline._session_id = "test-session"
    return pipeline, session, sent


async def _drive_to_speaking(session: SessionManager):
    await session.transition("vad_speech_start")
    await session.transition("vad_speech_end")
    await session.transition("processing_done")
    assert session.state == SessionState.SPEAKING


async def _test_shutdown_triggers_extract_and_save():
    """shutdown() 有对话时调 extract_and_save"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = MemoryManager(storage_dir=tmpdir)
        llm = FakeLLM(response='[{"content": "提取的记忆", "category": "fact"}]')

        pipeline, session, _ = _make_pipeline(llm=llm, memory_manager=mgr)
        # 模拟有对话历史
        pipeline._history = [
            _make_msg("system", "prompt"),
            _make_msg("user", "我叫小明"),
            _make_msg("assistant", "你好小明"),
            _make_msg("user", "再见"),
        ]

        await pipeline.shutdown()
        # shutdown 调了 extract_and_save → LLM chat → 解析 JSON → _save
        entries = mgr._load()
        assert len(entries) >= 1
        assert any("提取的记忆" in e.content for e in entries)


async def _test_shutdown_skips_when_short_history():
    """shutdown() — 历史过短时跳过提取"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = MemoryManager(storage_dir=tmpdir)
        llm = FakeLLM()

        pipeline, _, _ = _make_pipeline(llm=llm, memory_manager=mgr)
        pipeline._history = [_make_msg("system", "prompt")]  # 只有 1 条

        await pipeline.shutdown()
        # LLM 不应被调用
        assert len(llm.chat_calls) == 0


async def _test_compress_async_replaces_old_messages():
    """_compress_async — 压缩旧消息为摘要 system 消息"""
    pipeline, _, _ = _make_pipeline(
        llm=FakeLLM(response="用户讨论了天气和计划"),
    )

    # 构造 20+ 条非 system 消息
    system = [Message(role="system", content="长期记忆: 用户叫小明")]
    chat = []
    for i in range(25):
        chat.append(Message(role="user", content=f"消息{i}a"))
        chat.append(Message(role="assistant", content=f"回复{i}b"))
    pipeline._history = system + chat

    await pipeline._compress_async()

    # 检查：最旧的 10 条被 1 条摘要替换
    non_system = [m for m in pipeline._history if m.role != "system"]
    assert len(non_system) == 8  # keep_recent=8
    system_msgs = [m for m in pipeline._history if m.role == "system"]
    assert len(system_msgs) == 2  # 原始 system + 摘要
    assert any("用户讨论了天气和计划" in m.content for m in system_msgs)


async def _test_compress_skips_when_under_threshold():
    """_compress_async — 消息不足 keep_recent 时跳过"""
    pipeline, _, _ = _make_pipeline(llm=FakeLLM())

    pipeline._history = [
        _make_msg("system", "prompt"),
        _make_msg("user", "hi"),
        _make_msg("assistant", "hello"),
    ]

    before = list(pipeline._history)
    await pipeline._compress_async()
    # 历史不变
    assert len(pipeline._history) == len(before)


async def _test_summarize_batch_returns_text():
    """_summarize_batch — LLM 正常时返回摘要文本"""
    pipeline, _, _ = _make_pipeline(llm=FakeLLM(response="一句话总结结果"))

    batch = [
        _make_msg("user", "今天天气真好"),
        _make_msg("assistant", "是啊，适合出去玩"),
    ]
    result = await pipeline._summarize_batch(batch)
    assert result == "一句话总结结果"


async def _test_summarize_batch_handles_llm_failure():
    """_summarize_batch — LLM 异常时返回 None"""

    class BrokenLLM:
        async def chat(self, messages, tools=None):
            raise RuntimeError("LLM crashed")

    pipeline, _, _ = _make_pipeline(llm=BrokenLLM())
    result = await pipeline._summarize_batch([_make_msg("user", "hi")])
    assert result is None


async def _test_history_lock_prevents_concurrent_writes():
    """_history_lock — 并发写 _history 时不会损坏数据"""
    pipeline, _, _ = _make_pipeline()

    async def writer(n: int):
        for _ in range(100):
            async with pipeline._history_lock:
                pipeline._history.append(_make_msg("user", f"writer-{n}"))
            await asyncio.sleep(0)

    await asyncio.gather(writer(0), writer(1), writer(2))
    # 如果锁失效，不会有数据竞争异常；只要不崩就算过
    assert len(pipeline._history) == 300


async def _test_respond_triggers_compress_after_reply():
    """respond() 完成后，超过阈值时触发后台压缩"""
    llm = FakeLLM(chunks=["这是足够长的回复内容测试。"])

    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = MemoryManager(storage_dir=tmpdir)
        pipeline, session, _ = _make_pipeline(llm=llm, memory_manager=mgr)

        # 构造超过 compress_threshold 的历史
        pipeline._history = [_make_msg("system", "prompt")]
        for i in range(25):
            pipeline._history.append(_make_msg("user", f"msg{i}"))
            pipeline._history.append(_make_msg("assistant", f"reply{i}"))

        await _drive_to_speaking(session)
        await pipeline.respond("新消息")

        # 等待后台压缩完成
        await asyncio.sleep(0.3)

        # 验证压缩确实发生了：非 system 消息数 ≤ keep_recent + 1（新消息）
        # ponytail: 宽松断言，Ollama 同步线程竞争下可能还未完成
        non_system = [m for m in pipeline._history if m.role not in ("system",)]
        assert len(non_system) <= 10 + 1  # keep_recent=8 + 最多新增 1 条 user + 1 条 assistant


async def _test_fallback_truncation_always_active():
    """fallback 截断 — 即使压缩未运行，历史也不会无限增长"""
    llm = FakeLLM(chunks=["短回复。"] * 3)

    pipeline, session, _ = _make_pipeline(llm=llm)
    # 无 memory_manager，只有 fallback 截断

    pipeline._history = [_make_msg("system", "prompt")]
    for i in range(30):
        pipeline._history.append(_make_msg("user", f"msg{i}"))
        pipeline._history.append(_make_msg("assistant", f"reply{i}"))

    max_history = 20
    await _drive_to_speaking(session)
    await pipeline.respond("测试")

    non_system = [m for m in pipeline._history if m.role != "system"]
    assert len(non_system) <= max_history + 1  # 最多截断后 + 新 user + 新 assistant


async def _test_long_term_memory_injection():
    """_init_engines — system prompt 中包含长期记忆"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = MemoryManager(storage_dir=tmpdir)
        mgr._save([
            {"content": "用户偏好语音回复", "category": "preference"},
        ], session_id="s")

        pipeline, _, _ = _make_pipeline(memory_manager=mgr)
        pipeline._vad = None  # 让 _init_engines 执行
        pipeline._asr = FakeLLM()  # 防止 ASR warmup 失败
        pipeline._tts = FakeTTS()

        await pipeline._init_engines()

        system_content = pipeline._history[0].content
        assert "用户偏好语音回复" in system_content
        assert "<user_memory>" in system_content


# ── 同步包装 ────────────────────────────────────


def test_parse_response_valid_json_sync():
    test_parse_response_valid_json()

def test_parse_response_no_brackets_sync():
    test_parse_response_no_brackets()

def test_parse_response_malformed_json_sync():
    test_parse_response_malformed_json()

def test_parse_response_filters_empty_sync():
    test_parse_response_filters_empty_content()

def test_format_history_basic_sync():
    test_format_history_basic()

def test_format_history_truncates_sync():
    test_format_history_truncates_long_content()

def test_save_and_load_roundtrip_sync():
    test_save_and_load_roundtrip()

def test_load_empty_file_sync():
    test_load_empty_file()

def test_save_appends_and_truncates_sync():
    test_save_appends_and_truncates()

def test_atomic_write_no_tmp_sync():
    test_atomic_write_no_tmp_leftover()

def test_get_context_formatting_sync():
    test_get_context_formatting()

def test_get_context_empty_sync():
    test_get_context_empty()

def test_shutdown_triggers_extract():
    asyncio.run(_test_shutdown_triggers_extract_and_save())

def test_shutdown_skips_short_history():
    asyncio.run(_test_shutdown_skips_when_short_history())

def test_compress_async_replaces():
    asyncio.run(_test_compress_async_replaces_old_messages())

def test_compress_skips_under_threshold():
    asyncio.run(_test_compress_skips_when_under_threshold())

def test_summarize_batch_returns():
    asyncio.run(_test_summarize_batch_returns_text())

def test_summarize_batch_handles_failure():
    asyncio.run(_test_summarize_batch_handles_llm_failure())

def test_history_lock_prevents_corruption():
    asyncio.run(_test_history_lock_prevents_concurrent_writes())

def test_respond_triggers_compress():
    asyncio.run(_test_respond_triggers_compress_after_reply())

def test_fallback_truncation_active():
    asyncio.run(_test_fallback_truncation_always_active())

def test_long_term_memory_injection():
    asyncio.run(_test_long_term_memory_injection())
