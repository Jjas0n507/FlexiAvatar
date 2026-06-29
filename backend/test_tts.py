"""TTS module test with Edge-TTS"""
import sys
sys.path.insert(0, "D:/program/project")

import asyncio
from backend.tts.edge_tts_adapter import EdgeTTSAdapter


async def main():
    print("=" * 50)
    print("Edge-TTS Test Suite")
    print("=" * 50)

    tts = EdgeTTSAdapter(voice="zh-CN-XiaoxiaoNeural", speed="+10%")

    # Test 1: Basic synthesis
    print("\n--- Test 1: Basic synthesis ---")
    text1 = "你好，我是你的智能助手，很高兴认识你。"
    result1 = await tts.synthesize(text1)
    print(f"  Text: {text1}")
    print(f"  Audio: {len(result1.audio_bytes)} bytes")
    print(f"  Duration: {result1.duration_ms:.0f}ms")
    print(f"  Sample rate: {result1.sample_rate}Hz")
    print(f"  Phoneme count: {len(result1.phonemes)}")

    path1 = "D:/program/project/resources/test_audio/tts_output_1.wav"
    with open(path1, "wb") as f:
        f.write(result1.audio_bytes)
    print(f"  Saved: {path1}")

    if result1.phonemes:
        print(f"  First 8 mouth shapes:")
        for p in result1.phonemes[:8]:
            print(f"    [{p.start_ms:.0f}-{p.end_ms:.0f}ms] {p.phoneme}")

    assert len(result1.audio_bytes) > 500, "Audio should have data"
    print("  [PASS] Basic synthesis")

    # Test 2: Longer text with multiple sentences
    print("\n--- Test 2: Multi-sentence text ---")
    text2 = "今天天气真不错。阳光明媚，温度适宜。我们出去散步吧！"
    result2 = await tts.synthesize(text2)
    print(f"  Text: {text2}")
    print(f"  Audio: {len(result2.audio_bytes)} bytes")
    print(f"  Duration: {result2.duration_ms:.0f}ms")
    print(f"  Phoneme count: {len(result2.phonemes)}")

    path2 = "D:/program/project/resources/test_audio/tts_output_2.wav"
    with open(path2, "wb") as f:
        f.write(result2.audio_bytes)
    print(f"  Saved: {path2}")
    assert len(result2.audio_bytes) > 1000
    print("  [PASS] Multi-sentence synthesis")

    # Test 3: Phoneme mouth shapes distribution
    print("\n--- Test 3: Mouth shape variety ---")
    mouths = set(p.phoneme for p in result2.phonemes) if result2.phonemes else set()
    print(f"  Unique mouth shapes in text: {mouths}")
    # Should have more than just N (closed mouth)
    assert len(mouths) >= 1
    if result2.phonemes:
        assert len(mouths) >= 2 or len(result2.phonemes) < 3, "Need variety"
    print("  [PASS] Mouth shape variety")

    # Test 4: Edge cases
    print("\n--- Test 4: Edge cases ---")
    result_empty = await tts.synthesize("")
    assert len(result_empty.audio_bytes) == 0
    assert len(result_empty.phonemes) == 0
    print("  [PASS] Empty text")

    result_short = await tts.synthesize("嗯")
    assert len(result_short.audio_bytes) > 200
    print("  [PASS] Single character")

    # Test 5: Voices
    print("\n--- Test 5: Available voices ---")
    voices = await tts.voices()
    for v in voices:
        print(f"  {v['id']} -> {v['name']}")
    assert len(voices) >= 3
    print("  [PASS] Voice listing")

    # Summary
    print(f"\n{'='*50}")
    print("Summary: ALL PASSED")
    print("=" * 50)


asyncio.run(main())
