"""Persona 配置测试 — system prompt 组装 + emotion map 覆盖"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import config
from backend.llm.persona import build_system_prompt
from backend.live2d.motion_controller import (
    MotionController, detect_emotion, _SPEECH_EMOTION_MAP,
)

# 加载配置（测试中的 build_system_prompt fallback 需要读 llm.system_prompt）
_config_loaded = False
if not _config_loaded:
    config.load()
    _config_loaded = True


# ── build_system_prompt ──────────────────────


class TestBuildSystemPrompt:
    def test_none_returns_fallback(self):
        """persona 为 None → 返回 llm.system_prompt 兜底"""
        result = build_system_prompt(None)
        assert "桌面 AI 助手" in result
        assert "<Identity>" not in result

    def test_empty_dict_returns_fallback(self):
        """persona 为空 dict → 返回兜底"""
        result = build_system_prompt({})
        assert "桌面 AI 助手" in result

    def test_no_name_returns_fallback(self):
        """persona 有 identity 但 name 为空 → 返回兜底"""
        result = build_system_prompt({"name": "", "identity": "test"})
        assert "桌面 AI 助手" in result

    def test_minimal_persona(self):
        """最小配置（name + identity）→ 含 <Identity> + <ASRNote>，不含 <Background> / <Examples>"""
        result = build_system_prompt({
            "name": "测试",
            "identity": "测试身份",
            "personality": "",
            "speaking_style": "简洁",
            "language": "中文",
        })
        assert "<Identity>测试身份</Identity>" in result
        assert "<ASRNote>" in result
        assert "同音错字" in result
        assert "<Background>" not in result
        assert "<Examples>" not in result

    def test_full_persona(self):
        """完整配置 → 所有 XML 块输出"""
        result = build_system_prompt({
            "name": "傲娇助手",
            "identity": "傲娇高中生",
            "personality": "嘴硬心软",
            "speaking_style": "带点傲娇语气",
            "language": "中文",
            "background": "二年级，成绩优秀",
            "few_shot_examples": [
                {"user": "你好", "assistant": "哼，我才不是特意来见你的"},
            ],
        })
        assert "<Identity>傲娇高中生</Identity>" in result
        assert "<Personality>嘴硬心软</Personality>" in result
        assert "<SpeakingStyle>" in result
        assert "<Language>中文</Language>" in result
        assert "<Background>二年级，成绩优秀</Background>" in result
        assert "<Examples>" in result
        assert "哼，我才不是特意来见你的" in result
        assert "<ASRNote>" in result

    def test_speaking_style_includes_tts_warning(self):
        """SpeakingStyle 块自动包含 TTS 约束"""
        result = build_system_prompt({
            "name": "测试",
            "identity": "test",
            "speaking_style": "简洁",
        })
        assert "TTS 朗读" in result
        assert "Markdown" in result

    def test_no_background_when_empty(self):
        result = build_system_prompt({
            "name": "测试",
            "identity": "test",
            "speaking_style": "简洁",
            "background": "",
        })
        assert "<Background>" not in result

    def test_no_examples_when_empty(self):
        result = build_system_prompt({
            "name": "测试",
            "identity": "test",
            "speaking_style": "简洁",
            "few_shot_examples": [],
        })
        assert "<Examples>" not in result


# ── emotion_expression_map override ──────────


class TestEmotionMapOverride:
    def test_default_map_unchanged(self):
        """不传 emotion_expression_map → 行为不变"""
        ctrl = MotionController()
        expr = ctrl.get_expression_for_text("哈哈", speech_emotion="happy")
        assert expr.name == "happy"

    def test_override_happy_to_smug(self):
        """persona 覆盖 happy→smug"""
        ctrl = MotionController(emotion_expression_map={"happy": "smug"})
        expr = ctrl.get_expression_for_text("哈哈", speech_emotion="happy")
        assert expr.name == "smug"

    def test_override_sad_to_cry(self):
        """覆盖 sad→cry，未覆盖的仍用默认"""
        ctrl = MotionController(emotion_expression_map={"sad": "cry"})
        # happy 走默认
        expr_happy = ctrl.get_expression_for_text("哈哈", speech_emotion="happy")
        assert expr_happy.name == "happy"
        # sad 被覆盖
        expr_sad = ctrl.get_expression_for_text("难过", speech_emotion="sad")
        assert expr_sad.name == "cry"

    def test_detect_emotion_with_override_map(self):
        """detect_emotion 接受 emotion_map 参数"""
        override = {"happy": "smug", **{k: v for k, v in _SPEECH_EMOTION_MAP.items() if k != "happy"}}
        assert detect_emotion("哈哈", speech_emotion="happy", emotion_map=override) == "smug"
        # 不传 emotion_map → 走默认
        assert detect_emotion("哈哈", speech_emotion="happy") == "happy"

    def test_detect_emotion_without_override_backward_compat(self):
        """不传 emotion_map → 向后兼容"""
        assert detect_emotion("哈哈", speech_emotion="happy") == "happy"
        assert detect_emotion("今天星期三", speech_emotion="neutral") == "neutral"
