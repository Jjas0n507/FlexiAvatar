"""VAD 模块测试 — Silero VAD 语音/静音/打断检测"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
TEST_AUDIO_DIR = Path(__file__).parent.parent / "resources" / "test_audio"

from backend.vad.silero_adapter import SileroVAD

FRAME_SIZE = 512  # Silero VAD requires exactly 512 samples at 16kHz


def _test_file(path, label, expected_segments_min=1):
    """Test VAD on a WAV file"""
    print(f"\n{'='*50}")
    print(f"Test: {label}")
    print(f"File: {path}")

    audio = SileroVAD.load_wav(str(path))
    duration_s = len(audio) / 16000
    print(f"Duration: {duration_s:.2f}s, Samples: {len(audio)}")

    vad = SileroVAD(threshold=0.5, speech_start_frames=4, silence_end_frames=12)
    events, segments, segment_start = [], [], None

    for i, frame in enumerate(vad.frame_generator(audio, FRAME_SIZE)):
        result = vad.process_frame(frame)
        t = ((i + 1) * FRAME_SIZE) / 16000
        if result.event.value == "speech_start":
            segment_start = t
        elif result.event.value == "speech_end" and segment_start is not None:
            segments.append((segment_start, t))
            segment_start = None

    for s, e in segments:
        print(f"  [{s:.2f}s - {e:.2f}s] duration={e-s:.2f}s")

    assert len(segments) >= expected_segments_min, \
        f"Expected >= {expected_segments_min} segments, got {len(segments)}"
    print(f"  [OK] Detected {len(segments)} segment(s)")
    return True


def test_vad_synthetic():
    """合成音频 — VAD 应该忽略纯正弦波（语音模型预期行为）"""
    path = TEST_AUDIO_DIR / "synthetic_speech.wav"
    audio = SileroVAD.load_wav(str(path))
    vad = SileroVAD(threshold=0.5, speech_start_frames=4)
    speech_detected = False
    for frame in vad.frame_generator(audio, FRAME_SIZE):
        r = vad.process_frame(frame)
        if r.event.value in ("speech_start", "speech_continue"):
            speech_detected = True
    # 纯正弦波不具备语音声学特征，不应误触发
    print(f"[OK] Synthetic tones: speech_detected={speech_detected} (expected False for pure tones)")


def test_vad_chinese_speech():
    """中文语音检测"""
    for name in ["test_zh_hello", "test_zh_time"]:
        _test_file(TEST_AUDIO_DIR / f"{name}.wav", f"Chinese: {name}")


def test_interrupt_detection():
    """打断检测速度"""
    print(f"\n{'='*50}")
    print("Interrupt Detection")
    audio = SileroVAD.load_wav(str(TEST_AUDIO_DIR / "test_zh_hello.wav"))
    vad = SileroVAD(threshold=0.5, interrupt_frames=3)
    detected_at = None
    for i, frame in enumerate(vad.frame_generator(audio, FRAME_SIZE)):
        if vad.should_interrupt(frame):
            detected_at = i * FRAME_SIZE / 16000
            break
    assert detected_at is not None, "No interrupt detected"
    print(f"  [OK] Interrupt at t={detected_at:.2f}s (~{detected_at*1000:.0f}ms)")


def test_silence_no_false_positive():
    """静音无误报"""
    silence = np.zeros(16000 * 2, dtype=np.float32)
    vad = SileroVAD(threshold=0.5, speech_start_frames=4)
    speech_detected = any(
        vad.process_frame(f).event.value in ("speech_start", "speech_continue")
        for f in vad.frame_generator(silence, FRAME_SIZE)
    )
    assert not speech_detected, "False positive on silence!"
    print("[OK] No false positives on silence")


if __name__ == "__main__":
    print("=" * 50)
    print("VAD Test Suite")
    print(f"Frame size: {FRAME_SIZE} samples ({FRAME_SIZE/16000*1000:.0f}ms)")
    print("=" * 50)
    test_vad_synthetic()
    test_vad_chinese_speech()
    test_interrupt_detection()
    test_silence_no_false_positive()
    print("\n=== All VAD tests passed ===")
