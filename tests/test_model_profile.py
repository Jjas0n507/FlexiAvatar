"""ModelProfile 测试 — YAML 加载 + 数据类"""
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import tempfile

from backend.live2d.model_profile import (
    ModelProfile, ParameterIds, MouthShapeParams, ExpressionDef,
    MotionDef, IdleConfig,
)

# 完整的测试用 YAML 内容
VALID_PROFILE_YAML = """
model:
  name: "测试角色"
  model3_path: "test.model3.json"
  scale: 1.0

parameters:
  lip_sync:
    open_y: "ParamMouthOpenY"
    form: "ParamMouthForm"
  eyes:
    left_open: "ParamEyeLOpen"
    right_open: "ParamEyeROpen"
    left_smile: "ParamEyeLSmile"
    right_smile: "ParamEyeRSmile"
    eyeball_x: "ParamEyeBallX"
    eyeball_y: "ParamEyeBallY"
  brows:
    left_y: "ParamBrowLY"
    right_y: "ParamBrowRY"
    left_x: "ParamBrowLX"
    right_x: "ParamBrowRX"
  head:
    angle_z: "ParamHeadAngleZ"
  body:
    angle_x: "ParamBodyAngleX"
  extra: ["Paramemoji1", "Paramemoji2"]

mouth_shapes:
  A: { open_y: 0.8, form: 0.0 }
  I: { open_y: 0.3, form: 0.8 }
  U: { open_y: 0.3, form: -0.5 }
  E: { open_y: 0.5, form: 0.0 }
  O: { open_y: 0.6, form: -0.2 }
  N: { open_y: 0.0, form: 0.0 }

expressions:
  neutral:
    type: "native"
    name: null
  happy:
    type: "native"
    name: "害羞"
  surprised:
    type: "params"
    params:
      ParamEyeLOpen: 1.2
      ParamEyeROpen: 1.2
  thinking:
    type: "params"
    params:
      ParamBrowLX: -0.2
      ParamBrowRX: 0.2

motions:
  listening:
    - { group: "Idle", index: 0 }
    - { group: "Idle", index: 1 }
  processing:
    - { group: "Idle", index: 1 }
  idle:
    - { group: "Idle", index: 0 }
    - { group: "Idle", index: 1 }
    - { group: "Random", index: 0 }

idle:
  expression_cycle: ["neutral", "happy", "thinking"]
  expression_interval: [5.0, 12.0]
  blink_interval: [2.0, 6.0]
  eye_drift_range: 0.15
  head_tilt_chance: 0.15
  head_tilt_angle: 0.1
"""


class TestModelProfileLoad:
    def test_load_from_yaml_valid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = Path(tmpdir) / "model_profile.yaml"
            yaml_path.write_text(VALID_PROFILE_YAML, encoding="utf-8")
            profile = ModelProfile.load(tmpdir)
            assert profile.name == "测试角色"
            assert profile.model3_path == "test.model3.json"
            assert profile.scale == 1.0

    def test_load_from_yaml_missing_file(self):
        with pytest.raises(FileNotFoundError):
            ModelProfile.load("/nonexistent/path/12345")

    def test_load_from_yaml_missing_required_field(self):
        bad_yaml = """
model:
  name: "Test"
  model3_path: "x.model3.json"
  scale: 1.0
# missing parameters, mouth_shapes, expressions, motions, idle
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = Path(tmpdir) / "model_profile.yaml"
            yaml_path.write_text(bad_yaml, encoding="utf-8")
            with pytest.raises((KeyError, TypeError, AttributeError)):
                ModelProfile.load(tmpdir)

    def test_to_frontend_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = Path(tmpdir) / "model_profile.yaml"
            yaml_path.write_text(VALID_PROFILE_YAML, encoding="utf-8")
            profile = ModelProfile.load(tmpdir)
            d = profile.to_frontend_dict()
            assert d["name"] == "测试角色"
            assert d["model3_path"] == "test.model3.json"
            assert isinstance(d["parameters"], dict)
            assert isinstance(d["mouth_shapes"], dict)
            assert isinstance(d["expressions"], dict)
            assert isinstance(d["motions"], dict)
            assert isinstance(d["idle"], dict)

    def test_to_frontend_dict_is_json_serializable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = Path(tmpdir) / "model_profile.yaml"
            yaml_path.write_text(VALID_PROFILE_YAML, encoding="utf-8")
            profile = ModelProfile.load(tmpdir)
            json_str = json.dumps(profile.to_frontend_dict(), ensure_ascii=False)
            assert len(json_str) > 200

    def test_mouth_shape_lookup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = Path(tmpdir) / "model_profile.yaml"
            yaml_path.write_text(VALID_PROFILE_YAML, encoding="utf-8")
            profile = ModelProfile.load(tmpdir)
            shape = profile.mouth_shapes["A"]
            assert shape.open_y == 0.8
            assert shape.form == 0.0

    def test_expression_lookup_native(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = Path(tmpdir) / "model_profile.yaml"
            yaml_path.write_text(VALID_PROFILE_YAML, encoding="utf-8")
            profile = ModelProfile.load(tmpdir)
            expr = profile.expressions["happy"]
            assert expr.type == "native"
            assert expr.name == "害羞"

    def test_expression_lookup_params(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = Path(tmpdir) / "model_profile.yaml"
            yaml_path.write_text(VALID_PROFILE_YAML, encoding="utf-8")
            profile = ModelProfile.load(tmpdir)
            expr = profile.expressions["surprised"]
            assert expr.type == "params"
            assert expr.params["ParamEyeLOpen"] == 1.2
            assert expr.params["ParamEyeROpen"] == 1.2

    def test_motion_lookup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = Path(tmpdir) / "model_profile.yaml"
            yaml_path.write_text(VALID_PROFILE_YAML, encoding="utf-8")
            profile = ModelProfile.load(tmpdir)
            motions = profile.motions["idle"]
            assert len(motions) >= 3
            groups = {m.group for m in motions}
            assert "Random" in groups or "Idle" in groups

    def test_idle_config_bounds(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = Path(tmpdir) / "model_profile.yaml"
            yaml_path.write_text(VALID_PROFILE_YAML, encoding="utf-8")
            profile = ModelProfile.load(tmpdir)
            lo, hi = profile.idle.expression_interval
            assert lo > 0
            assert hi > lo
