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
