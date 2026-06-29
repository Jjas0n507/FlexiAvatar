"""
Silero VAD 适配器。

基于 Silero VAD V5+ (ONNX) 实现语音活动检测。
帧大小: 512 samples (32ms @ 16kHz) — 这是 Silero VAD 的要求。
"""

import time
import numpy as np
import torch

from backend.vad.base import BaseVAD, VADResult, VADEventType


class SileroVAD(BaseVAD):
    """Silero VAD 适配器"""

    FRAME_SIZE = 512          # Silero VAD 在 16kHz 要求精确 512 samples
    FRAME_DURATION_MS = 32    # 512/16000 = 32ms
    HOP_SIZE = 512            # 默认不重叠

    def __init__(
        self,
        threshold: float = 0.5,
        speech_start_frames: int = 4,    # 4 帧 ≈ 128ms → 开始说话
        silence_end_frames: int = 12,    # 12 帧 ≈ 384ms → 说话结束
        interrupt_frames: int = 3,        # 3 帧 ≈ 96ms → 打断检测
        sample_rate: int = 16000,
    ):
        from silero_vad import load_silero_vad

        self._threshold = threshold
        self._speech_start_frames = speech_start_frames
        self._silence_end_frames = silence_end_frames
        self._interrupt_frames = interrupt_frames
        self._sample_rate = sample_rate

        self._model = load_silero_vad(onnx=True)

        # 内部状态
        self._speech_frame_count = 0
        self._silence_frame_count = 0
        self._is_speaking = False
        self._speech_buffer: list[np.ndarray] = []
        self._total_frames = 0

    # ── 核心方法 ──────────────────────────────────

    def _to_tensor(self, audio: np.ndarray) -> torch.Tensor:
        """将 numpy array 转为 torch float32 tensor"""
        if isinstance(audio, torch.Tensor):
            return audio.float()
        return torch.from_numpy(np.asarray(audio, dtype=np.float32))

    def process_frame(self, audio_frame: np.ndarray) -> VADResult:
        """
        处理一帧音频 (512 samples, 16kHz)。

        Args:
            audio_frame: (512,) float32 or numpy array

        Returns:
            VADResult with event type
        """
        self._total_frames += 1
        timestamp = time.time()

        tensor = self._to_tensor(audio_frame)
        speech_prob = self._model(tensor, self._sample_rate).item()

        is_speech = speech_prob >= self._threshold

        if is_speech:
            self._speech_frame_count += 1
            self._silence_frame_count = 0
            self._speech_buffer.append(
                audio_frame.copy() if isinstance(audio_frame, np.ndarray)
                else np.array(audio_frame)
            )
        else:
            self._silence_frame_count += 1
            self._speech_frame_count = 0

        # ── 状态判定 ──────────────────────────────

        if not self._is_speaking and self._speech_frame_count >= self._speech_start_frames:
            self._is_speaking = True
            # 保留起始的几帧作为语音段开头
            keep = min(len(self._speech_buffer), self._speech_start_frames)
            self._speech_buffer = self._speech_buffer[-keep:] if keep > 0 else []
            return VADResult(
                event=VADEventType.SPEECH_START,
                speech_prob=speech_prob,
                frame_duration_ms=self.FRAME_DURATION_MS,
                timestamp=timestamp,
            )

        if self._is_speaking:
            if self._silence_frame_count >= self._silence_end_frames:
                self._is_speaking = False
                self._speech_frame_count = 0
                self._silence_frame_count = 0
                return VADResult(
                    event=VADEventType.SPEECH_END,
                    speech_prob=speech_prob,
                    frame_duration_ms=self.FRAME_DURATION_MS,
                    timestamp=timestamp,
                )
            else:
                return VADResult(
                    event=VADEventType.SPEECH_CONTINUE,
                    speech_prob=speech_prob,
                    frame_duration_ms=self.FRAME_DURATION_MS,
                    timestamp=timestamp,
                )

        return VADResult(
            event=VADEventType.SILENCE,
            speech_prob=speech_prob,
            frame_duration_ms=self.FRAME_DURATION_MS,
            timestamp=timestamp,
        )

    def should_interrupt(self, audio_frame: np.ndarray) -> bool:
        """
        打断检测 — 用更短的确认帧数快速响应。
        在 SPEAKING 状态下调用。

        Returns:
            True 如果检测到用户开始说话
        """
        tensor = self._to_tensor(audio_frame)
        speech_prob = self._model(tensor, self._sample_rate).item()

        if speech_prob >= self._threshold:
            self._speech_frame_count += 1
            self._silence_frame_count = 0
        else:
            self._silence_frame_count += 1

        if self._speech_frame_count >= self._interrupt_frames:
            self._speech_frame_count = 0
            self._silence_frame_count = 0
            return True

        if self._silence_frame_count > self._interrupt_frames * 2:
            self._speech_frame_count = 0

        return False

    def reset(self) -> None:
        """重置内部状态，新对话开始前调用"""
        self._speech_frame_count = 0
        self._silence_frame_count = 0
        self._is_speaking = False
        self._speech_buffer.clear()
        self._total_frames = 0

    # ── 工具方法 ──────────────────────────────────

    @staticmethod
    def load_wav(path: str, target_sr: int = 16000) -> np.ndarray:
        """加载 WAV 文件为 float32 mono numpy array"""
        import wave
        with wave.open(path, "rb") as wf:
            n_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            framerate = wf.getframerate()
            n_frames = wf.getnframes()
            raw = wf.readframes(n_frames)

        if sample_width == 2:
            data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        elif sample_width == 4:
            data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
        else:
            raise ValueError(f"Unsupported sample width: {sample_width}")

        if n_channels > 1:
            data = data.reshape(-1, n_channels).mean(axis=1)

        if framerate != target_sr:
            ratio = target_sr / framerate
            new_len = int(len(data) * ratio)
            indices = np.linspace(0, len(data) - 1, new_len)
            data = np.interp(indices, np.arange(len(data)), data)

        return data.astype(np.float32)

    @staticmethod
    def frame_generator(audio: np.ndarray, frame_size: int = 512):
        """滑动窗口帧生成器"""
        for i in range(0, len(audio) - frame_size + 1, frame_size):
            yield audio[i:i + frame_size]

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking
