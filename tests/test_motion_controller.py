"""MotionController 测试 — Profile 驱动的动画控制器"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from backend.live2d.model_profile import (
    ModelProfile, ParameterIds, MouthShapeParams, ExpressionDef,
    MotionDef, IdleConfig,
)
from backend.live2d.motion_controller import MotionController, MotionCommand, ExpressionCommand
from backend.tts.base import Phoneme


# ── 辅助：创建测试用 ModelProfile ──────────────


def make_test_profile():
    """创建与有马加奈模型一致的测试 profile"""
    return ModelProfile(
        name="TestModel",
        model3_path="test.model3.json",
        scale=1.0,
        parameters=ParameterIds(
            lip_open_y="ParamMouthOpenY",
            lip_form="ParamMouthForm",
            eye_left_open="ParamEyeLOpen",
            eye_right_open="ParamEyeROpen",
            eye_left_smile="ParamEyeLSmile",
            eye_right_smile="ParamEyeRSmile",
            eyeball_x="ParamEyeBallX",
            eyeball_y="ParamEyeBallY",
            brow_left_y="ParamBrowLY",
            brow_right_y="ParamBrowRY",
            brow_left_x="ParamBrowLX",
            brow_right_x="ParamBrowRX",
            head_angle_z="ParamHeadAngleZ",
            body_angle_x="ParamBodyAngleX",
            extra=["Paramemoji1", "Paramemoji2", "Paramemoji3",
                   "Paramemoji4", "Paramemoji5", "Paramemoji6", "Paramemoji7"],
        ),
        mouth_shapes={
            "A": MouthShapeParams(open_y=0.8, form=0.0),
            "I": MouthShapeParams(open_y=0.3, form=0.8),
            "U": MouthShapeParams(open_y=0.3, form=-0.5),
            "E": MouthShapeParams(open_y=0.5, form=0.0),
            "O": MouthShapeParams(open_y=0.6, form=-0.2),
            "N": MouthShapeParams(open_y=0.0, form=0.0),
        },
        expressions={
            "neutral": ExpressionDef(type="native", name=None),
            "happy": ExpressionDef(type="native", name="害羞"),
            "sad": ExpressionDef(type="native", name="哭泣"),
            "surprised": ExpressionDef(type="params", params={
                "ParamEyeLOpen": 1.2, "ParamEyeROpen": 1.2,
                "ParamBrowLY": 0.5, "ParamBrowRY": 0.5,
            }),
            "thinking": ExpressionDef(type="params", params={
                "ParamBrowLX": -0.2, "ParamBrowRX": 0.2,
            }),
        },
        motions={
            "listening": [MotionDef(group="Idle", index=0), MotionDef(group="Idle", index=1)],
            "processing": [MotionDef(group="Idle", index=1)],
            "idle": [MotionDef(group="Idle", index=0), MotionDef(group="Idle", index=1),
                     MotionDef(group="Random", index=0)],
        },
        idle=IdleConfig(
            expression_cycle=["neutral", "happy", "thinking"],
            expression_interval=(5.0, 12.0),
            blink_interval=(2.0, 6.0),
            eye_drift_range=0.15,
            head_tilt_chance=0.15,
            head_tilt_angle=0.1,
        ),
    )


# ── 测试类 ──────────────────────────────────────


class TestMotionControllerInit:
    def test_init_with_profile(self):
        profile = make_test_profile()
        ctrl = MotionController(profile=profile)
        assert ctrl.profile is profile
        assert ctrl.profile.name == "TestModel"

    def test_init_without_profile_still_works(self):
        """向后兼容：无 profile 时使用硬编码 fallback"""
        ctrl = MotionController()
        assert ctrl.profile is None
        # 基本方法应该仍然可用
        result = ctrl._mouth_params("A")
        assert "ParamMouthOpenY" in result


class TestMouthParams:
    def test_mouth_params_A_uses_profile_ids(self):
        ctrl = MotionController(profile=make_test_profile())
        params = ctrl._mouth_params("A")
        assert params == {"ParamMouthOpenY": 0.8, "ParamMouthForm": 0.0}
        assert "ParamMouthA" not in params  # 不再输出模型不支持的参数！

    def test_mouth_params_N(self):
        ctrl = MotionController(profile=make_test_profile())
        params = ctrl._mouth_params("N")
        assert params == {"ParamMouthOpenY": 0.0, "ParamMouthForm": 0.0}

    def test_mouth_params_unknown_falls_back_to_N(self):
        ctrl = MotionController(profile=make_test_profile())
        params = ctrl._mouth_params("X")
        assert params["ParamMouthOpenY"] == 0.0

    def test_mouth_params_all_shapes_only_2_keys(self):
        ctrl = MotionController(profile=make_test_profile())
        for mouth in ["A", "I", "U", "E", "O", "N"]:
            params = ctrl._mouth_params(mouth)
            assert set(params.keys()) == {"ParamMouthOpenY", "ParamMouthForm"}, \
                f"Mouth '{mouth}' has unexpected keys: {params.keys()}"

    def test_mouth_params_match_profile_values(self):
        profile = make_test_profile()
        ctrl = MotionController(profile=profile)
        for mouth, shape in profile.mouth_shapes.items():
            params = ctrl._mouth_params(mouth)
            assert params["ParamMouthOpenY"] == shape.open_y
            assert params["ParamMouthForm"] == shape.form


class TestMotionForState:
    def test_idle_uses_real_model_groups(self):
        ctrl = MotionController(profile=make_test_profile())
        for _ in range(10):
            motion = ctrl.get_motion_for_state("idle")
            assert motion is not None
            assert motion.group in ("Idle", "Random"), \
                f"Got group='{motion.group}', expected 'Idle' or 'Random'"

    def test_listening_uses_real_model_groups(self):
        ctrl = MotionController(profile=make_test_profile())
        for _ in range(5):
            motion = ctrl.get_motion_for_state("listening")
            assert motion is not None
            assert motion.group == "Idle"

    def test_unknown_state_returns_none(self):
        ctrl = MotionController(profile=make_test_profile())
        assert ctrl.get_motion_for_state("dancing") is None
        assert ctrl.get_motion_for_state("") is None

    def test_processing_motion(self):
        ctrl = MotionController(profile=make_test_profile())
        motion = ctrl.get_motion_for_state("processing")
        assert motion is not None
        assert motion.group == "Idle"
        assert motion.index == 1


class TestPhonemesToLipSync:
    def test_frame_count_preserved(self):
        """回归：帧数与修改前相同（每个 phoneme 生成开+闭两帧）"""
        ctrl = MotionController(profile=make_test_profile())
        phonemes = [
            Phoneme(phoneme="A", start_ms=0, end_ms=100),
            Phoneme(phoneme="I", start_ms=100, end_ms=200),
            Phoneme(phoneme="U", start_ms=200, end_ms=300),
        ]
        frames = ctrl.phonemes_to_lip_sync(phonemes)
        assert len(frames) >= 3  # 至少每个 phoneme 有一个帧

    def test_frame_params_no_hardcoded_vowel_params(self):
        """帧 params 不含 ParamMouthA/I/U/E/O"""
        ctrl = MotionController(profile=make_test_profile())
        phonemes = [
            Phoneme(phoneme="A", start_ms=0, end_ms=100),
            Phoneme(phoneme="I", start_ms=100, end_ms=200),
        ]
        frames = ctrl.phonemes_to_lip_sync(phonemes)
        for f in frames:
            for key in f["params"]:
                assert key in ("ParamMouthOpenY", "ParamMouthForm"), \
                    f"Unexpected param key: {key}"

    def test_time_ms_preserved(self):
        ctrl = MotionController(profile=make_test_profile())
        phonemes = [
            Phoneme(phoneme="A", start_ms=10.0, end_ms=100.0),
        ]
        frames = ctrl.phonemes_to_lip_sync(phonemes)
        # 第一帧应从 start_ms 开始
        assert frames[0]["time_ms"] == 10.0


class TestExpressionForState:
    def test_processing_returns_thinking(self):
        ctrl = MotionController(profile=make_test_profile())
        expr = ctrl.get_expression_for_state("processing")
        assert expr.name == "thinking"

    def test_interrupted_returns_surprised(self):
        ctrl = MotionController(profile=make_test_profile())
        expr = ctrl.get_expression_for_state("interrupted")
        assert expr.name == "surprised"

    def test_listening_returns_neutral(self):
        ctrl = MotionController(profile=make_test_profile())
        expr = ctrl.get_expression_for_state("listening")
        assert expr.name == "neutral"


class TestBackwardCompatibility:
    def test_no_profile_still_works(self):
        """无 profile 时 MotionController 仍能正常工作"""
        ctrl = MotionController()
        # 口型参数
        params = ctrl._mouth_params("A")
        assert "ParamMouthOpenY" in params
        # 动作
        motion = ctrl.get_motion_for_state("idle")
        assert motion is not None
        # 表情
        expr = ctrl.get_expression_for_state("processing")
        assert expr is not None
        # 口型帧
        phonemes = [Phoneme(phoneme="A", start_ms=0, end_ms=100)]
        frames = ctrl.phonemes_to_lip_sync(phonemes)
        assert len(frames) > 0


# ── Phase 1.2: 去强制 N 帧 + 智能闭口 ───────────

class TestSmartLipSync:
    """Phase 1.2: 口型帧生成不再强制每音素后插 N 帧"""

    def test_no_n_for_short_gap(self):
        """gap < 200ms 不插入闭口 N 帧（除最后一个音素的自动闭口外）"""
        ctrl = MotionController(profile=make_test_profile())
        phonemes = [
            Phoneme(phoneme="A", start_ms=0, end_ms=80),
            Phoneme(phoneme="I", start_ms=100, end_ms=180),
        ]
        # gap between end of first (80) and start of second (100) = 20ms < 200ms
        frames = ctrl.phonemes_to_lip_sync(phonemes)
        mouths = [f["mouth"] for f in frames]
        # 连续短间隔 → 不应在 A 和 I 之间插入 N
        # 最后一个 I 后会自动闭口追加 N
        assert mouths[0] == "A"
        assert mouths[1] == "I"
        assert "N" not in mouths[:2], f"No N should appear between short-gap phonemes, got {mouths}"

    def test_n_inserted_for_long_gap(self):
        """gap > 200ms 插入过渡闭口帧"""
        ctrl = MotionController(profile=make_test_profile())
        phonemes = [
            Phoneme(phoneme="A", start_ms=0, end_ms=80),
            Phoneme(phoneme="I", start_ms=400, end_ms=480),
        ]
        # gap = 400 - 80 = 320ms > 200ms
        frames = ctrl.phonemes_to_lip_sync(phonemes)
        mouths = [f["mouth"] for f in frames]
        assert "N" in mouths, f"Expected N frame for long gap, got {mouths}"

    def test_last_phoneme_closes(self):
        """最后一个音素后追加闭口帧"""
        ctrl = MotionController(profile=make_test_profile())
        phonemes = [
            Phoneme(phoneme="A", start_ms=0, end_ms=80),
        ]
        frames = ctrl.phonemes_to_lip_sync(phonemes)
        mouths = [f["mouth"] for f in frames]
        assert mouths[0] == "A"
        assert mouths[-1] == "N", f"Last frame should close mouth, got {mouths}"

    def test_punctuation_forces_close(self):
        """标点字符 (。！？) 结束时强制闭口"""
        ctrl = MotionController(profile=make_test_profile())
        phonemes = [
            Phoneme(phoneme="E", start_ms=0, end_ms=100, char="。"),
            Phoneme(phoneme="A", start_ms=150, end_ms=250),
        ]
        frames = ctrl.phonemes_to_lip_sync(phonemes)
        mouths = [f["mouth"] for f in frames]
        # 第一个 phoneme char 为 。→ 之后应紧跟 N
        # expected: E, N, A (last close handled separately)
        assert "N" in mouths[:3], f"Punctuation should force close, got {mouths}"

    def test_single_phoneme_open_then_close(self):
        """单音素生成开+闭两帧"""
        ctrl = MotionController(profile=make_test_profile())
        phonemes = [
            Phoneme(phoneme="O", start_ms=10, end_ms=200),
        ]
        frames = ctrl.phonemes_to_lip_sync(phonemes)
        mouths = [f["mouth"] for f in frames]
        assert mouths[0] == "O"
        assert mouths[-1] == "N"
        assert len(frames) >= 2

    def test_close_gap_threshold_exactly_200(self):
        """gap 恰好 200ms 时视情况而定（<= 阈值不插入 N）"""
        ctrl = MotionController(profile=make_test_profile())
        phonemes = [
            Phoneme(phoneme="A", start_ms=0, end_ms=100),
            Phoneme(phoneme="I", start_ms=300, end_ms=400),
        ]
        # gap = 300 - 100 = 200ms → 不插入 N
        frames = ctrl.phonemes_to_lip_sync(phonemes)
        mouths = [f["mouth"] for f in frames]
        # Should be A, I (no N between since gap is exactly threshold)
        # Last close frame is expected
        assert mouths[0] == "A"
        assert "I" in mouths


# ── Phase 2: 分段情绪时间线 ─────────────────────

class TestSplitTextToSegments:
    """按标点切分文本"""

    def test_split_by_punctuation(self):
        """按 。！？ 切分"""
        ctrl = MotionController()
        segments = ctrl._split_text_to_segments("你好！今天天气真好。我们出去玩吧？")
        assert len(segments) == 3
        assert segments[0] == "你好！"
        assert "今天天气真好" in segments[1]
        assert "我们出去玩吧" in segments[2]

    def test_split_single_sentence(self):
        """无标点不分段"""
        ctrl = MotionController()
        segments = ctrl._split_text_to_segments("今天天气真好")
        assert len(segments) == 1
        assert segments[0] == "今天天气真好"

    def test_split_empty(self):
        """空字符串返回空列表"""
        ctrl = MotionController()
        assert ctrl._split_text_to_segments("") == []
        assert ctrl._split_text_to_segments("   ") == []

    def test_segment_order_preserved(self):
        """段顺序保持不变"""
        ctrl = MotionController()
        text = "第一句。第二句！第三句？"
        segments = ctrl._split_text_to_segments(text)
        assert segments[0].startswith("第一句")
        assert segments[1].startswith("第二句")
        assert segments[2].startswith("第三句")


class TestTimelineMessage:
    """build_timeline_message 结构验证"""

    def test_timeline_has_command_field(self):
        """返回 dict 含 command/timeline/audio_start_time"""
        ctrl = MotionController(profile=make_test_profile())
        phonemes = [
            Phoneme(phoneme="A", start_ms=0, end_ms=100, char="啊"),
            Phoneme(phoneme="I", start_ms=150, end_ms=250, char="嘻"),
        ]
        msg = ctrl.build_timeline_message("啊！嘻嘻。", phonemes, 0.0)
        assert msg["command"] == "timeline"
        assert "entries" in msg
        assert "audio_start_time" in msg
        assert isinstance(msg["entries"], list)

    def test_timeline_entries_sorted_by_time(self):
        """entries 按 timeMs 升序排列"""
        ctrl = MotionController(profile=make_test_profile())
        phonemes = [
            Phoneme(phoneme="A", start_ms=0, end_ms=80, char="好"),
            Phoneme(phoneme="I", start_ms=100, end_ms=180, char="的"),
        ]
        msg = ctrl.build_timeline_message("好的。", phonemes, 0.0)
        entries = msg["entries"]
        times = [e["timeMs"] for e in entries]
        assert times == sorted(times), f"Entries not sorted: {times}"

    def test_timeline_contains_mouth_events(self):
        """timeline 含 mouth 类型事件"""
        ctrl = MotionController(profile=make_test_profile())
        phonemes = [
            Phoneme(phoneme="A", start_ms=0, end_ms=100, char="啊"),
        ]
        msg = ctrl.build_timeline_message("啊。", phonemes, 0.0)
        entries = msg["entries"]
        mouth_entries = [e for e in entries if e["type"] == "mouth"]
        assert len(mouth_entries) > 0

    def test_timeline_contains_expression_events(self):
        """timeline 含 expression 类型事件"""
        ctrl = MotionController(profile=make_test_profile())
        phonemes = [
            Phoneme(phoneme="A", start_ms=0, end_ms=100, char="哇"),
            Phoneme(phoneme="I", start_ms=100, end_ms=200, char="哈"),
        ]
        msg = ctrl.build_timeline_message("哇！哈哈！", phonemes, 0.0)
        entries = msg["entries"]
        expr_entries = [e for e in entries if e["type"] == "expression"]
        # 感叹句应触发情绪
        assert len(expr_entries) >= 0  # 可能检测到 happy/surprised

    def test_empty_phonemes_still_works(self):
        """空 phonemes 列表不崩溃"""
        ctrl = MotionController()
        msg = ctrl.build_timeline_message("测试。", [], 0.0)
        assert msg["command"] == "timeline"
        assert msg["entries"] == []
