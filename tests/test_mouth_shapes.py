"""mouth_shapes 模块测试 — 拼音韵母→口型映射"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from backend.live2d.mouth_shapes import PINYIN_TO_MOUTH, pinyin_final_to_mouth


class TestPinyinFinalToMouth:
    def test_known_finals(self):
        """已知韵母映射正确"""
        cases = [
            ("a", "A"), ("ai", "A"), ("an", "A"), ("ang", "A"), ("ao", "A"),
            ("ia", "A"), ("ian", "A"), ("iang", "A"), ("iao", "A"),
            ("ua", "A"), ("uai", "A"), ("uan", "A"), ("uang", "A"),
            ("e", "E"), ("ei", "E"), ("en", "E"), ("eng", "E"), ("er", "E"),
            ("ie", "E"), ("ue", "E"),
            ("i", "I"), ("in", "I"), ("ing", "I"),
            ("o", "O"), ("ou", "O"), ("ong", "O"), ("io", "O"), ("iong", "O"),
            ("u", "U"), ("un", "U"), ("iu", "U"), ("ui", "U"), ("uo", "U"),
            ("ü", "U"), ("üe", "U"), ("üan", "U"), ("ün", "U"),
        ]
        for final, expected in cases:
            assert pinyin_final_to_mouth(final) == expected, \
                f"pinyin_final_to_mouth('{final}') should be '{expected}'"

    def test_with_tone_numbers(self):
        """去掉声调数字"""
        assert pinyin_final_to_mouth("a1") == "A"
        assert pinyin_final_to_mouth("an3") == "A"
        assert pinyin_final_to_mouth("üe4") == "U"
        assert pinyin_final_to_mouth("ing2") == "I"
        assert pinyin_final_to_mouth("ong5") == "O"

    def test_unknown_defaults_to_n(self):
        """未知韵母默认闭嘴"""
        assert pinyin_final_to_mouth("xyz") == "N"
        assert pinyin_final_to_mouth("abc") == "N"

    def test_empty_defaults_to_n(self):
        """空字符串默认闭嘴"""
        assert pinyin_final_to_mouth("") == "N"

    def test_table_has_expected_entries(self):
        """表有 37 个条目（与当前两份重复表一致）"""
        assert len(PINYIN_TO_MOUTH) == 37, \
            f"Expected 37 entries, got {len(PINYIN_TO_MOUTH)}"

    def test_both_tables_identical(self):
        """现有两份表的 key-value 完全一致（回归检测）"""
        # 导入 motion_controller 的表
        from backend.live2d.motion_controller import (
            _PHONEME_TO_MOUTH as motion_table,
        )
        # 直接检查新表与 motion_controller 的表一致
        assert PINYIN_TO_MOUTH == motion_table, \
            "New PINYIN_TO_MOUTH differs from existing table! Regression detected."
        assert len(PINYIN_TO_MOUTH) == len(motion_table), \
            f"Table sizes differ: new={len(PINYIN_TO_MOUTH)} vs motion={len(motion_table)}"
