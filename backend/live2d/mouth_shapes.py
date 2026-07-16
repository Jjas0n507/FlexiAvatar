"""
中文拼音韵母 → Live2D 五口型映射。

纯语言学规则，不依赖任何模型配置。
A=张口, I=咧嘴, U=嘟嘴, E=半开, O=圆唇, N=闭嘴
"""

# 中文拼音韵母 → 五口型映射
PINYIN_TO_MOUTH: dict[str, str] = {
    # A 组 — 张口
    "a": "A", "ai": "A", "an": "A", "ang": "A", "ao": "A",
    "ia": "A", "ian": "A", "iang": "A", "iao": "A",
    "ua": "A", "uai": "A", "uan": "A", "uang": "A",
    # E 组 — 半开
    "e": "E", "ei": "E", "en": "E", "eng": "E", "er": "E",
    "ie": "E", "ue": "E",
    # I 组 — 咧嘴
    "i": "I", "in": "I", "ing": "I",
    # O 组 — 圆唇
    "o": "O", "ou": "O", "ong": "O",
    "io": "O", "iong": "O",
    # U 组 — 嘟嘴
    "u": "U", "un": "U",
    "iu": "U", "ui": "U", "uo": "U",
    "ü": "U", "üe": "U", "üan": "U", "ün": "U",
}


def pinyin_final_to_mouth(final: str) -> str:
    """将拼音韵母映射到 Live2D 口型 (A/I/U/E/O/N)"""
    # 去掉声调数字
    final_clean = final.rstrip("0123456789")
    return PINYIN_TO_MOUTH.get(final_clean, "N")  # 默认闭嘴
