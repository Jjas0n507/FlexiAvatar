"""
形象选择逻辑 —— 不依赖 FastAPI / pydantic 的纯逻辑层。

放在这里的理由：backend/main.py 在模块级 import FastAPI 与工具系统（pydantic），
把「清单发现 / profile 应用 / 情绪映射校验」的纯逻辑挤在 main.py 里会导致
这些规则无法被单元测试覆盖（测试环境未必装齐后端依赖）。

main.py 只负责：持有 AVATAR_STATE、把 WebSocket 消息转成这里的函数调用。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from backend.avatar.avatar_profile import DigitalHumanProfile
from backend.avatar.catalog import (
    AvatarEntry,
    AvatarInUse,
    discover_avatars,
    find_entry,
    load_avatar,
)
from backend.config import config
from backend.live2d.model_profile import ModelProfile
from backend.live2d.motion_controller import MotionController

logger = logging.getLogger("avatar")


# ── 进程级形象状态 ──────────────────────────────
#
# 用 dict 而不是模块级 global 变量：main.py 与这里共享同一个对象，
# 赋值不需要 `global` 声明，也不会出现「两处各自持有副本」的隐患。

AVATAR_STATE: dict = {
    "current": None,      # AvatarInUse | None
    "model_profile": None,  # ModelProfile | None（Live2D 渲染器契约）
    "motion": None,       # MotionController | None
}

# main.py 加载后注入（用于运行期热替换已存在 pipeline 的控制器）。
# 注意：这里持有的是 main.client_pipelines **本体**（不是它的副本/包装），
# 否则运行期新建的 pipeline 不会出现在这里。
_pipelines_ref: dict = {}


def set_pipelines_ref(pipelines: dict) -> None:
    _pipelines_ref["pipelines"] = pipelines


def current() -> AvatarInUse | None:
    return AVATAR_STATE["current"]


def model_profile() -> ModelProfile | None:
    return AVATAR_STATE["model_profile"]


def motion_controller() -> MotionController:
    motion = AVATAR_STATE["motion"]
    if motion is None:
        motion = MotionController()
        AVATAR_STATE["motion"] = motion
    return motion


# ── 情绪覆盖校验（耦合点①）──────────────────────


def emotion_names() -> list[str]:
    """本运行态可能出现的所有情绪名（SER 映射 + 文本关键词 + persona 覆盖）。"""
    from backend.live2d.motion_controller import _EMOTION_KEYWORDS, _SPEECH_EMOTION_MAP

    names = set(_EMOTION_KEYWORDS) | set(_SPEECH_EMOTION_MAP.values())
    persona = config.get("persona") or {}
    names |= set((persona.get("emotion_expression_map") or {}).values())
    return sorted(names)


def check_emotion_coverage(profile, wanted: list[str] | None = None) -> list[str]:
    """persona/内置映射产出的情绪名，当前形象是否都有实现；返回缺失清单。

    缺失不致命（渲染器回退 neutral），但必须**可见** —— 这类「静默失效」
    最难查（如 persona 把 happy 映射成 smug，而新形象没有 smug）。
    """
    expressions = getattr(profile, "expressions", None)
    if not isinstance(expressions, dict):
        return []
    wanted = wanted if wanted is not None else emotion_names()
    missing = [n for n in wanted if n not in expressions]
    if missing:
        logger.warning(
            f"形象「{getattr(profile, 'name', '?')}」缺少这些情绪的实现，将回退 neutral: "
            f"{', '.join(missing)}"
        )
    return missing


def make_motion_controller(profile) -> MotionController:
    persona = config.get("persona") or {}
    return MotionController(
        # 数字人没有 Live2D 参数体系 → 不传 profile，走情绪/状态分支即可
        profile=profile if isinstance(profile, ModelProfile) else None,
        emotion_expression_map=persona.get("emotion_expression_map") or None,
    )


# ── 应用形象 ────────────────────────────────────


def apply_avatar(entry: AvatarEntry) -> AvatarInUse:
    """加载并应用一个形象：换 profile + 换 MotionController + 补校验。

    失败会抛异常，调用方负责回滚（绝不留下半死不活的状态）。
    """
    in_use = load_avatar(entry)
    profile = in_use.profile

    check_emotion_coverage(profile)

    AVATAR_STATE["model_profile"] = profile if isinstance(profile, ModelProfile) else None
    AVATAR_STATE["motion"] = make_motion_controller(profile)
    AVATAR_STATE["current"] = in_use

    # 已存在的 pipeline 也换掉控制器（本版选择发生在会话前，这里是防御性处理）
    for pipeline in (_pipelines_ref.get("pipelines") or {}).values():
        pipeline.set_motion_controller(AVATAR_STATE["motion"])

    logger.info(f"形象已应用: {entry.id} ({entry.type})「{entry.name}」")
    return in_use


def initial_avatar() -> AvatarInUse | None:
    """启动时选定初始形象：config.avatar.selected → 第一个可用条目。"""
    catalog = discover_avatars()
    flat = [*catalog["live2d"], *catalog["digital_human"]]
    wanted_type = config.get("avatar.type", "live2d")
    wanted_id = config.get("avatar.selected", "")

    candidates: list[AvatarEntry] = []
    if wanted_id:
        hit = next((e for e in flat if e.id == wanted_id), None)
        if hit:
            candidates.append(hit)
        else:
            logger.warning(f"avatar.selected={wanted_id!r} 不在清单中，改用默认")
    candidates += [e for e in flat if e.valid and e.type == wanted_type]
    candidates += [e for e in flat if e.valid]

    for entry in candidates:
        try:
            return apply_avatar(entry)
        except Exception as e:  # noqa: BLE001 — 逐个降级尝试，别让启动失败
            logger.error(f"形象 {entry.id} 加载失败: {e}")
    return None


def avatar_profile_payload() -> dict | None:
    """当前形象的 profile payload（带 type 判别字段）。"""
    in_use = current()
    return in_use.to_profile_dict() if in_use else None


def live2d_profile_payload() -> dict | None:
    """旧契约（前端 modelProfile），仅在当前是 Live2D 形象时有值。"""
    profile = model_profile()
    return profile.to_frontend_dict() if profile else None


# ── 选择请求（WebSocket 处理器的纯逻辑部分）──────


@dataclass
class SelectResult:
    """一次 avatar.select 的结果 —— 由 main.py 翻译成 WS 消息。

    把这段逻辑放在这里（而不是 main.py 里）是为了让它可被单元测试覆盖：
    main.py 在模块级 import FastAPI 与工具系统（pydantic），测试环境未必装齐。
    """
    ok: bool
    entry: AvatarEntry | None = None
    payload: dict | None = None      # 成功时：新形象的 profile payload
    code: str = ""                   # 失败时：AVATAR_NOT_FOUND / AVATAR_LOAD_FAILED
    message: str = ""


def handle_select_request(avatar_id: str) -> SelectResult:
    """校验 → 加载 → 应用（失败回滚）。不抛异常，结果由调用方转成消息。"""
    entry = find_entry(avatar_id)
    if entry is None:
        return SelectResult(
            ok=False, code="AVATAR_NOT_FOUND", message=f"未知形象: {avatar_id}"
        )

    if not entry.valid:
        return SelectResult(
            ok=False,
            entry=entry,
            code="AVATAR_LOAD_FAILED",
            message=f"形象不可用: {entry.name}（{entry.reason}）",
        )

    previous = current()
    try:
        apply_avatar(entry)
    except Exception as e:  # noqa: BLE001 — 失败必须回滚，不能留下半死不活状态
        logger.error(f"切换形象失败 {avatar_id}: {e}", exc_info=True)
        AVATAR_STATE["current"] = previous
        return SelectResult(
            ok=False,
            entry=entry,
            code="AVATAR_LOAD_FAILED",
            message=f"形象加载失败: {e}",
        )

    # 记录选中（进程内，不落盘）
    config.set("avatar.selected", entry.id)
    config.set("avatar.type", entry.type)

    return SelectResult(ok=True, entry=entry, payload=avatar_profile_payload())
