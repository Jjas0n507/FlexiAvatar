"""TTS 模块测试 — Edge-TTS 合成 + 口型时间线"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
TEST_AUDIO_DIR = Path(__file__).parent.parent / "resources" / "test_audio"

from backend.tts.edge_tts_adapter import EdgeTTSAdapter


async def main():
    print("=" * 50)
    print("TTS Test Suite")
    print("=" * 50)

    tts = EdgeTTSAdapter(voice="zh-CN-XiaoxiaoNeural", speed="+10%")

    # Test 1: Basic synthesis
    print("\n--- Test 1: Basic synthesis ---")
    result = await tts.synthesize("你好，我是你的智能助手。")
    assert len(result.audio_bytes) > 1000, "Audio too short"
    assert result.duration_ms > 500, f"Duration too short: {result.duration_ms}ms"
    print(f"  Audio: {len(result.audio_bytes)} bytes, {result.duration_ms:.0f}ms")
    print(f"  Phonemes: {len(result.phonemes)}")
    if result.phonemes:
        mouths = set(p.phoneme for p in result.phonemes)
        print(f"  Mouth shapes: {mouths}")
    print("  [OK]")

    # Test 2: Multi-sentence
    print("\n--- Test 2: Multi-sentence ---")
    result2 = await tts.synthesize("今天天气真不错。阳光明媚。我们出去散步吧！")
    assert len(result2.audio_bytes) > 2000
    mouths2 = set(p.phoneme for p in result2.phonemes)
    assert len(mouths2) >= 2, f"Need >= 2 mouth shapes, got {mouths2}"
    print(f"  Phonemes: {len(result2.phonemes)}, Mouth shapes: {mouths2}")
    print("  [OK]")

    # Test 3: Edge cases
    print("\n--- Test 3: Edge cases ---")
    assert len((await tts.synthesize("")).audio_bytes) == 0
    print("  [OK] Empty text")
    assert len((await tts.synthesize("嗯")).audio_bytes) > 100
    print("  [OK] Single char")

    # Test 4: Voices
    print("\n--- Test 4: Voices ---")
    voices = await tts.voices()
    assert len(voices) >= 3
    for v in voices:
        print(f"  {v['id']}: {v['name']}")
    print("  [OK]")

    # Save a test output (gitignored)
    output_path = TEST_AUDIO_DIR / "tts_output_1.wav"
    with open(str(output_path), "wb") as f:
        f.write(result.audio_bytes)
    print(f"\n  Saved sample to: {output_path}")

    print("\n=== All TTS tests passed ===")


if __name__ == "__main__":
    asyncio.run(main())
