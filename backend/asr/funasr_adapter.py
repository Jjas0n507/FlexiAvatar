"""
FunASR SenseVoice 适配器。

基于阿里 FunAudioLLM SenseVoiceSmall 模型：
- 一模型同时完成 ASR + 语音情绪识别 (SER)
- 非自回归架构，极快推理 (~70ms/10s audio)
- 输出 rich text 格式: "<|HAPPY|>今天天气真好"

参考: https://github.com/FunAudioLLM/SenseVoice
"""

import logging
import re

import numpy as np

from backend.asr.base import BaseASR, ASRResult

logger = logging.getLogger("asr.funasr")

# SenseVoice 情绪标签 → 内部 emotion 名映射
_EMOTION_TAG_MAP: dict[str, str] = {
    "HAPPY": "happy",
    "ANGRY": "angry",
    "SAD": "sad",
    "NEUTRAL": "neutral",
    "FEARFUL": "fearful",
    "DISGUSTED": "disgusted",
    "SURPRISED": "surprised",
}

# 音频事件标签（非情绪，可记录但忽略）
_AUDIO_EVENT_TAGS: frozenset = frozenset({
    "BGM", "APPLAUSE", "LAUGHTER", "CRY", "COUGH", "SNEEZE",
})

# 匹配所有 SenseVoice rich text 标签: <|TAG|>
_TAG_PATTERN = re.compile(r"<\|([^|]+)\|>")

# 情绪标签集合（大写形式）
_EMOTION_TAGS = frozenset(_EMOTION_TAG_MAP.keys())


def _parse_emotion(raw_text: str) -> tuple[str, float]:
    """
    从 SenseVoice rich text 中提取情绪。

    Args:
        raw_text: 如 "<|HAPPY|>今天天气真好" 或 "你好"

    Returns:
        (emotion_name, confidence)
        emotion_name: "happy"/"angry"/"sad"/"neutral" 等
        confidence: 0.0 ~ 1.0，存在情绪标签时固定 1.0（SenseVoice 不输出置信度）
    """
    matches = _TAG_PATTERN.findall(raw_text)
    for tag in matches:
        upper = tag.upper()
        if upper in _EMOTION_TAGS:
            emotion = _EMOTION_TAG_MAP[upper]
            return emotion, 1.0
    return "neutral", 0.0


def _clean_text(raw_text: str) -> str:
    """
    去除 SenseVoice rich text 中的所有 <|TAG|> 标签，返回纯文本。

    Args:
        raw_text: 如 "<|HAPPY|>你好<|BGM|>"

    Returns:
        纯文本: "你好"
    """
    return _TAG_PATTERN.sub("", raw_text).strip()


def _parse_audio_events(raw_text: str) -> list[str]:
    """
    提取音频事件标签（非情绪），如 BGM, APPLAUSE 等。

    Args:
        raw_text: 带标签的原始文本

    Returns:
        事件名列表（小写）: ["bgm", "applause"]
    """
    events = []
    matches = _TAG_PATTERN.findall(raw_text)
    for tag in matches:
        upper = tag.upper()
        if upper in _AUDIO_EVENT_TAGS:
            events.append(upper.lower())
    return events


class FunASRAdapter(BaseASR):
    """
    FunASR SenseVoice 适配器。

    一模型同时完成 ASR 转录 + 语音情绪识别 (SER)。

    用法:
        asr = FunASRAdapter(model="iic/SenseVoiceSmall", device="cpu")
        await asr.warmup()
        result = await asr.transcribe(audio_array)
        # result.text → "今天天气真好"
        # result.emotion → "happy"
    """

    def __init__(
        self,
        model: str = "iic/SenseVoiceSmall",
        device: str = "cpu",
        language: str = "auto",
    ):
        """
        Args:
            model: ModelScope 模型名，默认 "iic/SenseVoiceSmall"
            device: "cpu" | "cuda:0" | "cuda:1" ...
            language: "auto" | "zh" | "en" | "ja" | "ko" 等
        """
        self._model_name = model
        self._device = device
        self._language = language
        self._model = None
        self._model_loaded = False

    async def _ensure_model(self):
        """懒加载模型"""
        if self._model_loaded:
            return
        from funasr import AutoModel

        logger.info(f"Loading FunASR model: {self._model_name} on {self._device}")
        self._model = AutoModel(
            model=self._model_name,
            device=self._device,
            disable_update=True,  # 禁止运行时检查更新
        )
        self._model_loaded = True
        logger.info("FunASR model loaded successfully")

    async def warmup(self) -> None:
        """预热模型：用 1 秒静音音频推理一次"""
        await self._ensure_model()
        dummy = np.zeros(16000, dtype=np.float32)
        _ = await self.transcribe(dummy)
        logger.info("FunASR warmup complete")

    async def transcribe(self, audio: np.ndarray) -> ASRResult:
        """
        将语音转写为文本，同时识别情绪。

        Args:
            audio: float32 numpy array, 16kHz mono

        Returns:
            ASRResult 包含 text, emotion, emotion_confidence
        """
        await self._ensure_model()

        audio = np.asarray(audio, dtype=np.float32)

        # 简单静音检测: 过短的音频直接返回空
        if len(audio) < 160:  # < 10ms
            return ASRResult(
                text="", confidence=0.0, is_final=True,
                language=self._language, emotion="neutral", emotion_confidence=0.0,
            )

        # SenseVoice.generate() 返回 list[dict]，每个 dict 有 key, text 等字段
        try:
            results = self._model.generate(
                input=audio,
                language=self._language,
                ban_emo_unk=True,   # 不输出 <unk> 情绪标签
                use_itn=True,       # 逆文本正则化 (ITN)
                disable_pbar=True,  # 禁用进度条
            )
        except Exception as e:
            logger.error(f"FunASR inference error: {e}")
            return ASRResult(
                text="", confidence=0.0, is_final=True,
                language=self._language, emotion="neutral", emotion_confidence=0.0,
            )

        if not results or len(results) == 0:
            return ASRResult(
                text="", confidence=0.0, is_final=True,
                language=self._language, emotion="neutral", emotion_confidence=0.0,
            )

        # 取第一个结果（单段音频只有一个结果）
        first = results[0]
        raw_text = first.get("text", "").strip()

        if not raw_text:
            return ASRResult(
                text="", confidence=0.0, is_final=True,
                language=self._language, emotion="neutral", emotion_confidence=0.0,
            )

        # 解析情绪和纯文本
        emotion, emotion_conf = _parse_emotion(raw_text)
        clean_text = _clean_text(raw_text)

        # 没有实质文本内容时返回空
        if not clean_text:
            return ASRResult(
                text="", confidence=0.0, is_final=True,
                language=self._language, emotion=emotion, emotion_confidence=emotion_conf,
            )

        # SenseVoice 不提供传统置信度，使用一个固定值表示成功识别
        confidence = 0.9

        # 记录音频事件（如有）
        audio_events = _parse_audio_events(raw_text)
        if audio_events:
            logger.debug(f"FunASR audio events detected: {audio_events}")

        return ASRResult(
            text=clean_text,
            confidence=confidence,
            is_final=True,
            language=self._language,
            emotion=emotion,
            emotion_confidence=emotion_conf,
        )

    @classmethod
    def get_info(cls) -> dict:
        return {
            "name": "FunASRSenseVoice",
            "version": "1.0",
            "backend": "FunASR (ModelScope)",
            "models": ["iic/SenseVoiceSmall"],
            "features": ["emotion_recognition", "audio_event_detection"],
        }
