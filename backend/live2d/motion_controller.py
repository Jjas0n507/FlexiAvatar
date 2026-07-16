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

    # Phase 1.2: 闭口阈值 (ms)
    CLOSE_GAP_THRESHOLD_MS = 200
    CLOSE_AFTER_LAST_MS = 100

    def phonemes_to_lip_sync(self, phonemes: list[Phoneme]) -> list[dict]:
        """
        将音素时间线转换为 Live2D 口型帧序列。

        Phase 1.2 改进:
        - 不再强制在每个音素后插入 N 帧
        - gap ≤ 200ms: 不插入闭口帧（前端自然插值过渡）
        - gap > 200ms: 插入闭口帧
        - 标点字符 (。！？) 强制闭口
        - 最后一个音素后追加闭口帧

        有 profile 时：仅输出模型支持的参数（open_y + form）。
        无 profile 时：fallback 到硬编码值（含 ParamMouthA/I/U/E/O）。
        """
        if not phonemes:
            return []

        _PUNCTUATION = frozenset({"。", "！", "？", "!", "?", ".", "\n"})
        frames: list[dict] = []

        for i, p in enumerate(phonemes):
            mouth = pinyin_final_to_mouth(p.phoneme)
            params = self._mouth_params(mouth)

            # Phase 1.4: 音量驱动口型缩放
            # open_y *= (0.3 + 0.7 * volume) — 最低保持 30% 开口
            # form *= volume
            volume = getattr(p, "volume", 0.5)
            if mouth != "N":  # 闭口帧不缩放
                scaled_params = dict(params)
                for key, val in scaled_params.items():
                    if self.profile is not None:
                        pid = self.profile.parameters
                        if key == pid.lip_open_y:
                            scaled_params[key] = round(val * (0.3 + 0.7 * volume), 3)
                        elif key == pid.lip_form:
                            scaled_params[key] = round(val * volume, 3)
                    else:
                        # Fallback: 检测参数名决定缩放方式
                        if "Open" in key:
                            scaled_params[key] = round(val * (0.3 + 0.7 * volume), 3)
                        elif "Form" in key:
                            scaled_params[key] = round(val * volume, 3)
                params = scaled_params

            # 当前音素的开口帧
            frames.append({
                "time_ms": p.start_ms,
                "mouth": mouth,
                "params": params,
            })

            # 决定是否需要在当前音素结束后插入闭口帧
            is_last = (i == len(phonemes) - 1)
            is_punctuation = p.char in _PUNCTUATION

            if is_punctuation:
                # 标点字符强制闭口
                frames.append({
                    "time_ms": p.end_ms,
                    "mouth": "N",
                    "params": self._mouth_params("N"),
                })
                continue

            if is_last:
                # 最后一个音素后追加闭口帧
                close_time = p.end_ms + self.CLOSE_AFTER_LAST_MS
                frames.append({
                    "time_ms": close_time,
                    "mouth": "N",
                    "params": self._mouth_params("N"),
                })
                continue

            # 检查与下一个音素的间隔
            next_p = phonemes[i + 1]
            gap = next_p.start_ms - p.end_ms
            if gap > self.CLOSE_GAP_THRESHOLD_MS:
                # 长间隔 → 插入闭口帧，在下个音素开始时重新开口
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

    # ── 分段情绪时间线 (Phase 2) ─────────────────

    @staticmethod
    def _split_text_to_segments(text: str) -> list[str]:
        """
        Phase 2.1: 按标点切分文本为情绪段。

        保留标点在片段末尾。
        """
        import re
        if not text or not text.strip():
            return []
        # 在句末标点处切分，保留标点
        parts = re.split(r"(?<=[。！？!?\n])", text.strip())
        return [p.strip() for p in parts if p.strip()]

    def build_timeline_message(
        self, text: str, phonemes: list[Phoneme], audio_start_time: float
    ) -> dict:
        """
        Phase 2.2: 构建混合时间线消息。

        将口型帧和分段表情合并为一条时间线，按 timeMs 排序。
        前端按时间线调度播放，消除单独的表情消息。

        Returns:
            {"command": "timeline", "entries": [...], "audio_start_time": ...}
        """
        entries: list[dict] = []

        # 1. 口型帧 → timeline entries
        lip_frames = self.phonemes_to_lip_sync(phonemes)
        for f in lip_frames:
            entries.append({
                "type": "mouth",
                "timeMs": f["time_ms"],
                "mouth": f.get("mouth", "N"),
                "params": f.get("params", {}),
            })

        # 2. 分段情绪 → timeline entries
        segments = self._split_text_to_segments(text)
        if segments:
            # 找到每个段对应的音素时间范围
            seg_phonemes = self._align_phonemes_to_segments(phonemes, segments)
            cum_offset = 0.0
            for seg_text, seg_ps in zip(segments, seg_phonemes):
                if not seg_ps:
                    cum_offset += 1000.0  # 无音素时粗略估计 1 秒
                    continue

                emotion = detect_emotion(seg_text)
                seg_start = seg_ps[0].start_ms
                seg_end = seg_ps[-1].end_ms

                if emotion != "neutral":
                    expr = self.get_expression_for_text(seg_text)
                    entries.append({
                        "type": "expression",
                        "timeMs": seg_start,
                        "expression": {
                            "name": expr.name,
                            "intensity": expr.intensity,
                            "fadeInMs": expr.fade_in_ms,
                            "durationMs": seg_end - seg_start,
                            "fadeOutMs": expr.fade_out_ms,
                        },
                    })

                cum_offset = seg_end

        # 3. 按 timeMs 排序
        entries.sort(key=lambda e: e["timeMs"])

        return {
            "command": "timeline",
            "entries": entries,
            "audio_start_time": audio_start_time,
        }

    @staticmethod
    def _align_phonemes_to_segments(
        phonemes: list[Phoneme], segments: list[str]
    ) -> list[list[Phoneme]]:
        """
        将 phoneme 列表按文本段大致对齐。

        策略：按 char 字段累积匹配到各段文本字符。
        """
        result: list[list[Phoneme]] = [[] for _ in segments]
        if not phonemes:
            return result

        # 收集所有 phoneme 的 char 并构建累积文本
        p_chars = [p.char for p in phonemes if p.char]
        if not p_chars:
            # fallback: 均匀分配
            n = len(phonemes)
            k = len(segments)
            size = max(1, n // k)
            for j in range(k):
                start = j * size
                end = start + size if j < k - 1 else n
                result[j] = phonemes[start:end]
            return result

        # 按 char 累计长度分配到最近的 segment
        seg_char_counts = [len(s) for s in segments]
        p_idx = 0
        char_count = 0
        for seg_idx, target_len in enumerate(seg_char_counts):
            seg_end = char_count + target_len
            while p_idx < len(phonemes) and char_count < seg_end:
                result[seg_idx].append(phonemes[p_idx])
                char_count += len(phonemes[p_idx].char)
                p_idx += 1
            char_count = seg_end  # 对齐到段边界

        # 将剩余 phoneme 分配给最后一个段
        while p_idx < len(phonemes):
            result[-1].append(phonemes[p_idx])
            p_idx += 1

        return result

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
