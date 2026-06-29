"""ASR 模块测试 — Faster-Whisper 中文语音识别"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
TEST_AUDIO_DIR = Path(__file__).parent.parent / "resources" / "test_audio"

from backend.asr.whisper_adapter import WhisperASR
from backend.vad.silero_adapter import SileroVAD


async def _transcribe_and_check(path, label, min_length=3):
    """识别并检查结果"""
    asr = WhisperASR(model_size="medium", language="zh", device="cpu", compute_type="int8")
    await asr.warmup()

    audio = SileroVAD.load_wav(str(path))
    result = await asr.transcribe(audio)

    print(f"\n{'='*50}")
    print(f"Test: {label}")
    print(f"  Expected words in text")
    print(f"  Result: '{result.text}'")
    print(f"  Confidence: {result.confidence:.2%}")
    print(f"  Language: {result.language}")

    assert len(result.text) >= min_length, f"Text too short: '{result.text}'"
    print(f"  [OK]")
    return result.text, result.confidence


async def main():
    print("=" * 50)
    print("ASR Test Suite")
    print("=" * 50)

    results = []
    results.append(await _transcribe_and_check(
        TEST_AUDIO_DIR / "test_zh_hello.wav", "Chinese: weather greeting", min_length=3
    ))
    results.append(await _transcribe_and_check(
        TEST_AUDIO_DIR / "test_zh_time.wav", "Chinese: asking time", min_length=2
    ))
    results.append(await _transcribe_and_check(
        TEST_AUDIO_DIR / "test_zh_search.wav", "Chinese: search request", min_length=2
    ))

    # 验证所有测试都有合理的置信度
    for i, (text, conf) in enumerate(results):
        assert conf > 0.3, f"Test {i+1} confidence too low: {conf}"

    print("\n=== All ASR tests passed ===")


if __name__ == "__main__":
    asyncio.run(main())
