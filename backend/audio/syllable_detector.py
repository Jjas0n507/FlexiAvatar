"""
Syllable boundary detector for Chinese TTS audio.

Detects syllable onset times from WAV audio using RMS energy analysis.
Each Chinese character corresponds to one syllable, so detected boundaries
can be matched to characters for more accurate lip-sync timing than the
uniform-distribution fallback.

ponytail: simple energy-based onset detection. No ML, no new deps.
          Falls back to uniform distribution when detection confidence is low.
"""

import numpy as np
import struct
import logging

logger = logging.getLogger("syllable_detector")


def detect_syllable_onsets(
    wav_bytes: bytes,
    sample_rate: int = 24000,
    frame_ms: float = 10.0,
    min_syllable_ms: float = 60.0,
    prominence: float = 0.15,
) -> list[float]:
    """
    Detect syllable onset times from WAV audio using valley detection.

    Edge-TTS produces smooth speech without clear silence between syllables,
    so a simple energy threshold doesn't work. Instead, find local energy
    minima (valleys) between peaks — these correspond to syllable boundaries.

    Algorithm:
    1. Compute smoothed RMS energy envelope
    2. Find peaks (local maxima) → each peak ≈ one syllable nucleus
    3. Valleys between peaks → syllable boundaries
    4. The point where energy starts rising after a valley → syllable onset

    Args:
        wav_bytes: WAV audio bytes (16-bit PCM)
        sample_rate: audio sample rate
        frame_ms: analysis frame length in ms
        min_syllable_ms: minimum gap between syllable onsets
        prominence: minimum peak-to-valley drop for a valid boundary

    Returns:
        List of onset times in milliseconds, sorted ascending.
    """
    if not wav_bytes:
        return []

    try:
        audio = _decode_wav_pcm(wav_bytes, sample_rate)
    except Exception as e:
        logger.warning(f"Failed to decode WAV: {e}")
        return []

    if len(audio) < sample_rate * 0.05:
        return []

    peak = np.abs(audio).max()
    if peak > 0:
        audio = audio / peak

    frame_len = int(sample_rate * frame_ms / 1000)
    if frame_len < 1:
        frame_len = 1

    n_frames = len(audio) // frame_len
    if n_frames < 3:
        return []

    # RMS energy per frame
    energy = np.zeros(n_frames, dtype=np.float32)
    for i in range(n_frames):
        seg = audio[i * frame_len:(i + 1) * frame_len]
        energy[i] = np.sqrt(np.mean(seg * seg))

    # Smooth with wider window (50ms) to remove micro-fluctuations
    win = max(3, int(50 / frame_ms))
    if win % 2 == 0:
        win += 1  # odd window
    kernel = np.ones(win) / win
    smoothed = np.convolve(energy, kernel, mode='same')

    # ponytail: find peaks and valleys with wider ±3 frame context
    ctx = 3
    peaks: list[int] = []
    valleys: list[int] = []

    for i in range(ctx, len(smoothed) - ctx):
        left = smoothed[i-ctx:i]
        right = smoothed[i+1:i+ctx+1]
        mid = smoothed[i]

        # Peak: higher than neighbors on both sides
        if mid > left.max() and mid > right.max():
            peaks.append(i)
        # Valley: lower than neighbors on both sides
        elif mid < left.min() and mid < right.min():
            valleys.append(i)

    if not valleys:
        return []

    # Convert valleys to onset times, filtering by prominence
    onsets: list[float] = []
    min_frames = max(1, int(min_syllable_ms / frame_ms))

    for v in valleys:
        # Find nearest peak after this valley
        next_peaks = [p for p in peaks if p > v]
        prev_peaks = [p for p in peaks if p < v]

        if not next_peaks or not prev_peaks:
            continue

        peak_before = smoothed[prev_peaks[-1]]
        valley_val = smoothed[v]
        peak_after = smoothed[next_peaks[0]]

        # Check prominence: valley should be significantly lower than peaks
        drop = min(peak_before - valley_val, peak_after - valley_val)
        if drop < prominence:
            continue

        # Onset = frame where energy starts rising after valley
        onset_frame = v
        for j in range(v + 1, min(v + 8, len(smoothed))):
            if smoothed[j] > smoothed[j - 1]:
                onset_frame = j
                break

        onset_ms = onset_frame * frame_ms

        # Enforce minimum gap
        if onsets and onset_ms - onsets[-1] < min_syllable_ms:
            continue

        onsets.append(onset_ms)

    # ponytail: if too few onsets found, retry with lower prominence
    if len(onsets) < 3 and prominence > 0.05:
        return detect_syllable_onsets(
            wav_bytes, sample_rate, frame_ms, min_syllable_ms,
            prominence=prominence * 0.5,
        )

    logger.debug(
        f"Syllable: {len(onsets)} onsets from {len(valleys)} valleys, "
        f"{len(peaks)} peaks, audio={len(audio)/sample_rate:.1f}s"
    )
    return onsets


def align_characters_to_onsets(
    chars: list[str],
    onsets_ms: list[float],
    total_duration_ms: float,
    fallback: str = "uniform",
) -> list[tuple[str, float, float]]:
    """
    Align characters to detected syllable onsets.

    Strategy: use onsets as anchor points. Characters between anchors
    are uniformly distributed in proportion to their count. This works
    even when onset count doesn't match char count exactly.

    Args:
        chars: list of Chinese characters
        onsets_ms: detected syllable onset times (ms)
        total_duration_ms: total audio duration (ms)
        fallback: "uniform" or "none"

    Returns:
        List of (char, start_ms, end_ms) tuples.
    """
    if not chars:
        return []

    n_chars = len(chars)
    n_onsets = len(onsets_ms)

    # Need at least 2 onsets to form intervals
    if n_onsets < 2:
        return _uniform_distribution(chars, total_duration_ms)

    # Normalize onsets to [0, 1] scale
    onset_arr = np.array(onsets_ms, dtype=np.float64)
    if onset_arr[-1] <= 0:
        return _uniform_distribution(chars, total_duration_ms)
    onset_norm = onset_arr / onset_arr[-1]

    # Distribute chars across onset intervals proportionally
    # Each onset interval gets chars proportional to its time fraction
    intervals = [(0.0, onset_norm[0])]
    for i in range(n_onsets - 1):
        intervals.append((onset_norm[i], onset_norm[i + 1]))
    intervals.append((onset_norm[-1], 1.0))

    # Merge very short intervals (< 0.03) with neighbors
    merged = [intervals[0]]
    for lo, hi in intervals[1:]:
        if hi - lo < 0.03 and merged:
            merged[-1] = (merged[-1][0], hi)
        else:
            merged.append((lo, hi))

    intervals = merged
    n_intervals = len(intervals)

    # Assign char counts to intervals (proportional to duration)
    interval_durs = np.array([hi - lo for lo, hi in intervals])
    char_counts_raw = (interval_durs / interval_durs.sum()) * n_chars
    char_counts = np.round(char_counts_raw).astype(int)

    # Adjust to match total
    diff = n_chars - char_counts.sum()
    # Add/remove from largest intervals
    order = np.argsort(-char_counts)
    for i in range(abs(diff)):
        idx = order[i % len(order)]
        if diff > 0:
            char_counts[idx] += 1
        elif char_counts[idx] > 0:
            char_counts[idx] -= 1

    # Build result
    result: list[tuple[str, float, float]] = []
    char_idx = 0

    for intv_idx, (lo_norm, hi_norm) in enumerate(intervals):
        count = int(char_counts[intv_idx])
        if count <= 0 or char_idx >= n_chars:
            continue

        lo_ms = lo_norm * total_duration_ms
        hi_ms = hi_norm * total_duration_ms
        seg_dur = hi_ms - lo_ms

        for j in range(count):
            if char_idx >= n_chars:
                break
            c = chars[char_idx]
            local_frac = j / max(1, count)
            next_frac = (j + 0.85) / max(1, count)
            start_ms = lo_ms + local_frac * seg_dur
            end_ms = lo_ms + next_frac * seg_dur
            result.append((c, round(start_ms, 1), round(end_ms, 1)))
            char_idx += 1

    # Assign any remaining chars
    while char_idx < n_chars:
        # Append after last interval
        last_end = result[-1][2] if result else 0.0
        dur = total_duration_ms / n_chars
        c = chars[char_idx]
        result.append((c, round(last_end, 1), round(last_end + dur * 0.85, 1)))
        char_idx += 1

    return result


def _uniform_distribution(
    chars: list[str], total_duration_ms: float
) -> list[tuple[str, float, float]]:
    """Fallback: uniform character distribution. 15% gap between chars."""
    if not chars:
        return []
    char_dur = total_duration_ms / len(chars)
    return [
        (c, round(i * char_dur, 1), round((i + 0.85) * char_dur, 1))
        for i, c in enumerate(chars)
    ]


def _merge_close_onsets(onsets: list[float], min_gap_ms: float) -> list[float]:
    """Merge onsets that are too close together."""
    if not onsets:
        return []
    merged = [onsets[0]]
    for t in onsets[1:]:
        if t - merged[-1] < min_gap_ms:
            # Merge: keep the earlier one
            continue
        merged.append(t)
    return merged


def _decode_wav_pcm(wav_bytes: bytes, expected_rate: int) -> np.ndarray:
    """
    Decode WAV bytes to float32 numpy array.

    Handles standard WAV headers. Falls back to raw 16-bit PCM if header
    is missing or malformed.
    """
    # Parse WAV header — start chunk scan from offset 12 (right after RIFF/WAVE)
    if wav_bytes[:4] == b'RIFF' and len(wav_bytes) > 44:
        actual_rate = struct.unpack_from('<I', wav_bytes, 24)[0]
        bits = struct.unpack_from('<H', wav_bytes, 34)[0]

        # Walk RIFF chunks to find 'data', starting from offset 12
        data_offset = 12
        found_data = False
        while data_offset + 8 <= len(wav_bytes):
            chunk_id = wav_bytes[data_offset:data_offset + 4]
            chunk_size = struct.unpack_from('<I', wav_bytes, data_offset + 4)[0]
            if chunk_id == b'data':
                data_offset += 8  # skip 'data' + size fields
                found_data = True
                break
            data_offset += 8 + chunk_size

        if not found_data:
            # Fallback: standard layout with no extra chunks
            data_offset = 44

        pcm = wav_bytes[data_offset:]
        dtype = np.int16 if bits == 16 else np.int32

        audio = np.frombuffer(pcm, dtype=dtype).astype(np.float32)
        audio /= (32768.0 if bits == 16 else 2147483648.0)

        # Resample if needed
        if actual_rate != expected_rate:
            ratio = expected_rate / actual_rate
            indices = np.arange(0, len(audio), ratio).astype(np.int32)
            indices = indices[indices < len(audio)]
            audio = audio[indices]

        return audio

    # Fallback: raw 16-bit PCM
    audio = np.frombuffer(wav_bytes, dtype=np.int16).astype(np.float32)
    audio /= 32768.0
    return audio
