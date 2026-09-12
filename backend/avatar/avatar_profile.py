"""
数字人形象抽象层 — DigitalHumanProfile。

通过 avatar_profile.yaml 描述一个 GLB/GLTF 数字人模型：
口型驱动哪个 morph、情绪怎么映射、空闲行为参数、相机取景。

设计约束（来自公开素材实测，doc: digital-human-avatar-plan.md §0.4）：
- morph 命名不统一（facecap 用 `browDown_L`，RPM/ARKit 用 `browDownLeft`），
  所以**一律逐项显式映射，代码不做任何命名猜测/硬编码**。
- 存在「只有整脸表情 morph、没有逐 blendshape」的模型（如 RobotExpressive），
  所以 expressions 同时支持：
    {type: "blendshapes", params: {morph: weight, ...}}
    {type: "morph", name: "Angry"}
- 存在没有嘴部 morph 的模型，所以 mouth_open 支持：
    {kind: "morph", name: "jawOpen"}                     # 驱动单个 morph 权重
    {kind: "add", name: "Angry", amount: 0.35}           # 发声时整体加偏置（代理）

用法:
    from backend.avatar.avatar_profile import DigitalHumanProfile
    profile = DigitalHumanProfile.load(Path("frontend/public/avatar/_placeholder/facecap/avatar_profile.yaml"))
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_BLINK_INTERVAL = (2.5, 6.0)
DEFAULT_EXPRESSION_INTERVAL = (6.0, 14.0)
DEFAULT_LIP_SYNC_GAIN = 5.0
DEFAULT_LIP_SYNC_SMOOTHING = 0.5
DEFAULT_LOOK_AT_RANGE = 0.8
DEFAULT_CAMERA = {
    "position": [0.0, 1.55, 0.65],
    "target": [0.0, 1.5, 0.0],
    "fov": 30.0,
}


# ── 数据类 ──────────────────────────────────────


@dataclass
class ExpressionDef:
    """一个情绪的实现方式（两类模型通吃）"""
    type: str                                    # "blendshapes" | "morph"
    params: dict[str, float] = field(default_factory=dict)
    name: str | None = None

    @property
    def morph_names(self) -> list[str]:
        if self.type == "morph":
            return [self.name] if self.name else []
        return list(self.params.keys())

    def to_frontend_dict(self) -> dict:
        if self.type == "morph":
            return {"type": "morph", "name": self.name}
        return {"type": "blendshapes", "params": dict(self.params)}


@dataclass
class MouthOpenDef:
    """口型驱动方式"""
    kind: str                                    # "morph" | "add"
    name: str = ""
    amount: float = 0.35                         # 仅 kind == "add"

    @property
    def morph_names(self) -> list[str]:
        return [self.name] if self.name else []

    def to_frontend_dict(self) -> dict:
        if self.kind == "add":
            return {"kind": "add", "name": self.name, "amount": self.amount}
        return {"kind": "morph", "name": self.name}


@dataclass
class IdleConfig:
    blink_interval: tuple[float, float] = DEFAULT_BLINK_INTERVAL
    expression_cycle: list[str] = field(default_factory=list)
    expression_interval: tuple[float, float] = DEFAULT_EXPRESSION_INTERVAL
    look_at_range: float = DEFAULT_LOOK_AT_RANGE


@dataclass
class DigitalHumanProfile:
    """数字人模型抽象描述 — 前后端共同遵守的契约"""
    name: str
    model_path: str
    mouth_open: MouthOpenDef | None
    blink_left: str = ""
    blink_right: str = ""
    lip_sync_gain: float = DEFAULT_LIP_SYNC_GAIN
    lip_sync_smoothing: float = DEFAULT_LIP_SYNC_SMOOTHING
    expressions: dict[str, ExpressionDef] = field(default_factory=dict)
    idle: IdleConfig = field(default_factory=IdleConfig)
    camera: dict = field(default_factory=lambda: dict(DEFAULT_CAMERA))
    persona_id: str = ""
    voice_id: str = ""
    extras: dict = field(default_factory=dict)
    source_path: str = ""

    # ── 加载 ────────────────────────────────────

    @classmethod
    def load(cls, yaml_path: str | Path) -> "DigitalHumanProfile":
        """从 avatar_profile.yaml 加载"""
        yaml_path = Path(yaml_path)
        if not yaml_path.exists():
            raise FileNotFoundError(f"avatar_profile.yaml not found: {yaml_path}")

        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict) or not data:
            raise ValueError(f"Empty or invalid YAML: {yaml_path}")

        return cls.from_dict(data, source_path=str(yaml_path))

    @classmethod
    def from_dict(cls, data: dict, source_path: str = "") -> "DigitalHumanProfile":
        name = data.get("name") or ""
        if not name:
            raise ValueError("avatar_profile.yaml 缺少 name")
        model_path = data.get("model_path") or ""
        if not model_path:
            raise ValueError("avatar_profile.yaml 缺少 model_path")

        # morphs 节
        morphs = data.get("morphs") or {}
        mouth_open = _parse_mouth_open(morphs.get("mouth_open"))
        blink_left = str(morphs.get("blink_left") or "")
        blink_right = str(morphs.get("blink_right") or "")

        # lip_sync 节
        lip_raw = data.get("lip_sync") or {}
        gain = float(lip_raw.get("gain", DEFAULT_LIP_SYNC_GAIN))
        smoothing = float(lip_raw.get("smoothing", DEFAULT_LIP_SYNC_SMOOTHING))

        # expressions 节
        expressions: dict[str, ExpressionDef] = {}
        for expr_name, expr_data in (data.get("expressions") or {}).items():
            expressions[expr_name] = _parse_expression(expr_name, expr_data)

        # idle 节
        idle_raw = data.get("idle") or {}
        idle = IdleConfig(
            blink_interval=_pair(idle_raw.get("blink_interval"), DEFAULT_BLINK_INTERVAL),
            expression_cycle=list(idle_raw.get("expression_cycle") or []),
            expression_interval=_pair(
                idle_raw.get("expression_interval"), DEFAULT_EXPRESSION_INTERVAL
            ),
            look_at_range=float(idle_raw.get("look_at_range", DEFAULT_LOOK_AT_RANGE)),
        )

        # camera 节
        cam_raw = data.get("camera") or {}
        camera = {
            "position": _vec3(cam_raw.get("position"), DEFAULT_CAMERA["position"]),
            "target": _vec3(cam_raw.get("target"), DEFAULT_CAMERA["target"]),
            "fov": float(cam_raw.get("fov", DEFAULT_CAMERA["fov"])),
        }

        known = {
            "name", "model_path", "morphs", "lip_sync", "expressions",
            "idle", "camera", "persona_id", "voice_id",
        }
        extras = {k: v for k, v in data.items() if k not in known}

        profile = cls(
            name=name,
            model_path=model_path,
            mouth_open=mouth_open,
            blink_left=blink_left,
            blink_right=blink_right,
            lip_sync_gain=gain,
            lip_sync_smoothing=smoothing,
            expressions=expressions,
            idle=idle,
            camera=camera,
            persona_id=str(data.get("persona_id") or ""),
            voice_id=str(data.get("voice_id") or ""),
            extras=extras,
            source_path=source_path,
        )
        profile.validate()
        return profile

    # ── 校验 ────────────────────────────────────

    def missing_expressions(self, wanted: list[str]) -> list[str]:
        """给定情绪名清单，返回本 profile 缺失的那些（供耦合点①校验用）"""
        return [name for name in wanted if name not in self.expressions]

    def all_morph_names(self) -> set[str]:
        """profile 引用到的所有 morph 名（供渲染器/探针比对用）"""
        names: set[str] = set()
        if self.mouth_open:
            names.update(self.mouth_open.morph_names)
        for n in (self.blink_left, self.blink_right):
            if n:
                names.add(n)
        for expr in self.expressions.values():
            names.update(expr.morph_names)
        return names

    def validate(self) -> None:
        """结构性校验：错误直接抛（配置文件写错应当尽早暴露）"""
        if not self.expressions:
            raise ValueError(f"[{self.name}] expressions 为空：至少要有一个情绪（含 neutral）")
        if "neutral" not in self.expressions:
            raise ValueError(f"[{self.name}] expressions 缺少 neutral（打断/复位需要它归零）")
        neutral = self.expressions["neutral"]
        if neutral.type == "blendshapes" and neutral.params:
            raise ValueError(f"[{self.name}] neutral 必须是空实现（params 为空或 type:morph 也不行）")
        for expr_name, expr in self.expressions.items():
            if expr.type == "morph" and not expr.name:
                raise ValueError(f"[{self.name}] 情绪 {expr_name} 是 type:morph 但缺少 name")
        if self.mouth_open and self.mouth_open.kind == "morph" and not self.mouth_open.name:
            raise ValueError(f"[{self.name}] morphs.mouth_open 是 morph 类型但缺少 name")

    # ── 序列化 ──────────────────────────────────

    def to_frontend_dict(self, model_url: str | None = None) -> dict:
        """序列化为前端可用的 JSON（带 type 判别字段）。

        model_url: 由 catalog 解析出的 public URL。**前端拿到的必须是可直接
        fetch 的地址**（profile 里的 model_path 是相对模型目录的裸文件名，
        前端无法自行拼对 —— 实测曾因此把 GLB 请求成 SPA 的 index.html）。
        """
        return {
            "type": "digital_human",
            "name": self.name,
            "model_path": model_url or self.model_path,
            "camera": self.camera,
            "morphs": {
                "mouth_open": self.mouth_open.to_frontend_dict() if self.mouth_open else None,
                "blink_left": self.blink_left,
                "blink_right": self.blink_right,
            },
            "lip_sync": {
                "gain": self.lip_sync_gain,
                "smoothing": self.lip_sync_smoothing,
            },
            "expressions": {
                k: v.to_frontend_dict() for k, v in self.expressions.items()
            },
            "idle": {
                "blink_interval": list(self.idle.blink_interval),
                "expression_cycle": list(self.idle.expression_cycle)
                or ["neutral", "happy", "thinking", "surprised"],
                "expression_interval": list(self.idle.expression_interval),
                "look_at_range": self.idle.look_at_range,
            },
            "persona_id": self.persona_id,
            "voice_id": self.voice_id,
        }


# ── 解析辅助 ────────────────────────────────────


def _parse_expression(expr_name: str, expr_data) -> ExpressionDef:
    """解析一个情绪定义。

    兼容两种写法：
      {type: "blendshapes", params: {...}}          # 显式
      {type: "morph", name: "Angry"}                # 显式
      {} / null                                     # neutral 简写
      {mouthSmile_L: 0.6, ...}                      # 裸权重表简写（等价 blendshapes）
    """
    if expr_data is None:
        return ExpressionDef(type="blendshapes", params={})
    if not isinstance(expr_data, dict):
        raise ValueError(f"情绪 {expr_name} 定义非法（应为 mapping，得到 {type(expr_data).__name__}）")

    expr_type = expr_data.get("type")
    if expr_type is None:
        # 裸权重表简写：{morphName: weight}
        params = {}
        for k, v in expr_data.items():
            try:
                params[str(k)] = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"情绪 {expr_name} 的权重 {k}={v!r} 不是数字")
        return ExpressionDef(type="blendshapes", params=params)

    if expr_type == "morph":
        return ExpressionDef(type="morph", name=expr_data.get("name"))

    if expr_type == "blendshapes":
        raw = expr_data.get("params") or {}
        if not isinstance(raw, dict):
            raise ValueError(f"情绪 {expr_name} 的 params 应为 mapping")
        return ExpressionDef(
            type="blendshapes",
            params={str(k): float(v) for k, v in raw.items()},
        )

    raise ValueError(f"情绪 {expr_name} 的 type 非法: {expr_type!r}（应为 blendshapes | morph）")


def _parse_mouth_open(raw) -> MouthOpenDef | None:
    """解析 morphs.mouth_open。

    兼容：字符串（morph 名）/ {add: name, amount: x} / {name: ..., amount: ...} / null
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, str):
        return MouthOpenDef(kind="morph", name=raw)
    if isinstance(raw, dict):
        if "add" in raw:
            return MouthOpenDef(
                kind="add",
                name=str(raw["add"]),
                amount=float(raw.get("amount", 0.35)),
            )
        return MouthOpenDef(
            kind="morph",
            name=str(raw.get("name") or ""),
        )
    raise ValueError(f"morphs.mouth_open 定义非法: {raw!r}")


def _pair(raw, default: tuple[float, float]) -> tuple[float, float]:
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        return default
    try:
        lo, hi = float(raw[0]), float(raw[1])
    except (TypeError, ValueError):
        return default
    if hi < lo:
        lo, hi = hi, lo
    return (lo, hi)


def _vec3(raw, default) -> list[float]:
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        return list(default)
    try:
        return [float(raw[0]), float(raw[1]), float(raw[2])]
    except (TypeError, ValueError):
        return list(default)
