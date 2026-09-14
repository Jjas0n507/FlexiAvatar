"""DigitalHumanProfile 测试 — YAML 加载 / 两类 schema / 校验 / 序列化"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from backend.avatar.avatar_profile import (
    DigitalHumanProfile,
    ExpressionDef,
    MouthOpenDef,
)


def _minimal(**over):
    data = {
        "name": "测试形象",
        "model_path": "avatar.glb",
        "expressions": {"neutral": {"type": "blendshapes", "params": {}}},
    }
    data.update(over)
    return data


class TestBasicLoading:
    def test_from_dict_minimal(self):
        p = DigitalHumanProfile.from_dict(_minimal())
        assert p.name == "测试形象"
        assert p.model_path == "avatar.glb"
        assert set(p.expressions) == {"neutral"}

    def test_load_from_file(self, tmp_path):
        f = tmp_path / "avatar_profile.yaml"
        f.write_text(
            "name: 文件形象\n"
            "model_path: a.glb\n"
            "expressions:\n"
            "  neutral: {type: blendshapes, params: {}}\n",
            encoding="utf-8",
        )
        p = DigitalHumanProfile.load(f)
        assert p.name == "文件形象"
        assert p.source_path == str(f)

    def test_load_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            DigitalHumanProfile.load(tmp_path / "nope.yaml")

    def test_load_empty_yaml(self, tmp_path):
        f = tmp_path / "avatar_profile.yaml"
        f.write_text("", encoding="utf-8")
        with pytest.raises(ValueError):
            DigitalHumanProfile.load(f)

    def test_missing_name_rejected(self):
        with pytest.raises(ValueError, match="name"):
            DigitalHumanProfile.from_dict({"model_path": "a.glb"})

    def test_missing_model_path_rejected(self):
        with pytest.raises(ValueError, match="model_path"):
            DigitalHumanProfile.from_dict({"name": "x"})


class TestExpressionSchema:
    """两类模型通吃：blendshapes（多 morph 加权）与 morph（单整脸 morph）"""

    def test_blendshapes_form(self):
        p = DigitalHumanProfile.from_dict(_minimal(expressions={
            "neutral": {"type": "blendshapes", "params": {}},
            "happy": {"type": "blendshapes", "params": {"mouthSmile_L": 0.6}},
        }))
        assert p.expressions["happy"].type == "blendshapes"
        assert p.expressions["happy"].params == {"mouthSmile_L": 0.6}
        assert p.expressions["happy"].morph_names == ["mouthSmile_L"]

    def test_morph_form(self):
        """RobotExpressive 类：没有逐 blendshape，只有整脸 morph"""
        p = DigitalHumanProfile.from_dict(_minimal(expressions={
            "neutral": {"type": "blendshapes", "params": {}},
            "happy": {"type": "morph", "name": "Angry"},
        }))
        assert p.expressions["happy"].type == "morph"
        assert p.expressions["happy"].name == "Angry"
        assert p.expressions["happy"].morph_names == ["Angry"]

    def test_bare_weight_table_shorthand(self):
        """裸权重表写法等价于 blendshapes"""
        p = DigitalHumanProfile.from_dict(_minimal(expressions={
            "neutral": {},
            "happy": {"mouthSmile_L": 0.6, "mouthSmile_R": 0.5},
        }))
        assert p.expressions["happy"].type == "blendshapes"
        assert p.expressions["happy"].params["mouthSmile_R"] == 0.5

    def test_invalid_expression_type(self):
        with pytest.raises(ValueError, match="type 非法"):
            DigitalHumanProfile.from_dict(_minimal(expressions={
                "neutral": {},
                "happy": {"type": "wat"},
            }))

    def test_morph_without_name_rejected(self):
        with pytest.raises(ValueError, match="缺少 name"):
            DigitalHumanProfile.from_dict(_minimal(expressions={
                "neutral": {},
                "happy": {"type": "morph"},
            }))

    def test_non_numeric_weight_rejected(self):
        with pytest.raises(ValueError, match="不是数字"):
            DigitalHumanProfile.from_dict(_minimal(expressions={
                "neutral": {},
                "happy": {"mouthSmile_L": "a lot"},
            }))


class TestMouthOpen:
    def test_string_form_is_morph_kind(self):
        p = DigitalHumanProfile.from_dict(_minimal(morphs={"mouth_open": "jawOpen"}))
        assert p.mouth_open == MouthOpenDef(kind="morph", name="jawOpen")
        assert p.mouth_open.morph_names == ["jawOpen"]

    def test_add_form_is_proxy(self):
        """无嘴部 morph 的模型：发声时整体加偏置"""
        p = DigitalHumanProfile.from_dict(_minimal(
            morphs={"mouth_open": {"add": "Surprised", "amount": 0.4}},
        ))
        assert p.mouth_open.kind == "add"
        assert p.mouth_open.name == "Surprised"
        assert p.mouth_open.amount == 0.4
        assert p.mouth_open.to_frontend_dict() == {
            "kind": "add", "name": "Surprised", "amount": 0.4,
        }

    def test_add_default_amount(self):
        p = DigitalHumanProfile.from_dict(_minimal(morphs={"mouth_open": {"add": "Angry"}}))
        assert p.mouth_open.amount == 0.35

    def test_absent_mouth_open(self):
        p = DigitalHumanProfile.from_dict(_minimal(morphs={}))
        assert p.mouth_open is None

    def test_invalid_mouth_open(self):
        with pytest.raises(ValueError, match="mouth_open"):
            DigitalHumanProfile.from_dict(_minimal(morphs={"mouth_open": 42}))


class TestValidation:
    def test_empty_expressions_rejected(self):
        with pytest.raises(ValueError, match="expressions 为空"):
            DigitalHumanProfile.from_dict(_minimal(expressions={}))

    def test_neutral_required(self):
        with pytest.raises(ValueError, match="neutral"):
            DigitalHumanProfile.from_dict(_minimal(expressions={
                "happy": {"type": "morph", "name": "Angry"},
            }))

    def test_neutral_must_be_empty(self):
        with pytest.raises(ValueError, match="neutral"):
            DigitalHumanProfile.from_dict(_minimal(expressions={
                "neutral": {"type": "blendshapes", "params": {"jawOpen": 0.5}},
            }))


class TestHelpers:
    def test_missing_expressions(self):
        p = DigitalHumanProfile.from_dict(_minimal(expressions={
            "neutral": {},
            "happy": {"type": "morph", "name": "Angry"},
        }))
        assert p.missing_expressions(["happy", "sad", "surprised"]) == ["sad", "surprised"]

    def test_all_morph_names(self):
        p = DigitalHumanProfile.from_dict(_minimal(
            morphs={"mouth_open": "jawOpen", "blink_left": "eyeBlink_L"},
            expressions={
                "neutral": {},
                "happy": {"type": "blendshapes", "params": {"mouthSmile_L": 0.5}},
                "sad": {"type": "morph", "name": "Sad"},
            },
        ))
        assert p.all_morph_names() == {"jawOpen", "eyeBlink_L", "mouthSmile_L", "Sad"}

    def test_defaults(self):
        p = DigitalHumanProfile.from_dict(_minimal())
        assert p.lip_sync_gain == 5.0
        assert p.lip_sync_smoothing == 0.5
        assert p.idle.blink_interval == (2.5, 6.0)
        assert p.camera["fov"] == 30.0

    def test_pair_normalizes_order(self):
        p = DigitalHumanProfile.from_dict(_minimal(idle={"blink_interval": [9, 3]}))
        assert p.idle.blink_interval == (3.0, 9.0)

    def test_vec3_invalid_falls_back(self):
        p = DigitalHumanProfile.from_dict(_minimal(camera={"position": "nope"}))
        assert p.camera["position"] == [0.0, 1.55, 0.65]

    def test_reserved_fields_parsed(self):
        p = DigitalHumanProfile.from_dict(_minimal(persona_id="catgirl", voice_id="youxiang"))
        assert p.persona_id == "catgirl"
        assert p.voice_id == "youxiang"

    def test_extras_passthrough(self):
        p = DigitalHumanProfile.from_dict(_minimal(future_field={"a": 1}))
        assert p.extras == {"future_field": {"a": 1}}


class TestSerialization:
    def test_to_frontend_dict_has_discriminator(self):
        p = DigitalHumanProfile.from_dict(_minimal())
        d = p.to_frontend_dict()
        assert d["type"] == "digital_human"
        assert d["model_path"] == "avatar.glb"
        assert d["morphs"]["mouth_open"] is None
        assert d["lip_sync"] == {"gain": 5.0, "smoothing": 0.5}
        assert d["expressions"]["neutral"] == {"type": "blendshapes", "params": {}}
        assert isinstance(d["idle"]["blink_interval"], list)
        assert "persona_id" in d and "voice_id" in d

    def test_morph_expression_serialized(self):
        p = DigitalHumanProfile.from_dict(_minimal(expressions={
            "neutral": {},
            "happy": {"type": "morph", "name": "Angry"},
        }))
        assert p.to_frontend_dict()["expressions"]["happy"] == {
            "type": "morph", "name": "Angry",
        }
