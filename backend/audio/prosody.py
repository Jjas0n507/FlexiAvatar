"""
WAV 音量提取工具 (Phase 1.3)。

从 WAV 音频数据提取 RMS 音量包络，用于驱动 Live2D 口型缩放。
"""

from __future__ import annotations

import io
import math
import struct
import wave


def extract_volume_envelope(
    audio_bytes: bytes,
    frame_ms: float = 50.0,
) -> list[float]:
    """
    从 WAV 音频数据提取归一化 RMS 音量包络。

    返回每帧的 RMS 值，归一化到 [0.0, 1.0]（16-bit PCM 满幅为 1.0）。

    Args:
        audio_bytes: WAV 格式的音频字节数据
        frame_ms: 每帧时长（毫秒），默认 50ms

    Returns:
        音量包络列表，每个元素 ∈ [0.0, 1.0]

    Raises:
        ValueError: 输入为空或不是有效 WAV
    """
    if not audio_bytes:
        raise ValueError("Empty audio data, cannot extract volume envelope")

    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
            sample_rate = wf.getframerate()
            n_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            n_frames = wf.getnframes()

            if n_frames == 0:
                return [0.0]

            raw = wf.readframes(n_frames)
    except Exception as e:
        raise ValueError(f"Invalid WAV data: {e}") from e

    # 解析 PCM 样本
    if sample_width == 2:
        total_samples = n_frames * n_channels
        fmt = f"<{total_samples}h"
        samples = struct.unpack(fmt, raw)
    else:
        raise ValueError(
            f"Unsupported sample width: {sample_width} (expected 2 for 16-bit PCM)"
        )

    # 转单声道
    if n_channels > 1:
        mono: list[float] = []
        for i in range(0, len(samples), n_channels):
            mono.append(sum(samples[i:i + n_channels]) / n_channels)
    else:
        mono = list(samples)

    if not mono:
        return [0.0]

    # 帧大小（样本数）
    frame_samples = max(1, int(sample_rate * frame_ms / 1000.0))

    # 逐帧计算归一化 RMS
    envelopes: list[float] = []
    for i in range(0, len(mono), frame_samples):
        chunk = mono[i:i + frame_samples]
        if not chunk:
            break
        # RMS
        mean_sq = sum(s * s for s in chunk) / len(chunk)
        rms = math.sqrt(mean_sq)
        # 归一化：16-bit max = 32767
        normalized = rms / 32767.0
        envelopes.append(round(min(normalized, 1.0), 4))

    if not envelopes:
        envelopes = [0.0]

    return envelopes
