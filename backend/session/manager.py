"""
会话状态机。

管理对话会话的状态转换。五种状态:
- IDLE:        空闲，等待用户说话
- LISTENING:   正在监听用户语音
- PROCESSING:  正在处理 (ASR → LLM → TTS)
- SPEAKING:    正在播放回复语音
- INTERRUPTED: 被打断，正在清理并准备重新监听
"""

import asyncio
import time
from enum import Enum
from typing import Callable, Awaitable


class SessionState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"


# 合法的状态转换映射
ALLOWED_TRANSITIONS: dict[SessionState, set[SessionState]] = {
    SessionState.IDLE:        {SessionState.LISTENING},
    SessionState.LISTENING:   {SessionState.IDLE, SessionState.PROCESSING},
    SessionState.PROCESSING:  {SessionState.SPEAKING, SessionState.INTERRUPTED},
    SessionState.SPEAKING:    {SessionState.IDLE, SessionState.INTERRUPTED},
    SessionState.INTERRUPTED: {SessionState.LISTENING},
}


class InvalidTransitionError(Exception):
    """非法的状态转换"""
    pass


class SessionManager:
    """
    会话状态机。

    用法:
        manager = SessionManager()

        @manager.on_transition
        async def on_state_change(transition):
            print(f"{transition.from_state} → {transition.to_state}")

        await manager.transition("user_started_speaking")
    """

    def __init__(self):
        self._state: SessionState = SessionState.IDLE
        self._listeners: list[Callable[..., Awaitable[None]]] = []
        self._history: list[dict] = []
        self._cancel_event: asyncio.Event = asyncio.Event()
        self._lock: asyncio.Lock = asyncio.Lock()

    # ── 属性 ──────────────────────────────────────

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def cancel_event(self) -> asyncio.Event:
        """当前对话的取消事件。在 INTERRUPTED 时被设置，用于取消 LLM/TTS 任务。"""
        return self._cancel_event

    @property
    def history(self) -> list[dict]:
        """状态转换历史"""
        return list(self._history)

    # ── 状态转换 ──────────────────────────────────

    async def transition(self, event: str, reason: str = "") -> bool:
        """
        触发状态转换。

        返回 True 如果转换成功，False 如果该事件不触发任何转换。
        """
        async with self._lock:
            target = self._resolve_target(event)
            if target is None:
                return False

            if target not in ALLOWED_TRANSITIONS.get(self._state, set()):
                raise InvalidTransitionError(
                    f"不允许从 {self._state.value} 转换到 {target.value} (事件: {event})"
                )

            previous = self._state
            self._state = target
            timestamp = time.time()

            record = {
                "from": previous.value,
                "to": target.value,
                "event": event,
                "reason": reason,
                "timestamp": timestamp,
            }
            self._history.append(record)

            # INTERRUPTED → 设置取消事件
            if target == SessionState.INTERRUPTED:
                self._cancel_event.set()
            else:
                self._cancel_event.clear()

            # 通知所有监听器
            for listener in self._listeners:
                try:
                    await listener(previous, target, event, reason)
                except Exception:
                    pass  # 监听器异常不影响状态机

            return True

    async def interrupt(self, reason: str = "user_speech_detected") -> None:
        """从外部触发打断"""
        if self._state in (SessionState.SPEAKING, SessionState.PROCESSING):
            await self.transition("interrupt", reason=reason)

    def _resolve_target(self, event: str) -> SessionState | None:
        """
        根据事件名和当前状态，解析目标状态。

        事件命名约定:
          vad_speech_start  → IDLE → LISTENING
          vad_speech_end    → LISTENING → PROCESSING
          vad_timeout       → LISTENING → IDLE
          processing_done   → PROCESSING → SPEAKING
          interrupt         → PROCESSING/SPEAKING → INTERRUPTED
          speaking_done     → SPEAKING → IDLE
          interrupt_handled → INTERRUPTED → LISTENING
        """
        event_map: dict[str, dict[SessionState, SessionState]] = {
            "vad_speech_start":  {SessionState.IDLE: SessionState.LISTENING},
            "vad_speech_end":    {SessionState.LISTENING: SessionState.PROCESSING},
            "vad_timeout":       {SessionState.LISTENING: SessionState.IDLE},
            "processing_done":   {SessionState.PROCESSING: SessionState.SPEAKING},
            "speaking_done":     {SessionState.SPEAKING: SessionState.IDLE},
            "interrupt":         {
                SessionState.PROCESSING: SessionState.INTERRUPTED,
                SessionState.SPEAKING: SessionState.INTERRUPTED,
            },
            "interrupt_handled": {SessionState.INTERRUPTED: SessionState.LISTENING},
        }

        mapping = event_map.get(event, {})
        return mapping.get(self._state)

    # ── 事件监听 ──────────────────────────────────

    def on_transition(self, callback: Callable[..., Awaitable[None]]):
        """
        装饰器：注册状态转换监听器。

        回调签名: async def callback(from_state, to_state, event, reason)
        """
        self._listeners.append(callback)
        return callback

    # ── 重置 ──────────────────────────────────────

    async def reset(self) -> None:
        """重置状态机到 IDLE"""
        async with self._lock:
            self._cancel_event.set()  # 取消所有进行中的任务
            self._state = SessionState.IDLE
            self._cancel_event.clear()
            self._history.clear()
