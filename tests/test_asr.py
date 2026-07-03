"""ASR 模块测试 — Faster-Whisper 中文语音识别

测试模拟线上行为：模型启动时加载一次，后续所有音频复用同一个模型实例。
这能真实反映每次语音输入的延迟。
"""
import sys
import os
import time
from pathlib import Path

# Windows 上 MKL 与 LLVM OpenMP 冲突修复 (conda 环境必需)
# 否则 CTranslate2 在 transcribe() 时会直接崩溃 (exit code 127)
if sys.platform == "win32":
    os.environ.setdefault("MKL_THREADING_LAYER", "sequential")
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
TEST_AUDIO_DIR = Path(__file__).parent.parent / "resources" / "test_audio"

from backend.asr.whisper_adapter import WhisperASR
from backend.vad.silero_adapter import SileroVAD
from backend.config import config

# 从配置读取模型大小（默认 base）
MODEL_SIZE = config.get("asr.whisper.model_size", "base")
DEVICE = config.get("asr.whisper.device", "cpu")
COMPUTE_TYPE = config.get("asr.whisper.compute_type", "int8")


async def _transcribe_and_check(asr, path, label, min_length=3):
    """识别并检查结果（复用已加载的 ASR 实例）"""
    t_start = time.perf_counter()
    print(f"\n{'='*50}")
    print(f"Test: {label}")
    print(f"  [timestamp] start: {time.strftime('%H:%M:%S')}")

    # 音频加载计时
    audio = SileroVAD.load_wav(str(path))
    duration_s = len(audio) / 16000
    print(f"  Audio: {duration_s:.2f}s, {len(audio)} samples")

    # 转录计时
    t_transcribe_start = time.perf_counter()
    result = await asr.transcribe(audio)
    t_transcribe_ms = (time.perf_counter() - t_transcribe_start) * 1000
    rtf = t_transcribe_ms / 1000 / duration_s

    status = "OK" if rtf < 1.0 else "WARN"
    print(f"  Result: '{result.text}'")
    print(f"  Confidence: {result.confidence:.2%}")
    print(f"  Language: {result.language}")
    print(f"  [TIMING] Transcribe: {t_transcribe_ms:.0f}ms, RTF: {rtf:.2f}x [{status}]")

    assert len(result.text) >= min_length, f"Text too short: '{result.text}'"

    total_ms = (time.perf_counter() - t_start) * 1000
    print(f"  [OK] total: {total_ms:.0f}ms")
    return result.text, result.confidence


async def main():
    t_suite_start = time.perf_counter()
    print("=" * 50)
    print("ASR Test Suite")
    print(f"Started at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Model: Whisper {MODEL_SIZE} on {DEVICE} ({COMPUTE_TYPE})")
    print("=" * 50)

    # ── 启动时加载模型（仅一次，模拟线上行为） ──
    print(f"\n[TIMING] Loading model (one-time startup cost)...")
    t_load_start = time.perf_counter()
    asr = WhisperASR(model_size=MODEL_SIZE, language="zh",
                     device=DEVICE, compute_type=COMPUTE_TYPE)
    await asr.warmup()
    startup_ms = (time.perf_counter() - t_load_start) * 1000
    print(f"[TIMING] Model warmup: {startup_ms:.0f}ms ({startup_ms/1000:.1f}s)")
    print(f"  This is a one-time cost at startup, not per-request latency.")

    # ── 逐文件测试（模拟每次语音输入） ──
    results = []
    results.append(await _transcribe_and_check(
        asr, TEST_AUDIO_DIR / "test_zh_hello.wav",
        "Chinese: weather greeting", min_length=3
    ))
    results.append(await _transcribe_and_check(
        asr, TEST_AUDIO_DIR / "test_zh_time.wav",
        "Chinese: asking time", min_length=2
    ))
    results.append(await _transcribe_and_check(
        asr, TEST_AUDIO_DIR / "test_zh_search.wav",
        "Chinese: search request", min_length=2
    ))

    # 验证所有测试都有合理的置信度
    for i, (text, conf) in enumerate(results):
        assert conf > 0.3, f"Test {i+1} confidence too low: {conf}"

    suite_ms = (time.perf_counter() - t_suite_start) * 1000
    print(f"\n{'='*50}")
    print("Summary:")
    print(f"  Startup cost: {startup_ms:.0f}ms (once)")
    transcribe_ms = suite_ms - startup_ms
    print(f"  Transcription: ~{transcribe_ms:.0f}ms for 3 files")
    print(f"=== All ASR tests passed ===")
    print(f"[TIMING] Total suite time: {suite_ms:.0f}ms ({suite_ms/1000:.1f}s)")


async def test_stream_transcribe():
    """测试流式识别 — 验证中间结果 is_final=False，最终结果 is_final=True"""
    import time
    from pathlib import Path as _Path
    TEST_DIR = _Path(__file__).parent.parent / "resources" / "test_audio"

    print(f"\n{'='*50}")
    print("Test: Streaming ASR")
    print("=" * 50)

    asr = WhisperASR(model_size=MODEL_SIZE, language="zh",
                     device=DEVICE, compute_type=COMPUTE_TYPE)
    await asr.warmup()

    audio = SileroVAD.load_wav(str(TEST_DIR / "test_zh_hello.wav"))
    print(f"  Audio: {len(audio)/16000:.1f}s")

    intermediate_count = 0
    final_count = 0
    last_text = ""

    async for result in asr.stream_transcribe(audio):
        if result.is_final:
            final_count += 1
            print(f"  [FINAL]   text='{result.text[:50]}', conf={result.confidence:.2%}")
        else:
            intermediate_count += 1
            last_text = result.text
            print(f"  [partial] text='{result.text[:50]}', conf={result.confidence:.2%}")

    assert intermediate_count >= 1, "Expected at least 1 intermediate result"
    assert final_count == 1, f"Expected 1 final result, got {final_count}"
    print(f"  [OK] {intermediate_count} intermediate + {final_count} final")


if __name__ == "__main__":
    asyncio.run(main())
    asyncio.run(test_stream_transcribe())
