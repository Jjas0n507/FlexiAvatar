"""
形象清单发现 + 运行期选中态。

- 扫描两个素材目录（Live2D 与数字人），产出前端可直接用的清单条目。
- profile 解析失败/文件缺失的条目**保留在清单里**并标 valid=False + reason：
  静默消失会让用户以为模型丢了。
- 客户端只传 id；路径一律由后端从磁盘重新计算（防路径穿越）。

用法:
    from backend.avatar.catalog import discover_avatars, AvatarInUse
    entries = discover_avatars()
    print(entries["digital_human"][0].id)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote

from backend.avatar.avatar_profile import DigitalHumanProfile
from backend.live2d.model_profile import ModelProfile

logger = logging.getLogger("avatar")

PUBLIC_ROOT_SUFFIX = ("frontend", "public")


# ── 清单条目 ────────────────────────────────────


@dataclass
class AvatarEntry:
    """前端可见的形象条目"""
    id: str
    name: str
    type: str                    # "live2d" | "digital_human"
    model_path: str              # public 相对 URL，前端可直接 fetch
    profile_path: str            # public 相对 URL
    valid: bool = True
    reason: str = ""
    # 预留关联字段（本版只解析/透传/显示，不消费 —— 将来"选角色"用）
    persona_id: str = ""
    voice_id: str = ""
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "model_path": self.model_path,
            "profile_path": self.profile_path,
            "valid": self.valid,
            "reason": self.reason,
            "persona_id": self.persona_id,
            "voice_id": self.voice_id,
        }


# ── 运行期选中态 ────────────────────────────────


@dataclass
class AvatarInUse:
    """当前选中并已加载的形象（进程内状态）"""
    entry: AvatarEntry
    profile: ModelProfile | DigitalHumanProfile

    @property
    def type(self) -> str:
        return self.entry.type

    def to_profile_dict(self) -> dict:
        """前端渲染器直接消费的 profile payload（带 type 判别字段）"""
        if isinstance(self.profile, DigitalHumanProfile):
            # entry.model_path 是 catalog 解析好的 public URL；模型本体在磁盘上的
            # 存在性已在 load_avatar 里校验过。
            return self.profile.to_frontend_dict(model_url=self.entry.model_path)
        data = self.profile.to_frontend_dict()
        data["type"] = "live2d"
        return data


# ── 路径与 URL ──────────────────────────────────


def public_root() -> Path:
    """仓库内 frontend/public 的绝对路径。"""
    return Path(__file__).resolve().parents[2] / "frontend" / "public"


def public_url_to_path(url: str) -> Path:
    """public 相对 URL → 磁盘路径（id 白名单之外的路径永不走到这里）"""
    rel = unquote(url.lstrip("/"))
    return public_root().joinpath(*[p for p in rel.split("/") if p])


def to_public_url(path: str | Path) -> str:
    """绝对/相对路径 → public 相对 URL（形如 /avatar/x/avatar_profile.yaml）。

    不在 public 下时返回 ""（调用方据此判为无效条目）。
    注意：不能对未 resolve 的相对路径做 relative_to —— 会得到
    "/frontend/public" 这种看似合法实则错误的 URL。
    """
    root = public_root().resolve()
    p = Path(path)
    abs_path = p if p.is_absolute() else (Path.cwd() / p)
    try:
        rel = abs_path.resolve().relative_to(root)
    except (ValueError, OSError):
        return ""
    return "/" + "/".join(quote(part) for part in rel.parts)


def _name_from_profile(profile_path: Path, fallback: str) -> tuple[str, str, str, dict]:
    """读取 profile 拿展示名与预留关联字段；失败返回 (fallback, "", "", {})。"""
    try:
        import yaml
        with open(profile_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            return fallback, "", "", {}
        if "model" in data and isinstance(data["model"], dict):
            name = data["model"].get("name") or fallback
        else:
            name = data.get("name") or fallback
        return (
            str(name),
            str(data.get("persona_id") or ""),
            str(data.get("voice_id") or ""),
            {},
        )
    except Exception:  # noqa: BLE001 — 展示名读取失败不该影响清单
        return fallback, "", "", {}


# ── 发现 ────────────────────────────────────────

MAX_SCAN_DEPTH = 2   # 允许 <dir>/<模型>/… ；再深容易把贴图/附件目录误当形象


def _profile_dirs(root: Path) -> list[Path]:
    """列出 root 下（含最多 MAX_SCAN_DEPTH-1 层嵌套）需要考察的目录，稳定排序。"""
    found: list[Path] = []
    if not root.is_dir():
        return found
    for sub in sorted(p for p in root.iterdir() if p.is_dir()):
        found.append(sub)
        if MAX_SCAN_DEPTH > 1:
            for deeper in sorted(p for p in sub.iterdir() if p.is_dir()):
                found.append(deeper)
    return found


def _is_nested(root: Path, sub: Path) -> bool:
    return sub.parent != root


def _discover_live2d(model_dir: Path) -> list[AvatarEntry]:
    entries: list[AvatarEntry] = []
    if not model_dir.is_dir():
        logger.warning(f"Live2D 素材目录不存在: {model_dir}")
        return entries

    for sub in _profile_dirs(model_dir):
        profile_file = sub / "model_profile.yaml"
        rel_id = "live2d/" + sub.relative_to(model_dir).as_posix()
        if not profile_file.exists():
            # 顶层缺 profile = 配置遗漏，必须可见；
            # 嵌套目录缺 profile 通常是贴图/附件目录（实测 有马加奈.4096），静默跳过。
            if not _is_nested(model_dir, sub):
                entries.append(AvatarEntry(
                    id=rel_id, name=sub.name, type="live2d",
                    model_path="", profile_path="",
                    valid=False, reason="缺少 model_profile.yaml",
                ))
            continue
        try:
            profile = ModelProfile.load(sub)
            entries.append(AvatarEntry(
                id=rel_id,
                name=profile.name,
                type="live2d",
                model_path=to_public_url(sub / profile.model3_path),
                profile_path=to_public_url(profile_file),
            ))
        except Exception as e:  # noqa: BLE001 — 坏条目要出现在清单里而不是消失
            logger.warning(f"Live2D 形象 {rel_id} 解析失败: {e}")
            entries.append(AvatarEntry(
                id=rel_id, name=sub.name, type="live2d",
                model_path="", profile_path=to_public_url(profile_file),
                valid=False, reason=f"profile 解析失败: {e}",
            ))
    return entries


def _discover_digital_human(avatar_dir: Path) -> list[AvatarEntry]:
    entries: list[AvatarEntry] = []
    if not avatar_dir.is_dir():
        # 素材未就位是预期状态，不算错误
        logger.info(f"数字人素材目录不存在（跳过）: {avatar_dir}")
        return entries

    for sub in _profile_dirs(avatar_dir):
        profile_file = sub / "avatar_profile.yaml"
        rel_id = "digital_human/" + sub.relative_to(avatar_dir).as_posix()
        if not profile_file.exists():
            # 顶层目录可能只是分组容器（如 _placeholder/），静默跳过；
            # 但已含模型文件的目录缺 profile 是配置错误，必须可见。
            if any(sub.glob("*.glb")) or any(sub.glob("*.gltf")):
                entries.append(AvatarEntry(
                    id=rel_id, name=sub.name, type="digital_human",
                    model_path="", profile_path="",
                    valid=False, reason="缺少 avatar_profile.yaml",
                ))
            continue
        try:
            profile = DigitalHumanProfile.load(profile_file)
            entries.append(AvatarEntry(
                id=rel_id,
                name=profile.name,
                type="digital_human",
                model_path=to_public_url(sub / profile.model_path),
                profile_path=to_public_url(profile_file),
                persona_id=profile.persona_id,
                voice_id=profile.voice_id,
            ))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"数字人形象 {rel_id} 解析失败: {e}")
            entries.append(AvatarEntry(
                id=rel_id, name=sub.name, type="digital_human",
                model_path="", profile_path=to_public_url(profile_file),
                valid=False, reason=f"profile 解析失败: {e}",
            ))
    return entries


def discover_avatars() -> dict[str, list[AvatarEntry]]:
    """扫描素材目录，返回 {"live2d": [...], "digital_human": [...]}"""
    from backend.config import config

    live2d_dir = config.get("avatar.live2d.dir") or config.get("live2d.model_dir") or ""
    dh_dir = config.get("avatar.digital_human.dir") or "frontend/public/avatar"

    return {
        "live2d": _discover_live2d(Path(live2d_dir)) if live2d_dir else [],
        "digital_human": _discover_digital_human(Path(dh_dir)),
    }


def all_entries() -> list[AvatarEntry]:
    catalog = discover_avatars()
    return [*catalog["live2d"], *catalog["digital_human"]]


def find_entry(avatar_id: str) -> AvatarEntry | None:
    """按 id 查找条目（白名单校验的唯一入口）"""
    for entry in all_entries():
        if entry.id == avatar_id:
            return entry
    return None


# ── 加载 ────────────────────────────────────────


def load_avatar(entry: AvatarEntry) -> AvatarInUse:
    """按条目加载 profile（entry 必须来自 discover_avatars）。"""
    profile_file = public_url_to_path(entry.profile_path)

    if entry.type == "digital_human":
        profile = DigitalHumanProfile.load(profile_file)
        _verify_model_exists(entry)
        return AvatarInUse(entry=entry, profile=profile)

    # Live2D：从 profile 所在目录加载
    profile = ModelProfile.load(profile_file.parent)
    return AvatarInUse(entry=entry, profile=profile)


def _verify_model_exists(entry: AvatarEntry) -> None:
    """数字人模型文件必须真实存在，否则切过去就是黑屏。"""
    if not entry.model_path:
        raise FileNotFoundError("模型路径为空")
    model_file = public_url_to_path(entry.model_path)
    if not model_file.is_file():
        raise FileNotFoundError(f"模型文件不存在: {entry.model_path}")
