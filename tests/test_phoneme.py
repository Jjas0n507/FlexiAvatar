"""测试 Phoneme dataclass 的 char 和 volume 字段 (Phase 1.1)"""

import pytest
from backend.tts.base import Phoneme


class TestPhonemeChar:
    def test_phoneme_has_char_field(self):
        """构造时传 char 可用"""
        p = Phoneme(phoneme="A", start_ms=0.0, end_ms=100.0, char="啊")
        assert p.char == "啊"

    def test_phoneme_char_defaults_empty(self):
        """char 默认值为空字符串"""
        p = Phoneme(phoneme="A", start_ms=0.0, end_ms=100.0)
        assert p.char == ""

    def test_phoneme_char_is_optional(self):
        """不传 char 时不报错"""
        p = Phoneme(phoneme="E", start_ms=50.0, end_ms=150.0)
        assert p.phoneme == "E"  # 其他字段不受影响


class TestPhonemeVolume:
    def test_phoneme_has_volume_field(self):
        """构造时传 volume 可用"""
        p = Phoneme(phoneme="A", start_ms=0.0, end_ms=100.0, volume=0.8)
        assert p.volume == 0.8

    def test_phoneme_volume_defaults_0_5(self):
        """volume 默认值为 0.5"""
        p = Phoneme(phoneme="A", start_ms=0.0, end_ms=100.0)
        assert p.volume == 0.5

    def test_phoneme_volume_is_optional(self):
        """不传 volume 时不报错"""
        p = Phoneme(phoneme="I", start_ms=50.0, end_ms=150.0)
        assert p.phoneme == "I"
        assert p.volume == 0.5


class TestPhonemeBackwardCompatibility:
    def test_existing_positional_args_still_work(self):
        """现有 Phoneme(phoneme, start_ms, end_ms) 调用方式不受影响"""
        p = Phoneme("A", 0.0, 100.0)
        assert p.phoneme == "A"
        assert p.start_ms == 0.0
        assert p.end_ms == 100.0
        assert p.char == ""
        assert p.volume == 0.5

    def test_all_fields_keyword(self):
        """关键字传所有字段"""
        p = Phoneme(
            phoneme="O",
            start_ms=200.0,
            end_ms=350.0,
            char="哦",
            volume=0.9,
        )
        assert p.phoneme == "O"
        assert p.char == "哦"
        assert p.volume == 0.9
