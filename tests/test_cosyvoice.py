"""CosyVoice2 适配器测试 — 模型/依赖不存在时自动跳过（需 GPU 环境手动跑）"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio

import pytest

MODEL_DIR = Path(__file__).parent.parent / "resources" / "models" / "CosyVoice2-0.5B"
REF_AUDIO = Path(__file__).parent.parent / "resources" / "voices" / "ref.wav"


def _cosyvoice_available() -> bool:
    try:
        import cosyvoice  # noqa: F401
    except ImportError:
        return False
    return MODEL_DIR.exists() and REF_AUDIO.exists()


@pytest.mark.skipif(not _cosyvoice_available(), reason="CosyVoice 未安装或模型/参考音频缺失")
def test_synthesize_wav():
    from backend.tts.cosyvoice_adapter import CosyVoice2Adapter

    async def run():
        tts = CosyVoice2Adapter(
            model_dir=str(MODEL_DIR),
            ref_audio=str(REF_AUDIO),
            ref_text="这是参考音频的文本。",
        )
        result = await tts.synthesize("你好，我是本地合成的声音。")
        assert result.format == "wav"
        assert result.audio_bytes[:4] == b"RIFF"
        assert result.duration_ms > 300
        # RTF 粗查在日志里看；这里只验证契约
        empty = await tts.synthesize("  ")
        assert empty.audio_bytes == b""

    asyncio.run(run())


def test_adapter_importable_without_cosyvoice():
    """未安装 CosyVoice 时 import 适配器不应报错（懒加载），报错发生在首次 synthesize"""
    from backend.tts.cosyvoice_adapter import CosyVoice2Adapter
    tts = CosyVoice2Adapter()
    assert tts is not None
