"""VAD module test with synthetic and Chinese speech audio"""
import sys
sys.path.insert(0, "D:/program/project")

from backend.vad.silero_adapter import SileroVAD

FRAME_SIZE = 512  # Silero VAD requirement at 16kHz


def test_file(path: str, label: str):
    """Test VAD on an audio file"""
    print(f"\n{'='*50}")
    print(f"Test: {label}")
    print(f"File: {path}")

    audio = SileroVAD.load_wav(path)
    duration_s = len(audio) / 16000
    print(f"Duration: {duration_s:.2f}s, Samples: {len(audio)}")

    vad = SileroVAD(
        threshold=0.5,
        speech_start_frames=4,
        silence_end_frames=12,
        interrupt_frames=3,
    )

    events = []
    speech_segments = []
    segment_start = None
    total_frames = 0

    for frame in vad.frame_generator(audio, FRAME_SIZE):
        result = vad.process_frame(frame)
        total_frames += 1
        t = (total_frames * FRAME_SIZE) / 16000

        if result.event.value != "silence":
            events.append(
                f"  t={t:.2f}s event={result.event.value} prob={result.speech_prob:.2f}"
            )
            if result.event.value == "speech_start":
                segment_start = t
            elif result.event.value == "speech_end" and segment_start is not None:
                speech_segments.append((segment_start, t))
                segment_start = None

    # Print events
    for e in events[:15]:
        print(e)
    if len(events) > 15:
        print(f"  ... ({len(events) - 15} more events)")

    print(f"\n  Detected {len(speech_segments)} speech segment(s):")
    for start, end in speech_segments:
        print(f"    [{start:.2f}s - {end:.2f}s] duration={end-start:.2f}s")

    return len(speech_segments) > 0


# ── Interrupt test ─────────────────────────────────

def test_interrupt(path: str):
    """Test interrupt detection speed"""
    print(f"\n{'='*50}")
    print("Interrupt Detection Test")
    print("=" * 50)

    audio = SileroVAD.load_wav(path)
    vad = SileroVAD(threshold=0.5, interrupt_frames=3)

    detected_at = None
    for i, frame in enumerate(vad.frame_generator(audio, FRAME_SIZE)):
        t = i * FRAME_SIZE / 16000
        if vad.should_interrupt(frame):
            detected_at = t
            break

    if detected_at is not None:
        print(f"  [OK] Interrupt detected at t={detected_at:.2f}s (~{detected_at*1000:.0f}ms)")
        return True
    else:
        print("  [WARN] No interrupt detected")
        return False


# ── Silence test ───────────────────────────────────

def test_silence():
    """VAD should not fire on silence"""
    print(f"\n{'='*50}")
    print("Silence Test")
    print("=" * 50)

    import numpy as np
    silence = np.zeros(16000 * 2, dtype=np.float32)  # 2 seconds
    vad = SileroVAD(threshold=0.5, speech_start_frames=4)
    speech_detected = False
    for frame in vad.frame_generator(silence, FRAME_SIZE):
        result = vad.process_frame(frame)
        if result.event.value in ("speech_start", "speech_continue"):
            speech_detected = True

    print(f"  Speech on silence: {speech_detected} (should be False)" if speech_detected
          else "  [OK] No false positives on silence")
    return not speech_detected


# ── Main ───────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("Silero VAD Test Suite")
    print(f"Frame size: {FRAME_SIZE} samples ({FRAME_SIZE/16000*1000:.0f}ms)")
    print("=" * 50)

    results = {}

    # 1. Synthetic
    results["Synthetic tones"] = test_file(
        "D:/program/project/resources/test_audio/synthetic_speech.wav",
        "Synthetic tones (2 segments expected)"
    )

    # 2. Chinese speech samples
    results["Chinese hello"] = test_file(
        "D:/program/project/resources/test_audio/test_zh_hello.wav",
        "Chinese: hello"
    )
    results["Chinese time"] = test_file(
        "D:/program/project/resources/test_audio/test_zh_time.wav",
        "Chinese: time"
    )

    # 3. Interrupt speed
    results["Interrupt detection"] = test_interrupt(
        "D:/program/project/resources/test_audio/test_zh_hello.wav"
    )

    # 4. Silence
    results["Silence no false positive"] = test_silence()

    # Summary
    print(f"\n{'='*50}")
    print("Summary")
    print("=" * 50)
    all_pass = True
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  {status}: {name}")
    print(f"\nOverall: {'ALL PASSED' if all_pass else 'SOME FAILED'}")
    print("=" * 50)
