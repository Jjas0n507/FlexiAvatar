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

            # 收集流式响应文本
            response_parts: list[str] = []
            is_first = True
            tools_used = False

            logger.info("LLM streaming start")
            async for chunk in self._llm.stream_chat(
                self._history,
                tools=None,  # 暂时不传工具，先跑通基本流式
                cancel_event=cancel,
            ):
                if cancel.is_set():
                    return

                if chunk.type == "text":
                    response_parts.append(chunk.content)
                    if self._on_llm:
                        await self._on_llm(chunk.content, is_first, False)
                        is_first = False
                elif chunk.type == "tool_call":
                    tools_used = True
                    logger.info(f"LLM tool call: {chunk.tool_call}")

            # 发送最后一个空 chunk 标记结束
            if self._on_llm and not is_first:
                await self._on_llm("", False, True)

            response_text = "".join(response_parts).strip()
            logger.info(f"LLM result: {response_text[:80]}...")

            if not response_text and not tools_used:
                response_text = "抱歉，我不太明白你的意思。"

            # 保存到历史
            if response_text:
                self._history.append(Message(role="assistant", content=response_text))

            if cancel.is_set():
                return

            # 3. TTS — 流式合成（逐句播放）
            logger.info(f"TTS synthesizing: {response_text[:50]}...")

            total_duration_ms = 0.0
            async for tts_result in self._tts.stream_synthesize(response_text):
                if cancel.is_set():
                    return

                # 记录音频起始时间（必须在发送音频之前，保证口型同步）
                tts_start_time = time.time()

                # 发送音频块
                if self._on_tts_audio:
                    await self._on_tts_audio(tts_result)

                # 口型 + 情绪时间线 (Phase 4: 统一使用 build_timeline_message)
                if self._on_live2d and tts_result.phonemes:
                    timeline_msg = self._motion.build_timeline_message(
                        tts_result.text, tts_result.phonemes, tts_start_time,
                        speech_emotion=speech_emotion,  # Phase 5: 传入语音情绪
                    )
                    await self._on_live2d(timeline_msg)

                total_duration_ms += tts_result.duration_ms

            # Phase 4: 情绪已整合进 timeline，不再单独发送 expression 消息

            # 等待所有音频播完
            await asyncio.sleep(total_duration_ms / 1000.0)

            if cancel.is_set():
                return

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
