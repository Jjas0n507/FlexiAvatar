"""
Live2D 动画控制器。

将 TTS 音素时间线 + 会话状态 + 文本情绪 → Live2D 控制指令。
控制指令通过 WebSocket 发送到前端 Cubism SDK 执行。

核心功能:
- 音素 → 口型参数映射 (A, I, U, E, O)
- 状态驱动的表情选择
- 情绪关键词检测

支持 ModelProfile: 传入则使用模型抽象层，不传则 fallback 到硬编码值。
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from backend.tts.base import Phoneme

if TYPE_CHECKING:
    from backend.live2d.model_profile import ModelProfile


# ── 口型映射表 ──────────────────────────────────
# 已提取到 backend.live2d.mouth_shapes。保留此别名用于向后兼容。
# TODO(Phase 0.5): 删除此别名，所有引用改为直接从 mouth_shapes import
from backend.live2d.mouth_shapes import PINYIN_TO_MOUTH as _PHONEME_TO_MOUTH, pinyin_final_to_mouth  # noqa: F401


# ── 情绪关键词 ──────────────────────────────────

_EMOTION_KEYWORDS: dict[str, list[str]] = {
    "happy": [
        "开心", "高兴", "快乐", "太好了", "棒", "哈哈",
        "恭喜", "喜欢", "爱", "有趣", "好玩",
    ],
    "sad": [
        "难过", "伤心", "遗憾", "可惜", "对不起", "抱歉",
        "失败", "糟糕", "不好", "倒霉",
    ],
    "surprised": [
        "哇", "天哪", "不会吧", "真的吗", "竟然", "居然",
        "不可思议", "震惊", "惊奇",
    ],
    "thinking": [
        "我想想", "让我想想", "嗯", "呃", "等等",
    ],
}


def detect_emotion(text: str) -> str:
    """从文本中检测情绪，返回 emotion name"""
    scores = {}
    for emotion, keywords in _EMOTION_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scores[emotion] = score
    if not scores:
        return "neutral"
    return max(scores, key=scores.get)


# ── 控制指令数据类 ──────────────────────────────

@dataclass
class LipSyncFrame:
    """口型帧"""
    mouth: str          # A, I, U, E, O, N
    value: float        # 0.0 ~ 1.0
    time_ms: float      # 达到该值的时间点 (相对于音频起始)


@dataclass
class ExpressionCommand:
    """表情指令"""
    name: str           # 表情名称
    intensity: float    # 0.0 ~ 1.0
    fade_in_ms: float = 300
    duration_ms: float = 0  # 0 = 保持
    fade_out_ms: float = 300


@dataclass
class MotionCommand:
    """身体动作指令"""
    group: str          # 动作组名
    index: int = 0      # 动作编号
    priority: int = 1   # 优先级


@dataclass
class Live2DControlMessage:
    """一次完整的 Live2D 控制指令"""
    command: str  # lip_sync | expression | motion | idle | reset | interrupt
    lip_sync_frames: list[dict] = field(default_factory=list)
    expression: dict | None = None
    motion: dict | None = None
    idle_enabled: bool = True
    audio_start_time: float = 0.0  # 前端 audioContext.currentTime


class MotionController:
    """
    Live2D 动画控制器。

    用法:
        # 新方式：传入 ModelProfile，使用模型抽象层
        ctrl = MotionController(profile=profile)

        # 旧方式：不传 profile，fallback 到硬编码值（向后兼容）
        ctrl = MotionController()

        # 从 TTS 结果生成口型帧
        frames = ctrl.phonemes_to_lip_sync(phonemes)

        # 从文本检测情绪
        expr = ctrl.get_expression_for_text("太棒了！")

        # 从会话状态获取动作
        motion = ctrl.get_motion_for_state("listening")

        # 生成打断指令
        cmd = ctrl.get_interrupt_command()
    """

    def __init__(self, profile: "ModelProfile | None" = None):
        self.profile = profile

    # ── 口型生成 ──────────────────────────────────

    def phonemes_to_lip_sync(self, phonemes: list[Phoneme]) -> list[dict]:
        """
        将音素时间线转换为 Live2D 口型帧序列。

        有 profile 时：仅输出模型支持的参数（open_y + form）。
        无 profile 时：fallback 到硬编码值（含 ParamMouthA/I/U/E/O）。
        """
        frames = []
        for p in phonemes:
            mouth = pinyin_final_to_mouth(p.phoneme)
            params = self._mouth_params(mouth)
            frames.append({
                "time_ms": p.start_ms,
                "mouth": mouth,
                "params": params,
            })
            # 在音素结束时添加一个"闭合"帧作为过渡
            frames.append({
                "time_ms": p.end_ms,
                "mouth": "N",
                "params": self._mouth_params("N"),
            })
        return frames

    def _mouth_params(self, mouth: str) -> dict[str, float]:
        """将口型符号映射到 Live2D Cubism 参数。有 profile 时使用模型实际参数 ID。"""
        if self.profile is not None:
            # 从 profile 读取模型实际支持的参数 ID 和口型值
            pid = self.profile.parameters
            shape = self.profile.mouth_shapes.get(mouth)
            if shape is not None:
                return {
                    pid.lip_open_y: shape.open_y,
                    pid.lip_form: shape.form,
                }
            # 未知口型 → 闭嘴
            return {
                pid.lip_open_y: 0.0,
                pid.lip_form: 0.0,
            }

        # Fallback: 旧硬编码值（向后兼容）
        mapping = {
            "A": {"ParamMouthOpenY": 0.8, "ParamMouthA": 1.0},
            "I": {"ParamMouthOpenY": 0.3, "ParamMouthForm": 0.8, "ParamMouthI": 1.0},
            "U": {"ParamMouthOpenY": 0.3, "ParamMouthForm": -0.5, "ParamMouthU": 1.0},
            "E": {"ParamMouthOpenY": 0.5, "ParamMouthE": 1.0},
            "O": {"ParamMouthOpenY": 0.6, "ParamMouthO": 1.0},
            "N": {"ParamMouthOpenY": 0.0},  # 闭嘴
        }
        return mapping.get(mouth, mapping["N"])

    # ── 表情生成 ──────────────────────────────────

    def get_expression_for_text(self, text: str) -> ExpressionCommand:
        """根据文本内容决定表情"""
        emotion = detect_emotion(text)
        intensity_map = {
            "neutral": 0.0,
            "happy": 0.8,
            "sad": 0.6,
            "surprised": 1.0,
            "thinking": 0.5,
        }
        return ExpressionCommand(
            name=emotion,
            intensity=intensity_map.get(emotion, 0.0),
            fade_in_ms=200,
            duration_ms=3000,
            fade_out_ms=500,
        )

    def get_expression_for_state(self, state: str) -> ExpressionCommand:
        """根据会话状态决定表情"""
        state_expr = {
            "idle": ("neutral", 0.0),
            "listening": ("neutral", 0.3),
            "processing": ("thinking", 0.5),
            "speaking": ("neutral", 0.0),  # 说话时的表情由文本决定
            "interrupted": ("surprised", 0.8),
        }
        name, intensity = state_expr.get(state, ("neutral", 0.0))
        return ExpressionCommand(name=name, intensity=intensity)

    # ── 动作生成 ──────────────────────────────────

    def get_motion_for_state(self, state: str) -> MotionCommand | None:
        """根据会话状态决定身体动作。有 profile 时使用模型实际的 motion group 名。"""
        if self.profile is not None:
            motion_defs = self.profile.motions.get(state)
            if not motion_defs:
                return None
            d = random.choice(motion_defs)
            return MotionCommand(group=d.group, index=d.index, priority=1)

        # Fallback: 旧硬编码值（向后兼容）
        state_motions = {
            "listening": [("listen", 0), ("listen", 1)],
            "processing": [("think", 0)],
            "idle": [("idle", 0), ("idle", 1), ("idle", 2)],
        }
        group = state_motions.get(state)
        if group is None:
            return None
        g, idx = random.choice(group)
        return MotionCommand(group=g, index=idx, priority=1)

    # ── 打断指令 ──────────────────────────────────

    def get_interrupt_command(self) -> dict:
        """生成打断时的 Live2D 控制指令"""
        return {
            "command": "interrupt",
            "expression": {"name": "surprised", "intensity": 0.9, "fadeInMs": 50, "durationMs": 1500, "fadeOutMs": 500},
            "lip_sync_frames": [],  # 停止口型
            "idle_enabled": False,  # 暂停空闲动画
        }

    # ── 组合消息 ──────────────────────────────────

    def build_lip_sync_message(
        self, phonemes: list[Phoneme], audio_start_time: float
    ) -> dict:
        """构建口型同步 WebSocket 消息"""
        frames = self.phonemes_to_lip_sync(phonemes)
        return {
            "command": "lip_sync",
            "lip_sync_frames": frames,
            "audio_start_time": audio_start_time,
        }

    def build_expression_message(self, expr: ExpressionCommand) -> dict:
        """构建表情控制 WebSocket 消息"""
        return {
            "command": "expression",
            "expression": {
                "name": expr.name,
                "intensity": expr.intensity,
                "fadeInMs": expr.fade_in_ms,
                "durationMs": expr.duration_ms,
                "fadeOutMs": expr.fade_out_ms,
            },
        }

    def build_motion_message(self, motion: MotionCommand) -> dict:
        """构建动作控制 WebSocket 消息"""
        return {
            "command": "motion",
            "motion": {
                "group": motion.group,
                "index": motion.index,
                "priority": motion.priority,
            },
        }

    def build_state_message(self, state: str) -> dict:
        """根据状态构建综合 Live2D 控制消息"""
        expr = self.get_expression_for_state(state)
        motion = self.get_motion_for_state(state)
        msg = {
            "command": "state",
            "state": state,
        }
        msg["expression"] = {
            "name": expr.name,
            "intensity": expr.intensity,
        }
        if motion:
            msg["motion"] = {
                "group": motion.group,
                "index": motion.index,
                "priority": motion.priority,
            }
        return msg
