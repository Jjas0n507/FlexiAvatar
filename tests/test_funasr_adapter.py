"""FunASR SenseVoice 适配器测试 — 情绪解析 + 文本清洗

所有测试为纯逻辑验证，不依赖 torch/funasr 实际模型。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from backend.asr.base import ASRResult
from backend.asr.funasr_adapter import (
    _parse_emotion,
    _clean_text,
    _parse_audio_events,
    _EMOTION_TAG_MAP,
    _AUDIO_EVENT_TAGS,
    FunASRAdapter,
)
from backend.live2d.motion_controller import _SPEECH_EMOTION_MAP


# ── _parse_emotion 测试 ────────────────────────

class TestParseEmotion:
    """从 SenseVoice rich text 中提取情绪"""

    @pytest.mark.parametrize("raw, expected", [
        ("<|HAPPY|>今天天气真好", "happy"),
        ("<|ANGRY|>你这个笨蛋", "angry"),
        ("<|SAD|>我今天很难过", "sad"),
        ("<|NEUTRAL|>今天星期三", "neutral"),
        ("<|SURPRISED|>真的吗", "surprised"),
        ("<|FEARFUL|>好可怕", "fearful"),
        ("<|DISGUSTED|>好恶心", "disgusted"),
    ])
    def test_emotion_tag_parsed(self, raw, expected):
        emotion, conf = _parse_emotion(raw)
        assert emotion == expected
        assert conf == 1.0

    def test_no_emotion_tag_returns_neutral(self):
        emotion, conf = _parse_emotion("你好")
        assert emotion == "neutral"
        assert conf == 0.0

    def test_only_audio_event_not_emotion(self):
        """仅含音频事件标签（非情绪）时返回 neutral"""
        emotion, conf = _parse_emotion("<|BGM|>纯音乐")
        assert emotion == "neutral"

    def test_first_emotion_tag_wins(self):
        """多个情绪标签时取第一个"""
        emotion, _ = _parse_emotion("<|ANGRY|>滚<|SAD|>算了")
        assert emotion == "angry"

    def test_emotion_with_audio_event(self):
        """情绪标签 + 音频事件 — 情绪正确提取"""
        emotion, _ = _parse_emotion("<|HAPPY|>你好<|LAUGHTER|>")
        assert emotion == "happy"

    def test_empty_text(self):
        emotion, conf = _parse_emotion("")
        assert emotion == "neutral"
        assert conf == 0.0


# ── _clean_text 测试 ────────────────────────────

class TestCleanText:
    """去除 SenseVoice rich text 标签"""

    def test_remove_emotion_tag(self):
        assert _clean_text("<|HAPPY|>今天天气真好") == "今天天气真好"

    def test_remove_emotion_and_bgm(self):
        assert _clean_text("<|HAPPY|>你好<|BGM|>") == "你好"

    def test_no_tags_unchanged(self):
        assert _clean_text("你好世界") == "你好世界"

    def test_all_tags_removed_empty(self):
        assert _clean_text("<|BGM|>") == ""

    def test_multiple_tags_stripped(self):
        result = _clean_text("<|HAPPY|>你好<|BGM|>世界")
        assert "你好" in result
        assert "世界" in result
        assert "<|" not in result


# ── _parse_audio_events 测试 ────────────────────

class TestParseAudioEvents:
    """提取音频事件标签"""

    def test_detect_bgm(self):
        assert "bgm" in _parse_audio_events("<|HAPPY|>你好<|BGM|>")

    def test_detect_applause(self):
        assert "applause" in _parse_audio_events("<|APPLAUSE|>")

    def test_no_events(self):
        assert _parse_audio_events("<|HAPPY|>你好") == []

    def test_emotion_not_audio_event(self):
        assert "happy" not in _parse_audio_events("<|HAPPY|>你好")

    def test_multiple_events(self):
        events = _parse_audio_events("<|BGM|><|APPLAUSE|>")
        assert "bgm" in events
        assert "applause" in events


# ── 情绪映射完整性 ──────────────────────────────

class TestEmotionMapCompleteness:
    """确认映射表覆盖所有 SenseVoice 情绪标签"""

    def test_all_known_emotions_mapped(self):
        known = {"HAPPY", "ANGRY", "SAD", "NEUTRAL", "FEARFUL", "DISGUSTED", "SURPRISED"}
        assert set(_EMOTION_TAG_MAP.keys()) == known

    def test_speech_emotion_map_covers_all(self):
        """_SPEECH_EMOTION_MAP 覆盖所有非音频事件情绪"""
        needed = {"happy", "angry", "sad", "neutral", "fearful", "surprised", "disgusted"}
        assert set(_SPEECH_EMOTION_MAP.keys()) == needed

    def test_audio_tags_not_in_emotion_map(self):
        for tag in _AUDIO_EVENT_TAGS:
            assert tag not in _EMOTION_TAG_MAP

    def test_known_audio_events(self):
        expected = {"BGM", "APPLAUSE", "LAUGHTER", "CRY", "COUGH", "SNEEZE"}
        assert _AUDIO_EVENT_TAGS == expected

    @pytest.mark.parametrize("ser_emotion, live2d_emotion", [
        ("happy", "happy"),
        ("angry", "angry"),
        ("sad", "sad"),
        ("fearful", "surprised"),
        ("surprised", "surprised"),
        ("disgusted", "sad"),
        ("neutral", "neutral"),
    ])
    def test_speech_to_live2d_mapping(self, ser_emotion, live2d_emotion):
        assert _SPEECH_EMOTION_MAP[ser_emotion] == live2d_emotion


# ── ASRResult 默认值 ────────────────────────────

class TestASRResultDefaults:
    """向后兼容：默认 emotion 字段不影响现有代码"""

    def test_default_emotion_is_neutral(self):
        result = ASRResult(text="你好", confidence=0.9)
        assert result.emotion == "neutral"
        assert result.emotion_confidence == 0.0

    def test_explicit_emotion_settable(self):
        result = ASRResult(
            text="你好", confidence=0.9,
            emotion="happy", emotion_confidence=0.85,
        )
        assert result.emotion == "happy"
        assert result.emotion_confidence == 0.85


# ── FunASRAdapter 基本信息 ──────────────────────

class TestFunASRAdapter:
    """适配器元信息 + 构造参数"""

    def test_get_info(self):
        info = FunASRAdapter.get_info()
        assert info["name"] == "FunASRSenseVoice"
        assert "emotion_recognition" in info["features"]

    def test_init_defaults(self):
        adapter = FunASRAdapter()
        assert adapter._model_name == "iic/SenseVoiceSmall"
        assert adapter._device == "cpu"
        assert adapter._language == "auto"

    def test_init_custom(self):
        adapter = FunASRAdapter(device="cuda:0", language="zh")
        assert adapter._device == "cuda:0"
        assert adapter._language == "zh"
