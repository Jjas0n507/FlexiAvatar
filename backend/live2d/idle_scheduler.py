"""
空闲行为调度器 (Phase 3.1)。

在 IDLE 状态下生成生物本能行为指令：眨眼、视线漂移、歪头、表情循环。
前端 rAF 循环调用 idle engine 自主执行，此调度器负责生成指令。
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.live2d.model_profile import IdleConfig


class IdleBehaviorScheduler:
    """
    空闲行为调度器。

    用法:
        sched = IdleBehaviorScheduler(idle_config)
        while idle:
            commands = sched.tick(dt)
            for cmd in commands:
                websocket.send(cmd)

    每个 tick 可能返回多个命令，前端按序执行。
    """

    def __init__(self, config: "IdleConfig"):
        if config is None:
            raise ValueError("IdleConfig is required")
        self.config = config
        self.elapsed = 0.0
        self._reset_timers()

    def _reset_timers(self):
        """重置内部计时器到初始状态"""
        # 下一次各行为触发的时间
        self._next_blink = self._random_interval(*self.config.blink_interval)
        self._next_expression = self._random_interval(*self.config.expression_interval)
        self._next_eye_drift = self._random_interval(1.0, 3.0)
        self._next_head_tilt = self._random_interval(3.0, 8.0)
        # 眨眼持续时间
        self._blink_remaining = 0.0
        self._expr_index = 0

    def reset(self):
        """重置所有计时器（退出 IDLE 时调用）"""
        self.elapsed = 0.0
        self._reset_timers()

    def tick(self, dt: float) -> list[dict]:
        """
        推进 dt 秒，返回应执行的命令列表。

        Args:
            dt: 经过的时间（秒）

        Returns:
            [{"type": "blink", "params": {...}}, {"type": "expression", ...}, ...]
        """
        self.elapsed += dt
        commands: list[dict] = []

        # 1. 眨眼（优先处理，持续时间短）
        blink_cmd = self._tick_blink(dt)
        if blink_cmd:
            commands.append(blink_cmd)

        # 2. 视线漂移
        drift_cmd = self._tick_eye_drift()
        if drift_cmd:
            commands.append(drift_cmd)

        # 3. 歪头
        tilt_cmd = self._tick_head_tilt()
        if tilt_cmd:
            commands.append(tilt_cmd)

        # 4. 表情循环
        expr_cmd = self._tick_expression()
        if expr_cmd:
            commands.append(expr_cmd)

        return commands

    # ── 眨眼 ──────────────────────────────────────

    def _tick_blink(self, dt: float) -> dict | None:
        # 眨眼进行中
        if self._blink_remaining > 0:
            self._blink_remaining -= dt
            if self._blink_remaining <= 0:
                # 眨眼结束，恢复睁眼
                self._next_blink = self.elapsed + self._random_interval(*self.config.blink_interval)
                return {"type": "blink", "value": 1.0}  # 睁眼
            return None

        # 触发新眨眼
        if self.elapsed >= self._next_blink:
            self._blink_remaining = random.uniform(0.08, 0.15)  # 80-150ms
            return {"type": "blink", "value": 0.0}  # 闭眼

        return None

    # ── 视线漂移 ──────────────────────────────────

    def _tick_eye_drift(self) -> dict | None:
        if self.elapsed >= self._next_eye_drift:
            self._next_eye_drift = self.elapsed + self._random_interval(1.0, 4.0)
            r = self.config.eye_drift_range
            return {
                "type": "eye_drift",
                "x": round(random.uniform(-r, r), 3),
                "y": round(random.uniform(-r, r), 3),
            }
        return None

    # ── 歪头 ──────────────────────────────────────

    def _tick_head_tilt(self) -> dict | None:
        if self.elapsed >= self._next_head_tilt:
            self._next_head_tilt = self.elapsed + self._random_interval(4.0, 10.0)
            if random.random() < self.config.head_tilt_chance:
                angle = self.config.head_tilt_angle
                return {
                    "type": "head_tilt",
                    "angle": round(random.uniform(-angle, angle), 3),
                }
        return None

    # ── 表情循环 ──────────────────────────────────

    def _tick_expression(self) -> dict | None:
        if not self.config.expression_cycle:
            return None

        if self.elapsed >= self._next_expression:
            self._next_expression = self.elapsed + self._random_interval(
                *self.config.expression_interval
            )
            expr = self.config.expression_cycle[self._expr_index]
            self._expr_index = (self._expr_index + 1) % len(self.config.expression_cycle)
            return {
                "type": "expression",
                "name": expr,
                "fadeInMs": 300,
                "durationMs": 0,
                "fadeOutMs": 0,
            }
        return None

    # ── 辅助 ──────────────────────────────────────

    @staticmethod
    def _random_interval(lo: float, hi: float) -> float:
        return random.uniform(lo, hi)
