"""
Live2D 模型抽象层 — ModelProfile。

通过 model_profile.yaml 描述模型支持哪些参数、表情、动作，
解耦代码和具体模型。每个模型目录下放置一份，前后端各自加载。

用法:
    from backend.live2d.model_profile import ModelProfile
    profile = ModelProfile.load("frontend/public/live2d/有马加奈")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


# ── 数据类 ──────────────────────────────────────


@dataclass
class ParameterIds:
    """模型实际参数 ID"""
    lip_open_y: str = "ParamMouthOpenY"
    lip_form: str = "ParamMouthForm"
    eye_left_open: str = "ParamEyeLOpen"
    eye_right_open: str = "ParamEyeROpen"
    eye_left_smile: str = "ParamEyeLSmile"
    eye_right_smile: str = "ParamEyeRSmile"
    eyeball_x: str = "ParamEyeBallX"
    eyeball_y: str = "ParamEyeBallY"
    brow_left_y: str = "ParamBrowLY"
    brow_right_y: str = "ParamBrowRY"
    brow_left_x: str = "ParamBrowLX"
    brow_right_x: str = "ParamBrowRX"
    head_angle_z: str = "ParamHeadAngleZ"
    body_angle_x: str = "ParamBodyAngleX"
    extra: list[str] = field(default_factory=list)


@dataclass
class MouthShapeParams:
    """口型参数值"""
    open_y: float
    form: float


@dataclass
class ExpressionDef:
    """表情定义"""
    type: str  # "native" | "params"
    name: str | None = None
    params: dict[str, float] | None = None


@dataclass
class MotionDef:
    """动作定义"""
    group: str
    index: int


@dataclass
class IdleConfig:
    """空闲行为配置"""
    expression_cycle: list[str]
    expression_interval: tuple[float, float]
    blink_interval: tuple[float, float]
    eye_drift_range: float
    head_tilt_chance: float
    head_tilt_angle: float


@dataclass
class ModelProfile:
    """Live2D 模型抽象描述 — 前后端共同遵守的契约"""
    name: str
    model3_path: str
    scale: float
    parameters: ParameterIds
    mouth_shapes: dict[str, MouthShapeParams]
    expressions: dict[str, ExpressionDef]
    motions: dict[str, list[MotionDef]]
    idle: IdleConfig

    @classmethod
    def load(cls, model_dir: str | Path) -> "ModelProfile":
        """从 model_profile.yaml 加载"""
        model_dir = Path(model_dir)
        yaml_path = model_dir / "model_profile.yaml"
        if not yaml_path.exists():
            raise FileNotFoundError(f"model_profile.yaml not found in {model_dir}")

        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if data is None:
            raise ValueError(f"Empty or invalid YAML: {yaml_path}")

        # 解析 model 节
        model = data["model"]
        name = model["name"]
        model3_path = model["model3_path"]
        scale = model.get("scale", 1.0)

        # 解析 parameters 节
        params_raw = data["parameters"]
        parameters = ParameterIds(
            lip_open_y=params_raw["lip_sync"]["open_y"],
            lip_form=params_raw["lip_sync"]["form"],
            eye_left_open=params_raw["eyes"]["left_open"],
            eye_right_open=params_raw["eyes"]["right_open"],
            eye_left_smile=params_raw["eyes"]["left_smile"],
            eye_right_smile=params_raw["eyes"]["right_smile"],
            eyeball_x=params_raw["eyes"]["eyeball_x"],
            eyeball_y=params_raw["eyes"]["eyeball_y"],
            brow_left_y=params_raw["brows"]["left_y"],
            brow_right_y=params_raw["brows"]["right_y"],
            brow_left_x=params_raw["brows"]["left_x"],
            brow_right_x=params_raw["brows"]["right_x"],
            head_angle_z=params_raw["head"]["angle_z"],
            body_angle_x=params_raw["body"]["angle_x"],
            extra=params_raw.get("extra", []),
        )

        # 解析 mouth_shapes 节
        mouth_shapes: dict[str, MouthShapeParams] = {}
        for mouth, shape_data in data["mouth_shapes"].items():
            mouth_shapes[mouth] = MouthShapeParams(
                open_y=shape_data["open_y"],
                form=shape_data["form"],
            )

        # 解析 expressions 节
        expressions: dict[str, ExpressionDef] = {}
        for expr_name, expr_data in data["expressions"].items():
            expr_type = expr_data["type"]
            expressions[expr_name] = ExpressionDef(
                type=expr_type,
                name=expr_data.get("name") if expr_type == "native" else None,
                params=expr_data.get("params") if expr_type == "params" else None,
            )

        # 解析 motions 节
        motions: dict[str, list[MotionDef]] = {}
        for motion_name, motion_list in data["motions"].items():
            motions[motion_name] = [
                MotionDef(group=m["group"], index=m["index"])
                for m in motion_list
            ]

        # 解析 idle 节
        idle_raw = data["idle"]
        idle = IdleConfig(
            expression_cycle=idle_raw["expression_cycle"],
            expression_interval=(
                idle_raw["expression_interval"][0],
                idle_raw["expression_interval"][1],
            ),
            blink_interval=(
                idle_raw["blink_interval"][0],
                idle_raw["blink_interval"][1],
            ),
            eye_drift_range=idle_raw["eye_drift_range"],
            head_tilt_chance=idle_raw["head_tilt_chance"],
            head_tilt_angle=idle_raw["head_tilt_angle"],
        )

        return cls(
            name=name,
            model3_path=model3_path,
            scale=scale,
            parameters=parameters,
            mouth_shapes=mouth_shapes,
            expressions=expressions,
            motions=motions,
            idle=idle,
        )

    def to_frontend_dict(self) -> dict:
        """序列化为前端可用的 JSON"""
        # 口型映射
        mouth_shapes_dict = {
            k: {"open_y": v.open_y, "form": v.form}
            for k, v in self.mouth_shapes.items()
        }

        # 表情映射
        expressions_dict = {}
        for k, v in self.expressions.items():
            expr = {"type": v.type}
            if v.type == "native":
                expr["name"] = v.name
            elif v.type == "params":
                expr["params"] = v.params
            expressions_dict[k] = expr

        # 动作映射
        motions_dict = {
            k: [{"group": m.group, "index": m.index} for m in v]
            for k, v in self.motions.items()
        }

        return {
            "name": self.name,
            "model3_path": self.model3_path,
            "scale": self.scale,
            "parameters": {
                "lip_sync": {
                    "open_y": self.parameters.lip_open_y,
                    "form": self.parameters.lip_form,
                },
                "eyes": {
                    "left_open": self.parameters.eye_left_open,
                    "right_open": self.parameters.eye_right_open,
                    "left_smile": self.parameters.eye_left_smile,
                    "right_smile": self.parameters.eye_right_smile,
                    "eyeball_x": self.parameters.eyeball_x,
                    "eyeball_y": self.parameters.eyeball_y,
                },
                "brows": {
                    "left_y": self.parameters.brow_left_y,
                    "right_y": self.parameters.brow_right_y,
                    "left_x": self.parameters.brow_left_x,
                    "right_x": self.parameters.brow_right_x,
                },
                "head": {
                    "angle_z": self.parameters.head_angle_z,
                },
                "body": {
                    "angle_x": self.parameters.body_angle_x,
                },
                "extra": self.parameters.extra,
            },
            "mouth_shapes": mouth_shapes_dict,
            "expressions": expressions_dict,
            "motions": motions_dict,
            "idle": {
                "expression_cycle": self.idle.expression_cycle,
                "expression_interval": list(self.idle.expression_interval),
                "blink_interval": list(self.idle.blink_interval),
                "eye_drift_range": self.idle.eye_drift_range,
                "head_tilt_chance": self.idle.head_tilt_chance,
                "head_tilt_angle": self.idle.head_tilt_angle,
            },
        }
