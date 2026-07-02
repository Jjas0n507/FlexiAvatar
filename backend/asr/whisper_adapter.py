"""
Faster-Whisper ASR 适配器。

基于 CTranslate2 的高效 Whisper 推理。
支持多语言，中文识别。
"""

import os
import sys

# Windows 上 MKL 与 LLVM OpenMP 冲突修复 (conda 环境必需)
if sys.platform == "win32":
    os.environ.setdefault("MKL_THREADING_LAYER", "sequential")
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import numpy as np

from backend.asr.base import BaseASR, ASRResult


class WhisperASR(BaseASR):
    """
    Faster-Whisper ASR 适配器。

    用法:
        asr = WhisperASR(model_size="medium", language="zh")
        result = await asr.transcribe(audio_array)
    """

    # 预计算 whisper 期望的 16kHz 重采样比
    WHISPER_SR = 16000

    def __init__(
        self,
        model_size: str = "medium",
        language: str = "zh",
        device: str = "cpu",
        compute_type: str = "int8",
        beam_size: int = 5,
    ):
        from faster_whisper import WhisperModel

        self._model_size = model_size
        self._language = language
        self._device = device
        self._compute_type = compute_type
        self._beam_size = beam_size
        self._model: WhisperModel | None = None
        self._model_loaded = False

    async def _ensure_model(self):
        """懒加载模型"""
        if self._model_loaded:
            return
        from faster_whisper import WhisperModel
        import os

        # 使用 HF 镜像 (中国用户)
        if os.environ.get("HF_ENDPOINT") is None:
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

        model_root = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "resources", "models", "whisper"
        )

        self._model = WhisperModel(
            self._model_size,
            device=self._device,
            compute_type=self._compute_type,
            download_root=model_root,
        )
        self._model_loaded = True

    async def warmup(self) -> None:
        """预加载模型"""
        await self._ensure_model()
        # 推理一个空音频来预热 CUDA 内核 (CPU 上跳过)
        if self._device == "cpu":
            return
        dummy = np.zeros(16000, dtype=np.float32)
        _ = await self.transcribe(dummy)

    async def transcribe(self, audio: np.ndarray) -> ASRResult:
        """
        将语音转写为文本。

        Args:
            audio: float32 numpy array, 16kHz mono

        Returns:
            ASRResult with text and confidence
        """
        await self._ensure_model()

        # 确保是 float32
        audio = np.asarray(audio, dtype=np.float32)

        # 静音剪裁
        audio_trimmed = self._trim_silence(audio)
        if len(audio_trimmed) < 160:  # < 10ms, too short
            return ASRResult(text="", confidence=0.0, is_final=True, language=self._language)

        segments, info = self._model.transcribe(
            audio_trimmed,
            language=self._language,
            beam_size=self._beam_size,
            vad_filter=True,          # 内置 VAD 过滤
            vad_parameters=dict(
                threshold=0.5,
                min_speech_duration_ms=250,
            ),
        )

        # 收集所有分段文本
        texts = []
        total_confidence = 0.0
        count = 0
        for segment in segments:
            text = segment.text.strip()
            if text:
                texts.append(text)
            total_confidence += segment.avg_logprob
            count += 1

        full_text = "".join(texts)
        avg_confidence = (
            float(np.exp(total_confidence / count)) if count > 0 else 0.0
        )

        return ASRResult(
            text=full_text,
            confidence=min(avg_confidence, 1.0),
            is_final=True,
            language=info.language if info else self._language,
        )

    async def stream_transcribe(self, audio: np.ndarray):
        """
        流式转写 — 每识别出一个 segment 就 yield 中间结果。

        这让前端可以在用户说完话之前就看到部分文本。
        最后的结果 yield 时 is_final=True。
        """
        await self._ensure_model()

        audio = np.asarray(audio, dtype=np.float32)
        audio_trimmed = self._trim_silence(audio)
        if len(audio_trimmed) < 160:
            yield ASRResult(text="", confidence=0.0, is_final=True, language=self._language)
            return

        segments_iter, info = self._model.transcribe(
            audio_trimmed,
            language=self._language,
            beam_size=self._beam_size,
            vad_filter=True,
            vad_parameters=dict(
                threshold=0.5,
                min_speech_duration_ms=250,
            ),
        )

        texts = []
        total_confidence = 0.0
        count = 0

        for segment in segments_iter:
            text = segment.text.strip()
            if text:
                texts.append(text)
            total_confidence += segment.avg_logprob
            count += 1

            partial_text = "".join(texts)
            avg_conf = float(np.exp(total_confidence / count)) if count > 0 else 0.0

            yield ASRResult(
                text=partial_text,
                confidence=min(avg_conf, 1.0),
                is_final=False,  # 中间结果
                language=info.language if info else self._language,
            )

        # 最终结果
        full_text = "".join(texts)
        avg_confidence = (
            float(np.exp(total_confidence / count)) if count > 0 else 0.0
        )

        yield ASRResult(
            text=full_text,
            confidence=min(avg_confidence, 1.0),
            is_final=True,
            language=info.language if info else self._language,
        )

    @staticmethod
    def _trim_silence(audio: np.ndarray, threshold: float = 0.01) -> np.ndarray:
        """简单的静音剪裁（移除首尾静音）"""
        abs_audio = np.abs(audio)
        above = abs_audio > threshold
        if not above.any():
            return audio
        start = above.argmax()
        end = len(audio) - above[::-1].argmax()
        return audio[start:end]

    @classmethod
    def get_info(cls) -> dict:
        return {
            "name": "FasterWhisperASR",
            "version": "1.2",
            "backend": "CTranslate2",
            "models": ["tiny", "base", "small", "medium", "large-v3"],
        }
