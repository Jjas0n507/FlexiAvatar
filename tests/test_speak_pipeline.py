"""respond() 共享 speak 管线测试 — 假 LLM/TTS，验证有序发送、失败跳过、取消收敛"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio

from backend.audio_pipeline import AudioPipeline
from backend.session.manager import SessionManager, SessionState
from backend.live2d.motion_controller import MotionController
from backend.llm.base import LLMChunk
from backend.tts.base import TTSResult


# ── 假引擎 ──────────────────────────────────────


class FakeLLM:
    """按给定文本块流式输出"""

    def __init__(self, chunks: list[str]):
        self._chunks = chunks

    async def stream_chat(self, messages, tools=None, cancel_event=None):
        for c in self._chunks:
            if cancel_event is not None and cancel_event.is_set():
                return
            yield LLMChunk(type="text", content=c)
            await asyncio.sleep(0)


class FakeTTS:
    """可配置每句延迟/失败的假 TTS"""

    def __init__(self, delays: dict[str, float] | None = None,
                 fail_on: set[str] | None = None):
        self._delays = delays or {}
        self._fail_on = fail_on or set()
        self.synthesized: list[str] = []

    async def synthesize(self, text: str) -> TTSResult:
        await asyncio.sleep(self._delays.get(text, 0.01))
        if text in self._fail_on:
            raise RuntimeError(f"fake failure: {text}")
        self.synthesized.append(text)
        return TTSResult(
            audio_bytes=b"\xff\xf3" + text.encode("utf-8"),  # 非空即可
            format="mp3",
            duration_ms=100.0,
            text=text,
        )

    async def voices(self):
        return []


def make_pipeline(llm: FakeLLM, tts: FakeTTS):
    """构造进入 SPEAKING 状态前的 pipeline（引擎直接注入，跳过 _init_engines）"""
    session = SessionManager()
    sent: list[dict] = []

    async def on_tts_audio(payload: dict):
        sent.append(payload)

        # 假前端：延迟一拍再通知播完。respond() 只认最后一段发出之后的
        # done（发送前会 clear 掉排空间隙的中间信号），同步 set 会被清掉。
        async def _done():
            await asyncio.sleep(0.05)
            pipeline.notify_playback_done()

        asyncio.create_task(_done())

    pipeline = AudioPipeline(
        session_manager=session,
        motion_controller=MotionController(),
        on_tts_audio=on_tts_audio,
    )
    pipeline._llm = llm
    pipeline._tts = tts
    pipeline._vad = object()  # 防止 respond 前误触 _init_engines
    return pipeline, session, sent


async def _drive_to_speaking(session: SessionManager):
    await session.transition("vad_speech_start")
    await session.transition("vad_speech_end")
    await session.transition("processing_done")
    assert session.state == SessionState.SPEAKING


# ── 测试 ────────────────────────────────────────


async def _test_ordered_seq_despite_out_of_order_completion():
    """慢首句 + 快次句：发送仍按 seq 0,1,2 有序"""
    # 每句 ≥15 字（min_segment_length），确保 Segmenter 切成三段
    llm = FakeLLM(["第一句话说得比较慢也比较长一些。", "第二句很快就能够合成完毕而且内容够长呀。", "第三句也一样非常快而且内容也足够长呀。"])
    tts = FakeTTS(delays={"第一句话说得比较慢也比较长一些。": 0.2})
    pipeline, session, sent = make_pipeline(llm, tts)
    await _drive_to_speaking(session)

    await pipeline.respond("测试输入")

    assert len(sent) == 3
    assert [p["seq"] for p in sent] == [0, 1, 2]
    assert sent[0]["text"].startswith("第一句")
    assert sent[1]["text"].startswith("第二句")
    assert session.state == SessionState.IDLE  # speaking_done


async def _test_failed_sentence_skipped_later_ones_still_sent():
    """中间句失败：被跳过，后续句仍按序发送（seq 连续）"""
    llm = FakeLLM(["这是正常且足够长的第一句话内容啦。", "这一句注定会合成失败而且也足够长哦。", "这是最后一句正常而且足够长的内容。"])
    tts = FakeTTS(fail_on={"这一句注定会合成失败而且也足够长哦。"})
    pipeline, session, sent = make_pipeline(llm, tts)
    await _drive_to_speaking(session)

    await pipeline.respond("测试输入")

    assert len(sent) == 2
    assert [p["seq"] for p in sent] == [0, 1]  # 跳过失败句后仍连续
    assert sent[0]["text"].startswith("这是正常且足够长的第一句")
    assert sent[1]["text"].startswith("这是最后一句")


async def _test_cancel_mid_stream_converges():
    """LLM 流中途打断：respond() 正常返回，不再发送，任务全部收敛"""

    class SlowLLM:
        async def stream_chat(self, messages, tools=None, cancel_event=None):
            yield LLMChunk(type="text", content="第一句话的内容绝对是足够长了的吧。")
            await asyncio.sleep(0.5)  # 打断窗口
            yield LLMChunk(type="text", content="第二句不应该被发送出去。")

    tts = FakeTTS()
    pipeline, session, sent = make_pipeline(SlowLLM(), tts)
    await _drive_to_speaking(session)

    task = asyncio.create_task(pipeline.respond("测试输入"))
    await asyncio.sleep(0.1)
    await session.interrupt(reason="test")

    await asyncio.wait_for(task, timeout=3.0)  # 必须收敛，不能挂死

    # 打断后 respond 不应把状态推到 IDLE（speaking_done 在 INTERRUPTED 下 no-op）
    assert session.state == SessionState.INTERRUPTED
    # 取消后不再发送第二句
    assert all(not p["text"].startswith("第二句") for p in sent)


async def _test_payload_schema():
    """payload 携带 utteranceId/seq/audio/format/durationMs/expressions"""
    llm = FakeLLM(["太棒了！哈哈，今天真是开心。"])
    tts = FakeTTS()
    pipeline, session, sent = make_pipeline(llm, tts)
    await _drive_to_speaking(session)

    await pipeline.respond("测试输入")

    assert len(sent) >= 1
    p = sent[0]
    for key in ("utteranceId", "seq", "audio", "format", "durationMs", "text", "expressions"):
        assert key in p, f"missing {key}"
    assert p["format"] == "mp3"
    assert isinstance(p["audio"], str) and len(p["audio"]) > 0
    assert p["expressions"] and p["expressions"][0]["name"] == "happy"  # 情绪句


async def _test_two_utterances_have_distinct_ids():
    """两轮回复 utteranceId 不同（前端据此丢弃迟到分段）"""
    tts = FakeTTS()
    pipeline, session, sent = make_pipeline(FakeLLM(["第一轮的回复内容在这里。"]), tts)
    await _drive_to_speaking(session)
    await pipeline.respond("输入一")

    pipeline._llm = FakeLLM(["第二轮的回复内容在这里。"])
    await _drive_to_speaking(session)
    await pipeline.respond("输入二")

    assert len(sent) == 2
    assert sent[0]["utteranceId"] != sent[1]["utteranceId"]


# ── 同步包装（容器内无 pytest-asyncio）─────────

def test_ordered_seq_despite_out_of_order_completion():
    asyncio.run(_test_ordered_seq_despite_out_of_order_completion())

def test_failed_sentence_skipped_later_ones_still_sent():
    asyncio.run(_test_failed_sentence_skipped_later_ones_still_sent())

def test_cancel_mid_stream_converges():
    asyncio.run(_test_cancel_mid_stream_converges())

def test_payload_schema():
    asyncio.run(_test_payload_schema())

def test_two_utterances_have_distinct_ids():
    asyncio.run(_test_two_utterances_have_distinct_ids())

