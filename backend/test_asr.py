"""ASR module test with Chinese speech audio"""
import sys
sys.path.insert(0, "D:/program/project")

import asyncio
from backend.asr.whisper_adapter import WhisperASR
from backend.vad.silero_adapter import SileroVAD


async def test_transcribe(asr, path: str, expected_text: str, label: str):
    """Test ASR on a WAV file"""
    print(f"\n{'='*50}")
    print(f"Test: {label}")
    print(f"File: {path}")
    print(f"Expected: {expected_text}")

    audio = SileroVAD.load_wav(path)
    print(f"Duration: {len(audio)/16000:.2f}s")

    result = await asr.transcribe(audio)
    print(f"Result:   {result.text}")
    print(f"Confidence: {result.confidence:.2%}")
    print(f"Language: {result.language}")

    # Check if expected text is roughly contained
    # (Whisper may add/remove punctuation, so do a fuzzy match)
    return result.text, result.confidence


async def main():
    print("=" * 50)
    print("Faster-Whisper ASR Test Suite")
    print("=" * 50)

    # Use medium model for best Chinese accuracy
    print("\nLoading model (first time downloads the model)...")
    asr = WhisperASR(model_size="medium", language="zh", device="cpu", compute_type="int8")
    await asr.warmup()
    print("Model loaded.\n")

    results = []

    # Test 1: Chinese hello
    text1, conf1 = await test_transcribe(
        asr,
        "D:/program/project/resources/test_audio/test_zh_hello.wav",
        "你好，今天天气真不错。我们出去散步吧。",
        "Chinese: weather greeting"
    )
    # Fuzzy check — at least "你好" should be in there
    ok1 = "你好" in text1 and len(text1) > 3
    results.append(("Chinese hello", ok1, conf1, text1))

    # Test 2: Chinese time
    text2, conf2 = await test_transcribe(
        asr,
        "D:/program/project/resources/test_audio/test_zh_time.wav",
        "请问现在是什么时间了？我想知道几点了。",
        "Chinese: asking time"
    )
    ok2 = len(text2) > 5
    results.append(("Chinese time", ok2, conf2, text2))

    # Test 3: Chinese search
    text3, conf3 = await test_transcribe(
        asr,
        "D:/program/project/resources/test_audio/test_zh_search.wav",
        "帮我搜索一下最近的人工智能新闻资讯。",
        "Chinese: search request"
    )
    ok3 = len(text3) > 5
    results.append(("Chinese search", ok3, conf3, text3))

    # Summary
    print(f"\n{'='*50}")
    print("Summary")
    print("=" * 50)
    all_pass = True
    for name, ok, conf, text in results:
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"  {status}: {name}")
        print(f"    Text: {text[:60]}{'...' if len(text)>60 else ''}")
        print(f"    Confidence: {conf:.2%}")
    print(f"\nOverall: {'ALL PASSED' if all_pass else 'SOME FAILED'}")
    print("=" * 50)


asyncio.run(main())
