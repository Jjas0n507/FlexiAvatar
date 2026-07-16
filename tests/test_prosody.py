"""WAV RMS 音量提取测试 (Phase 1.3)"""
import io
import struct
import wave
import math
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from backend.audio.prosody import extract_volume_envelope


def _make_wav(samples: list[float], sample_rate: int = 24000) -> bytes:
    """生成 WAV 字节（16-bit PCM mono）"""
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for s in samples:
            # clamp to [-1, 1]
            s = max(-1.0, min(1.0, s))
            wf.writeframes(struct.pack("<h", int(s * 32767)))
    return buf.getvalue()


class TestExtractVolumeEnvelope:
    def test_silence(self):
        """静音 WAV → 值全 ~0.0"""
        samples = [0.0] * 24000  # 1 second
        wav = _make_wav(samples)
        vols = extract_volume_envelope(wav, frame_ms=100.0)
        assert all(v < 0.01 for v in vols), f"Expected near-zero, got {vols[:3]}"

    def test_full_scale(self):
        """满幅正弦波 → 值全 ~1.0"""
        sr = 24000
        duration = 1.0
        samples = [
            math.sin(2.0 * math.pi * 440.0 * t / sr)
            for t in range(int(sr * duration))
        ]
        wav = _make_wav(samples)
        vols = extract_volume_envelope(wav, frame_ms=100.0)
        # RMS of sine wave ≈ 0.707, normalized to ~1.0
        assert all(v > 0.6 for v in vols), f"Expected near-1.0, got {vols[:3]}"

    def test_output_length(self):
        """500ms 音频 @50ms 帧 → ~10 帧"""
        samples = [0.0] * 12000  # 500ms @ 24000Hz
        wav = _make_wav(samples)
        vols = extract_volume_envelope(wav, frame_ms=50.0)
        assert 8 <= len(vols) <= 12, f"Expected ~10 frames for 500ms, got {len(vols)}"

    def test_values_range(self):
        """值全在 [0.0, 1.0] 内"""
        sr = 24000
        samples = [
            0.5 * math.sin(2.0 * math.pi * 440.0 * t / sr)
            for t in range(24000)
        ]
        wav = _make_wav(samples)
        vols = extract_volume_envelope(wav, frame_ms=50.0)
        for v in vols:
            assert 0.0 <= v <= 1.0, f"Volume {v} out of range [0.0, 1.0]"

    def test_monotonic_with_amplitude(self):
        """递增幅度对应递增 RMS"""
        sr = 24000
        # 前半段 0.2 幅度，后半段 0.8 幅度
        n = sr // 2
        low = [0.2 * math.sin(2.0 * math.pi * 440.0 * t / sr) for t in range(n)]
        high = [0.8 * math.sin(2.0 * math.pi * 440.0 * t / sr) for t in range(n)]
        wav = _make_wav(low + high)
        vols = extract_volume_envelope(wav, frame_ms=200.0)
        mid = len(vols) // 2
        first_half_avg = sum(vols[:mid]) / max(mid, 1)
        second_half_avg = sum(vols[mid:]) / max(len(vols[mid:]), 1)
        assert second_half_avg > first_half_avg, \
            f"Second half ({second_half_avg:.3f}) should be louder than first ({first_half_avg:.3f})"

    def test_empty_input_raises(self):
        """空 bytes 抛 ValueError"""
        with pytest.raises(ValueError):
            extract_volume_envelope(b"", frame_ms=50.0)

    def test_very_short_audio(self):
        """极短音频（< 1帧）仍能返回至少1帧"""
        # 10ms of audio @ 24000Hz = 240 samples
        samples = [0.5] * 240
        wav = _make_wav(samples)
        vols = extract_volume_envelope(wav, frame_ms=50.0)
        assert len(vols) >= 1
