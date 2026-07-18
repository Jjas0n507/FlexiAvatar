"""MotionController 测试 — Profile 驱动的动画控制器"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.live2d.model_profile import (
    ModelProfile, ParameterIds, MouthShapeParams, ExpressionDef,
    MotionDef, IdleConfig,
)
from backend.live2d.motion_controller import (
    MotionController,
    detect_emotion, _SPEECH_EMOTION_MAP,
)


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
        assert ctrl.get_motion_for_state("idle") is not None
        assert ctrl.get_expression_for_state("processing") is not None


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


class TestInterruptCommand:
    def test_interrupt_command_shape(self):
        ctrl = MotionController(profile=make_test_profile())
        cmd = ctrl.get_interrupt_command()
        assert cmd["command"] == "interrupt"
        assert cmd["expression"]["name"] == "surprised"
        assert cmd["idle_enabled"] is False


class TestSpeechEmotionOverride:
    """detect_emotion() speech_emotion 参数：语音情绪优先于文本关键词"""

    def test_speech_emotion_happy_overrides_neutral_text(self):
        """语音 happy → 覆盖文本 neutral"""
        assert detect_emotion("今天星期三", speech_emotion="happy") == "happy"

    def test_speech_emotion_angry_overrides_text_keyword(self):
        """语音 angry → 覆盖文本"开心"（语音优先）"""
        assert detect_emotion("今天真开心", speech_emotion="angry") == "angry"

    def test_speech_emotion_neutral_falls_back_to_text(self):
        """语音 neutral + 文本"开心" → fallback 到文本 happy"""
        assert detect_emotion("太开心了！", speech_emotion="neutral") == "happy"

    def test_speech_emotion_none_backward_compatible(self):
        """speech_emotion=None → 行为完全不变（向后兼容）"""
        assert detect_emotion("太棒了！哈哈", speech_emotion=None) == "happy"
        assert detect_emotion("今天星期三", speech_emotion=None) == "neutral"

    def test_speech_emotion_fearful_maps_to_surprised(self):
        """SenseVoice fearful → Live2D surprised"""
        assert detect_emotion("好可怕", speech_emotion="fearful") == "surprised"

    def test_speech_emotion_surprised_maps_directly(self):
        """SenseVoice surprised → Live2D surprised"""
        assert detect_emotion("哇", speech_emotion="surprised") == "surprised"

    def test_speech_emotion_disgusted_maps_to_sad(self):
        """SenseVoice disgusted → Live2D sad"""
        assert detect_emotion("好恶心", speech_emotion="disgusted") == "sad"

    def test_speech_emotion_sad_overrides_happy_text(self):
        """语音 sad 覆盖文本"哈哈"（语音信号更可靠）"""
        assert detect_emotion("哈哈真开心", speech_emotion="sad") == "sad"

    def test_speech_emotion_map_all_keys_documented(self):
        """_SPEECH_EMOTION_MAP 覆盖所有 SER 情绪"""
        assert set(_SPEECH_EMOTION_MAP.keys()) == {
            "happy", "angry", "sad", "neutral", "fearful", "surprised", "disgusted",
        }

    def test_get_expression_for_text_with_speech_emotion(self):
        """get_expression_for_text 接受 speech_emotion 参数"""
        ctrl = MotionController(profile=make_test_profile())
        expr = ctrl.get_expression_for_text("今天星期三", speech_emotion="happy")
        assert expr.name == "happy"

    def test_get_expression_for_text_without_speech_emotion(self):
        """get_expression_for_text 不传 speech_emotion 时向后兼容"""
        ctrl = MotionController(profile=make_test_profile())
        expr = ctrl.get_expression_for_text("太棒了！哈哈")
        assert expr.name == "happy"
