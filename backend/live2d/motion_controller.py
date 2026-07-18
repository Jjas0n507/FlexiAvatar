"""
Live2D 动画控制器。

会话状态 + 文本/语音情绪 → Live2D 控制指令。
控制指令通过 WebSocket 发送到前端 Cubism SDK 执行。

口型不在此处理：前端由 live2d-renderer 内置 RMS 音量驱动。

支持 ModelProfile: 传入则使用模型抽象层，不传则 fallback 到硬编码值。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.live2d.model_profile import ModelProfile


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

# SenseVoice 语音情绪 → Live2D 表情映射
# 用于将 SenseVoice 的 SER 输出映射到 Live2D 模型支持的表达式
_SPEECH_EMOTION_MAP: dict[str, str] = {
    "happy": "happy",
    "angry": "angry",
    "sad": "sad",
    "fearful": "surprised",
    "surprised": "surprised",
    "disgusted": "sad",
    "neutral": "neutral",
}


def detect_emotion(text: str, speech_emotion: str | None = None) -> str:
    """
    从文本和语音情绪中检测最终情绪。

    优先级：语音情绪（SenseVoice SER）> 文本关键词检测。
    语音情绪为非 neutral 时直接使用；neutral 或 None 时 fallback 到文本检测。

    Args:
        text: 待检测的文本
        speech_emotion: SenseVoice 识别的语音情绪，None 表示无语音情绪输入

    Returns:
        emotion name: "happy"/"angry"/"sad"/"surprised"/"thinking"/"neutral"
    """
    # 优先使用语音情绪
    if speech_emotion and speech_emotion != "neutral":
        mapped = _SPEECH_EMOTION_MAP.get(speech_emotion, speech_emotion)
        if mapped != "neutral":
            return mapped

    # Fallback: 文本关键词检测 (现有逻辑)
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


class MotionController:
    """
    Live2D 动画控制器。

    用法:
        # 新方式：传入 ModelProfile，使用模型抽象层
        ctrl = MotionController(profile=profile)

        # 旧方式：不传 profile，fallback 到硬编码值（向后兼容）
        ctrl = MotionController()

        # 从文本检测情绪
        expr = ctrl.get_expression_for_text("太棒了！")

        # 从会话状态获取动作
        motion = ctrl.get_motion_for_state("listening")

        # 生成打断指令
        cmd = ctrl.get_interrupt_command()
    """

    def __init__(self, profile: "ModelProfile | None" = None):
        self.profile = profile

    # ── 表情生成 ──────────────────────────────────

    def get_expression_for_text(self, text: str, speech_emotion: str | None = None) -> ExpressionCommand:
        """根据文本内容决定表情，可选传入语音情绪以覆盖文本检测"""
        emotion = detect_emotion(text, speech_emotion=speech_emotion)
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
            "idle_enabled": False,  # 暂停空闲动画
        }

    # ── 组合消息 ──────────────────────────────────

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
