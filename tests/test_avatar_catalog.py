"""形象清单发现 + 运行期选择 测试

覆盖：
- 目录扫描（含嵌套、噪声目录过滤、分组容器）
- 坏条目必须出现在清单里并带 reason（不静默消失）
- public URL 计算（含中文目录编码）
- load_avatar 白名单与文件存在性校验
- handle_avatar_select：未知 id / 路径穿越 / 无效条目 / 加载失败回滚
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from backend.avatar import catalog as catalog_mod
from backend.config import config


# ── 夹具 ────────────────────────────────────────


@pytest.fixture
def public_root(tmp_path, monkeypatch):
    """把 public_root 指到临时目录，避免依赖真实素材"""
    root = tmp_path / "public"
    root.mkdir()
    monkeypatch.setattr(catalog_mod, "public_root", lambda: root)
    config.load()
    return root


def _write_dh(dh_dir: Path, rel: str, *, name="形象", model="model.glb",
              expressions=None, create_model=True, profile=True, raw_profile=None):
    """在「被扫描的数字人目录」下造一个形象。

    注意：目录布局与 URL 归属是两件事 —— 素材目录可以是 public 之外的位置，
    前端 URL 由 to_public_url 统一换算（这里只关心发现逻辑）。
    """
    d = (dh_dir / rel).resolve()
    d.mkdir(parents=True, exist_ok=True)
    if create_model:
        (d / model).write_bytes(b"glTF-ish")
    if raw_profile is not None:
        (d / "avatar_profile.yaml").write_text(raw_profile, encoding="utf-8")
    elif profile:
        data = {
            "name": name,
            "model_path": model,
            "expressions": expressions or {"neutral": {"type": "blendshapes", "params": {}}},
        }
        (d / "avatar_profile.yaml").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
    return d


def _write_live2d(l2d_dir: Path, rel: str, *, profile=True, model3="m.model3.json"):
    d = (l2d_dir / rel).resolve()
    d.mkdir(parents=True, exist_ok=True)
    if model3:
        (d / model3).write_bytes(b"{}")
    if profile:
        (d / "model_profile.yaml").write_text(
            "model:\n"
            "  name: 测试Live2D\n"
            f"  model3_path: {model3}\n"
            "  scale: 1.0\n"
            "parameters:\n"
            "  lip_sync: {open_y: ParamMouthOpenY, form: ParamMouthForm}\n"
            "  eyes: {left_open: A, right_open: B, left_smile: C, right_smile: D,"
            " eyeball_x: E, eyeball_y: F}\n"
            "  brows: {left_y: G, right_y: H, left_x: I, right_x: J}\n"
            "  head: {angle_z: K}\n"
            "  body: {angle_x: L}\n"
            "  extra: []\n"
            "mouth_shapes:\n"
            "  A: {open_y: 0.8, form: 0.0}\n"
            "expressions:\n"
            "  neutral: {type: native, name: null}\n"
            "motions:\n"
            "  idle: [{group: Idle, index: 0}]\n"
            "idle:\n"
            "  expression_cycle: [neutral]\n"
            "  expression_interval: [5, 10]\n"
            "  blink_interval: [2, 6]\n"
            "  eye_drift_range: 0.2\n"
            "  head_tilt_chance: 0.1\n"
            "  head_tilt_angle: 5\n",
            encoding="utf-8",
        )
    return d


@pytest.fixture
def catalog_dirs(public_root, monkeypatch):
    """素材目录物理上位于 public_root 内（自托管素材的真实布局）。

    这样 to_public_url 能算出 URL，load_avatar 的文件存在性校验也才有意义。
    """
    dh = public_root / "avatar"
    l2d = public_root / "live2d"
    dh.mkdir(parents=True, exist_ok=True)
    l2d.mkdir(parents=True, exist_ok=True)
    config.set("avatar.digital_human.dir", str(dh))
    config.set("avatar.live2d.dir", str(l2d))
    return public_root, dh, l2d


# ── URL 计算 ────────────────────────────────────


class TestPublicUrl:
    def test_relative_path_resolved_against_cwd(self, public_root, monkeypatch):
        # 生产代码只传绝对路径；相对路径按 cwd 解析（在 public 下才算数）
        monkeypatch.chdir(public_root.parent)
        url = catalog_mod.to_public_url("public/avatar/x/a.glb")
        assert url == "/avatar/x/a.glb"

    def test_absolute_path(self, public_root):
        url = catalog_mod.to_public_url(public_root / "avatar" / "x" / "a.glb")
        assert url == "/avatar/x/a.glb"

    def test_outside_public_returns_empty(self, public_root, tmp_path):
        assert catalog_mod.to_public_url(tmp_path / "elsewhere" / "a.glb") == ""

    def test_chinese_path_is_encoded(self, public_root):
        url = catalog_mod.to_public_url(public_root / "live2d" / "有马加奈" / "m.model3.json")
        assert url.startswith("/live2d/%E6%9C%89%E9%A9%AC%E5%8A%A0%E5%A5%88/")
        assert " " not in url

    def test_roundtrip_through_public_url_to_path(self, public_root):
        original = public_root / "live2d" / "有马加奈" / "m.model3.json"
        url = catalog_mod.to_public_url(original)
        assert catalog_mod.public_url_to_path(url) == original


# ── 发现 ────────────────────────────────────────


class TestDiscovery:
    def test_valid_digital_human_entry(self, catalog_dirs):
        _, dh, _ = catalog_dirs
        _write_dh(dh, "face", name="人脸头")
        entries = catalog_mod.discover_avatars()["digital_human"]
        assert len(entries) == 1
        e = entries[0]
        assert e.valid is True
        assert e.id == "digital_human/face"
        assert e.name == "人脸头"
        assert e.model_path == "/avatar/face/model.glb"
        assert e.profile_path == "/avatar/face/avatar_profile.yaml"

    def test_nested_layout_is_found(self, catalog_dirs):
        """_placeholder/facecap/ 这种两层布局必须被发现"""
        _, dh, _ = catalog_dirs
        _write_dh(dh, "_placeholder/facecap", name="占位")
        entries = catalog_mod.discover_avatars()["digital_human"]
        assert [e.id for e in entries] == ["digital_human/_placeholder/facecap"]
        assert entries[0].valid

    def test_grouping_container_is_skipped_silently(self, public_root, tmp_path):
        # 直接构造：分组容器下没有 glb，不该出现在清单
        avatars = tmp_path / "avatars"
        (avatars / "_placeholder").mkdir(parents=True)
        config.load()
        config.set("avatar.digital_human.dir", str(avatars))
        assert catalog_mod.discover_avatars()["digital_human"] == []

    def test_missing_profile_with_model_is_visible(self, catalog_dirs):
        """目录里有模型但缺 profile = 配置错误，必须出现在清单里"""
        _, dh, _ = catalog_dirs
        _write_dh(dh, "broken", profile=False)
        entries = catalog_mod.discover_avatars()["digital_human"]
        assert len(entries) == 1
        assert entries[0].valid is False
        assert "avatar_profile.yaml" in entries[0].reason

    def test_bad_yaml_is_visible_with_reason(self, catalog_dirs):
        _, dh, _ = catalog_dirs
        _write_dh(dh, "bad", raw_profile="name: [unclosed\n  :::")
        entries = catalog_mod.discover_avatars()["digital_human"]
        assert entries[0].valid is False
        assert entries[0].reason

    def test_profile_parse_error_is_visible(self, catalog_dirs):
        _, dh, _ = catalog_dirs
        # 缺 neutral → validate 抛错
        _write_dh(dh, "noneutral",
                  expressions={"happy": {"type": "morph", "name": "Angry"}})
        entries = catalog_mod.discover_avatars()["digital_human"]
        assert entries[0].valid is False
        assert "neutral" in entries[0].reason

    def test_live2d_entry(self, catalog_dirs):
        _, _, l2d = catalog_dirs
        _write_live2d(l2d, "cat")
        entries = catalog_mod.discover_avatars()["live2d"]
        assert len(entries) == 1
        e = entries[0]
        assert e.valid is True
        assert e.id == "live2d/cat"
        assert e.name == "测试Live2D"
        assert e.model_path == "/live2d/cat/m.model3.json"

    def test_live2d_texture_subdir_not_listed(self, catalog_dirs):
        """贴图目录（有马加奈.4096）不该进清单"""
        _, _, l2d = catalog_dirs
        model_dir = _write_live2d(l2d, "cat")
        (model_dir / "cat.4096").mkdir()
        (model_dir / "cat.4096" / "tex.png").write_bytes(b"x")
        entries = catalog_mod.discover_avatars()["live2d"]
        assert [e.id for e in entries] == ["live2d/cat"]

    def test_missing_dirs_yield_empty(self, tmp_path):
        config.load()
        config.set("avatar.digital_human.dir", str(tmp_path / "nope"))
        config.set("avatar.live2d.dir", str(tmp_path / "nope2"))
        catalog = catalog_mod.discover_avatars()
        assert catalog == {"live2d": [], "digital_human": []}

    def test_discovery_is_stable_sorted(self, catalog_dirs):
        _, dh, _ = catalog_dirs
        for name in ("zeta", "alpha", "mid"):
            _write_dh(dh, f"{name}", name=name)
        ids = [e.id for e in catalog_mod.discover_avatars()["digital_human"]]
        assert ids == sorted(ids)

    def test_reserved_fields_surface_in_entry(self, catalog_dirs):
        _, dh, _ = catalog_dirs
        d = _write_dh(dh, "role")
        (d / "avatar_profile.yaml").write_text(
            json.dumps({
                "name": "角色",
                "model_path": "model.glb",
                "persona_id": "catgirl",
                "voice_id": "youxiang",
                "expressions": {"neutral": {}},
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        e = catalog_mod.discover_avatars()["digital_human"][0]
        assert e.persona_id == "catgirl"
        assert e.voice_id == "youxiang"
        assert e.to_dict()["persona_id"] == "catgirl"


# ── 查找 / 加载 ─────────────────────────────────


class TestFindAndLoad:
    def test_find_entry_by_id(self, catalog_dirs):
        _, dh, _ = catalog_dirs
        _write_dh(dh, "face")
        assert catalog_mod.find_entry("digital_human/face") is not None
        assert catalog_mod.find_entry("digital_human/nope") is None

    def test_find_entry_rejects_path_traversal(self, catalog_dirs):
        """客户端传来的 id 一律走白名单，绝不参与路径拼接"""
        _, dh, _ = catalog_dirs
        _write_dh(dh, "face")
        for evil in ("../../etc/passwd", "/etc/passwd", "digital_human/../../x", ".."):
            assert catalog_mod.find_entry(evil) is None

    def test_load_avatar_digital_human(self, catalog_dirs):
        _, dh, _ = catalog_dirs
        _write_dh(dh, "face", name="人脸头")
        entry = catalog_mod.find_entry("digital_human/face")
        in_use = catalog_mod.load_avatar(entry)
        d = in_use.to_profile_dict()
        assert d["type"] == "digital_human"
        assert d["name"] == "人脸头"
        assert in_use.type == "digital_human"

    def test_load_avatar_live2d_gets_type(self, catalog_dirs):
        _, _, l2d = catalog_dirs
        _write_live2d(l2d, "cat")
        entry = catalog_mod.find_entry("live2d/cat")
        d = catalog_mod.load_avatar(entry).to_profile_dict()
        assert d["type"] == "live2d"
        assert d["name"] == "测试Live2D"

    def test_load_avatar_missing_model_raises(self, catalog_dirs):
        """profile 在但模型文件被删 → 切换时必须失败而不是黑屏"""
        _, dh, _ = catalog_dirs
        d = _write_dh(dh, "face")
        (d / "model.glb").unlink()
        entry = catalog_mod.find_entry("digital_human/face")
        with pytest.raises(FileNotFoundError):
            catalog_mod.load_avatar(entry)


# ── 夹具：模块引用 ──────────────────────────────


@pytest.fixture
def select_module():
    """形象选择逻辑住在 backend/avatar/select.py（不依赖 FastAPI/pydantic）"""
    from backend.avatar import select as select_mod
    return select_mod


# ── avatar.select 选择请求 ──────────────────────


class TestSelectRequest:
    """选择逻辑（校验 / 回滚 / 记录）住在 backend/avatar/select.py，
    不依赖 FastAPI/pydantic，因此可以被真实测试。"""

    def test_unknown_id_rejected(self, select_module, monkeypatch):
        monkeypatch.setattr(select_module, "find_entry", lambda _id: None)
        r = select_module.handle_select_request("nope")
        assert r.ok is False
        assert r.code == "AVATAR_NOT_FOUND"

    def test_invalid_entry_rejected(self, select_module, monkeypatch):
        from backend.avatar.catalog import AvatarEntry
        bad = AvatarEntry(id="digital_human/x", name="坏", type="digital_human",
                          model_path="", profile_path="", valid=False, reason="缺 profile")
        monkeypatch.setattr(select_module, "find_entry", lambda _id: bad)
        r = select_module.handle_select_request("digital_human/x")
        assert r.ok is False
        assert r.code == "AVATAR_LOAD_FAILED"
        assert "缺 profile" in r.message

    def test_load_failure_rolls_back(self, select_module, monkeypatch):
        """加载失败必须回滚到切换前的形象，不留半死不活状态"""
        from backend.avatar.catalog import AvatarEntry
        entry = AvatarEntry(id="digital_human/a", name="A", type="digital_human",
                            model_path="/avatar/a/a.glb", profile_path="/avatar/a/p.yaml")
        monkeypatch.setattr(select_module, "find_entry", lambda _id: entry)
        sentinel = object()
        monkeypatch.setitem(select_module.AVATAR_STATE, "current", sentinel)
        monkeypatch.setattr(select_module, "apply_avatar",
                            lambda _e: (_ for _ in ()).throw(RuntimeError("boom")))
        r = select_module.handle_select_request("digital_human/a")
        assert r.ok is False
        assert r.code == "AVATAR_LOAD_FAILED"
        assert "boom" in r.message
        assert select_module.current() is sentinel  # 已回滚

    def test_success_records_selection(self, select_module, monkeypatch):
        from backend.avatar.catalog import AvatarEntry
        entry = AvatarEntry(id="digital_human/a", name="A", type="digital_human",
                            model_path="/avatar/a/a.glb", profile_path="/avatar/a/p.yaml")
        monkeypatch.setattr(select_module, "find_entry", lambda _id: entry)
        monkeypatch.setattr(select_module, "apply_avatar", lambda _e: "IN_USE")
        monkeypatch.setattr(select_module, "avatar_profile_payload",
                            lambda: {"type": "digital_human", "name": "A"})

        r = select_module.handle_select_request("digital_human/a")
        assert r.ok is True
        assert r.payload == {"type": "digital_human", "name": "A"}
        assert config.get("avatar.selected") == "digital_human/a"
        assert config.get("avatar.type") == "digital_human"

    def test_missing_id_treated_as_unknown(self, select_module, monkeypatch):
        monkeypatch.setattr(select_module, "find_entry", lambda _id: None)
        r = select_module.handle_select_request("")
        assert r.ok is False
        assert r.code == "AVATAR_NOT_FOUND"


class TestApplyAvatar:
    def test_apply_avatar_switches_state_and_controller(self, select_module, catalog_dirs):
        """apply_avatar 必须同时换 profile 与 MotionController"""
        dh, _, _ = catalog_dirs[1], None, None
        _write_dh(dh, "face", name="人脸头")
        entry = catalog_mod.find_entry("digital_human/face")

        before = select_module.AVATAR_STATE.get("motion")
        in_use = select_module.apply_avatar(entry)

        assert in_use.entry is entry
        assert select_module.current() is in_use
        assert select_module.motion_controller() is not before
        # 数字人没有 Live2D 参数体系 → model_profile 必须清空
        assert select_module.model_profile() is None

    def test_apply_avatar_live2d_keeps_model_profile(self, select_module, catalog_dirs):
        _, _, l2d = catalog_dirs
        _write_live2d(l2d, "cat")
        entry = catalog_mod.find_entry("live2d/cat")
        select_module.apply_avatar(entry)
        assert select_module.model_profile() is not None

    def test_apply_avatar_warns_on_missing_emotions(self, select_module, caplog):
        """切换形象时耦合点①校验必须触发（persona 覆盖出形象没有的情绪）"""
        from backend.avatar.catalog import AvatarEntry
        from backend.avatar.avatar_profile import DigitalHumanProfile
        entry = AvatarEntry(id="digital_human/a", name="A", type="digital_human",
                            model_path="/avatar/a/a.glb", profile_path="/avatar/a/p.yaml")
        profile = DigitalHumanProfile.from_dict({
            "name": "只有 happy",
            "model_path": "a.glb",
            "expressions": {"neutral": {}, "happy": {"type": "morph", "name": "X"}},
        })
        with caplog.at_level("WARNING"):
            select_module.check_emotion_coverage(profile)
        assert "sad" in caplog.text


class TestEmotionCoverage:
    """耦合点①：persona 映射出的情绪在当前形象缺失时必须可见"""

    def test_missing_emotions_reported(self, select_module, caplog):
        from backend.avatar.avatar_profile import DigitalHumanProfile
        profile = DigitalHumanProfile.from_dict({
            "name": "只有两个情绪",
            "model_path": "a.glb",
            "expressions": {
                "neutral": {"type": "blendshapes", "params": {}},
                "happy": {"type": "morph", "name": "Angry"},
            },
        })
        with caplog.at_level("WARNING"):
            select_module.check_emotion_coverage(profile)
        assert "缺少这些情绪的实现" in caplog.text
        assert "surprised" in caplog.text

    def test_full_coverage_no_warning(self, select_module, caplog):
        from backend.avatar.avatar_profile import DigitalHumanProfile
        names = select_module.emotion_names()
        profile = DigitalHumanProfile.from_dict({
            "name": "全覆盖",
            "model_path": "a.glb",
            "expressions": {n: {"type": "blendshapes", "params": {}} for n in names},
        })
        with caplog.at_level("WARNING"):
            select_module.check_emotion_coverage(profile)
        assert "缺少这些情绪的实现" not in caplog.text

    def test_emotion_names_include_persona_map(self, select_module):
        config.load()
        config.set("persona.emotion_expression_map", {"happy": "smug"})
        assert "smug" in select_module.emotion_names()
        config.set("persona.emotion_expression_map", None)
