"""
语音流水线编排器。

将 VAD → ASR → (LLM/Echo) → TTS 串联为完整的语音对话链路。
支持打断机制和 WebSocket 音频流。

设计:
- AudioPipeline 管理单个对话会话的完整生命周期
- 通过回调将结果推送到 WebSocket 客户端
- 可被 SessionManager 的 interrupt 事件取消
"""

import asyncio
import logging
import time
from typing import Callable, Awaitable

import numpy as np

from backend.config import config
from backend.session.manager import SessionManager, SessionState
from backend.adapters import create_vad, create_asr, create_llm, create_tts
from backend.tts.base import TTSResult
from backend.live2d.motion_controller import MotionController
from backend.llm.base import Message
from backend.tools.registry import ToolRegistry

logger = logging.getLogger("pipeline")


class AudioPipeline:
    """
    语音对话流水线。

    用法:
        pipeline = AudioPipeline(session_manager, on_tts_audio, on_live2d, on_asr_text)
        asyncio.create_task(pipeline.run())
    """

    def __init__(
        self,
        session_manager: SessionManager,
        motion_controller: MotionController | None = None,
        on_tts_audio: Callable[[TTSResult], Awaitable[None]] | None = None,
        on_live2d_control: Callable[[dict], Awaitable[None]] | None = None,
        on_asr_result: Callable[[str, bool], Awaitable[None]] | None = None,
        on_llm_stream: Callable[[str, bool, bool], Awaitable[None]] | None = None,
    ):
        self._session = session_manager
        self._on_tts_audio = on_tts_audio
        self._on_live2d = on_live2d_control
        self._on_asr_result = on_asr_result
        self._on_llm = on_llm_stream

        # 引擎 (懒初始化，具体类型由 config 的 engine 字段决定)
        self._vad = None       # type: BaseVAD | None
        self._asr = None       # type: BaseASR | None
        self._llm = None       # type: BaseLLM | None
        self._tts = None       # type: BaseTTS | None
        self._motion = motion_controller  # 外部注入，消除双实例

        # 对话历史 (保留上下文)
        self._history: list[Message] = []
        # 口型诊断：最近一次 phoneme → mouth 时间线 (供 diag.lip_sync_sample 对比)
        self._last_expected_frames: list[dict] = []
        # Phase B: 前端播放完成信号
        self._playback_done: asyncio.Event = asyncio.Event()

        # 音频缓冲
        self._audio_buffer: list[np.ndarray] = []
        self._input_queue: asyncio.Queue = asyncio.Queue()

        # 流水线停止标志 (独立于 session.cancel_event —— 后者在 INTERRUPTED 期间置位，
        # 仅用于取消 LLM/TTS 任务，不能作为主循环退出条件)
        self._stop = asyncio.Event()

    # ── 初始化 ──────────────────────────────────

    async def _init_engines(self):
        """懒初始化所有引擎"""
        if self._vad is None:
            # 使用工厂函数创建引擎（引擎类型由 config 的 engine 字段决定）
            self._vad = create_vad(config)
            self._asr = create_asr(config)
            self._llm = create_llm(config)
            self._tts = create_tts(config)
            if self._motion is None:
                self._motion = MotionController()  # fallback: 无外部注入时自建

            # 初始化对话历史
            system_prompt = config.get("llm.system_prompt", "")
            if system_prompt:
                self._history = [Message(role="system", content=system_prompt)]

            await self._asr.warmup()
            logger.info("All engines initialized")

    # ── 音频输入 ────────────────────────────────

    def feed_audio(self, audio_chunk: np.ndarray):
        """接收前端传来的音频帧，放入处理队列"""
        self._input_queue.put_nowait(audio_chunk)

    def notify_playback_done(self):
        """Phase B: 前端通知音频播放完毕"""
        self._playback_done.set()

    # ── 主循环 ──────────────────────────────────

    async def run(self):
        """主流水线循环"""
        await self._init_engines()

        logger.info("Audio pipeline started")

        while not self._stop.is_set():
            try:
                # 等待音频帧 (100ms 超时以便检查停止标志)
                try:
                    audio_frame = await asyncio.wait_for(
                        self._input_queue.get(), timeout=0.1
                    )
                except asyncio.TimeoutError:
                    continue

                state = self._session.state

                if state == SessionState.IDLE:
                    # 空闲时做低频率 VAD 检测
                    if self._vad.should_interrupt(audio_frame):
                        await self._session.transition(
                            "vad_speech_start", reason="vad_detected"
                        )
                        self._audio_buffer = [audio_frame]

                elif state == SessionState.LISTENING:
                    self._audio_buffer.append(audio_frame.copy())
                    result = self._vad.process_frame(audio_frame)

                    if result.event.value == "speech_end":
                        await self._on_asr_result("...", False) if self._on_asr_result else None
                        await self._session.transition(
                            "vad_speech_end", reason="vad_silence"
                        )
                        # 清空残留音频帧，防止处理时误触发打断
                        self._flush_queue()
                        # 在后台处理 ASR + 回复
                        asyncio.create_task(self._process_speech())

                    elif result.event.value == "vad_timeout":
                        await self._session.transition(
                            "vad_timeout", reason="no_speech"
                        )

                elif state == SessionState.SPEAKING:
                    # 检测打断
                    if self._vad.should_interrupt(audio_frame):
                        logger.info("Interrupt detected!")
                        await self._session.interrupt(reason="user_speech")
                        await self._on_live2d(
                            self._motion.get_interrupt_command()
                        ) if self._on_live2d else None

                elif state == SessionState.INTERRUPTED:
                    # 等待清理完成
                    await asyncio.sleep(0.3)
                    await self._session.transition("interrupt_handled")
                    self._audio_buffer = [audio_frame.copy()]

            except Exception as e:
                logger.error(f"Pipeline error: {e}", exc_info=True)

        logger.info("Audio pipeline stopped")

    # ── 语音处理 ────────────────────────────────

    async def _process_speech(self):
        """处理收集到的语音段: ASR → LLM(streaming) → TTS"""
        cancel = self._session.cancel_event

        try:
            # 1. ASR — 流式识别
            if not self._audio_buffer:
                return

            audio = np.concatenate(self._audio_buffer)
            self._audio_buffer.clear()

            logger.info(f"ASR processing {len(audio)} samples ({len(audio)/16000:.1f}s)")

            # 使用流式 ASR，每识别出一个片段就推送给前端
            final_text = ""
            speech_emotion: str | None = None  # Phase 5: SenseVoice 语音情绪
            async for partial_result in self._asr.stream_transcribe(audio):
                if cancel.is_set():
                    return

                if partial_result.is_final:
                    final_text = partial_result.text.strip()
                    speech_emotion = partial_result.emotion  # Phase 5: 提取语音情绪
                    await self._on_asr_result(final_text, True) if self._on_asr_result else None
                else:
                    # 中间结果：显示正在进行中的识别
                    await self._on_asr_result(partial_result.text, False) if self._on_asr_result else None

            logger.info(f"ASR result: {final_text}")
            if speech_emotion and speech_emotion != "neutral":
                logger.info(f"Speech emotion: {speech_emotion}")

            if not final_text:
                await self._session.transition("speaking_done", reason="empty_asr")
                return

            # 2. LLM — 流式生成
            # 先发送处理中状态，准备进入 SPEAKING
            await self._session.transition("processing_done", reason="response_ready")

            # 构建消息
            self._history.append(Message(role="user", content=final_text))
            # 限制历史长度
            max_history = config.get("conversation.max_history_messages", 20)
            if len(self._history) > max_history + 1:  # +1 for system prompt
                # 保留 system prompt + 最近的消息
                system_msgs = [m for m in self._history if m.role == "system"]
                non_system = [m for m in self._history if m.role != "system"]
                self._history = system_msgs + non_system[-(max_history):]

            # 收集流式响应文本 + Phase B 增量分句 TTS
            response_parts: list[str] = []
            is_first = True
            tools_used = False

            # Phase B: 增量分句器 + 并发 TTS
            from backend.audio.segmenter import Segmenter
            segmenter = Segmenter(
                min_segment_length=config.get("tts.streaming.min_segment_length", 15),
                first_segment_punc=config.get("tts.streaming.first_segment_punc", "，,。！？!?；;"),
                rest_segment_punc=config.get("tts.streaming.rest_segment_punc", "。！？!?；;"),
            )
            max_concurrent = config.get("tts.streaming.max_concurrent_synthesis", 2)
            tts_sem = asyncio.Semaphore(max_concurrent)
            tts_queue: asyncio.Queue = asyncio.Queue()
            tts_tasks: list[asyncio.Task] = []
            tts_order = 0
            _asr_end_time = time.time()  # TTFA 测量起点

            async def _tts_worker(text: str, order: int):
                """后台 TTS 合成任务"""
                async with tts_sem:
                    try:
                        result = await self._tts.synthesize(text)
                        if not cancel.is_set():
                            await tts_queue.put((order, result, None))
                    except Exception as e:
                        logger.error(f"TTS worker [{order}] failed: {e}")
                        if not cancel.is_set():
                            await tts_queue.put((order, None, str(e)))

            async def _consume_tts_results() -> float:
                """按序消费 TTS 结果并发送到前端，返回总时长(ms)"""
                next_order = 0
                pending: dict = {}
                ttfa_logged = False
                total_ms = 0.0

                while True:
                    item = await tts_queue.get()
                    if item is None:  # sentinel
                        break
                    order, result, error = item
                    if error:
                        logger.warning(f"TTS sentence [{order}] skipped: {error}")
                        next_order = max(next_order, order + 1)
                        continue
                    pending[order] = result

                    while next_order in pending:
                        r = pending.pop(next_order)

                        if not ttfa_logged:
                            ttfa = (time.time() - _asr_end_time) * 1000
                            logger.info(f"TTFA: {ttfa:.0f}ms (ASR end → first audio sent)")
                            ttfa_logged = True

                        if self._on_tts_audio:
                            await self._on_tts_audio(r)

                        if self._on_live2d and r.phonemes:
                            timeline_msg = self._motion.build_timeline_message(
                                r.text, r.phonemes,
                                speech_emotion=speech_emotion,
                            )
                            if config.get("debug.lip_sync_profiling", False):
                                self._last_expected_frames = self._motion.phonemes_to_lip_sync(
                                    r.phonemes
                                )
                            await self._on_live2d(timeline_msg)

                        total_ms += r.duration_ms
                        next_order += 1

                return total_ms

            # 启动消费者协程
            consumer_task = asyncio.create_task(_consume_tts_results())

            logger.info("LLM streaming start (Phase B: incremental TTS)")
            async for chunk in self._llm.stream_chat(
                self._history,
                tools=None,
                cancel_event=cancel,
            ):
                if cancel.is_set():
                    consumer_task.cancel()
                    return

                if chunk.type == "text":
                    response_parts.append(chunk.content)
                    if self._on_llm:
                        await self._on_llm(chunk.content, is_first, False)
                        is_first = False

                    # Phase B: 增量分句 → 立即提交 TTS 后台任务
                    sentences = segmenter.feed(chunk.content)
                    for sentence in sentences:
                        tts_tasks.append(asyncio.create_task(
                            _tts_worker(sentence, tts_order)
                        ))
                        tts_order += 1

                elif chunk.type == "tool_call":
                    tools_used = True
                    logger.info(f"LLM tool call: {chunk.tool_call}")

            # 发送最后一个空 chunk 标记结束
            if self._on_llm and not is_first:
                await self._on_llm("", False, True)

            # Phase B: Flush 剩余文本
            remaining = segmenter.flush()
            if remaining:
                tts_tasks.append(asyncio.create_task(_tts_worker(remaining, tts_order)))
                tts_order += 1

            response_text = "".join(response_parts).strip()
            logger.info(f"LLM result ({segmenter.sentence_count} sentences): {response_text[:80]}...")

            if not response_text and not tools_used:
                response_text = "抱歉，我不太明白你的意思。"

            # 保存到历史
            if response_text:
                self._history.append(Message(role="assistant", content=response_text))

            if cancel.is_set():
                consumer_task.cancel()
                return

            # Phase B: 等待所有 TTS 后台任务完成
            if tts_tasks:
                logger.info(f"Waiting for {len(tts_tasks)} TTS tasks...")
                await asyncio.gather(*tts_tasks, return_exceptions=True)

            # 发送 sentinel 通知消费者结束
            await tts_queue.put(None)
            total_duration_ms = await consumer_task

            if cancel.is_set():
                return

            # Phase B: 等待前端播放完成（替代估算 sleep）
            timeout_s = (total_duration_ms / 1000.0) * 1.5 + 2.0
            try:
                await asyncio.wait_for(self._playback_done.wait(), timeout=timeout_s)
                logger.info("Playback confirmed by frontend")
            except asyncio.TimeoutError:
                logger.warning(f"playback.done timeout after {timeout_s:.1f}s, proceeding anyway")

            self._playback_done.clear()

            await self._session.transition("speaking_done", reason="tts_finished")

        except asyncio.CancelledError:
            logger.info("Speech processing cancelled (interrupted)")
        except Exception as e:
            logger.error(f"Speech processing error: {e}", exc_info=True)
            try:
                await self._session.transition("speaking_done", reason="error")
            except Exception:
                pass

    def _flush_queue(self):
        """清空输入队列中的残留音频帧"""
        drained = 0
        while not self._input_queue.empty():
            try:
                self._input_queue.get_nowait()
                drained += 1
            except asyncio.QueueEmpty:
                break
        if drained:
            logger.debug(f"Flushed {drained} residual audio frames")

    # ── 清理 ──────────────────────────────────

    async def shutdown(self):
        """关闭流水线"""
        self._stop.set()
        self._audio_buffer.clear()
        self._history.clear()
        while not self._input_queue.empty():
            self._input_queue.get_nowait()
        logger.info("Pipeline shutdown complete")
