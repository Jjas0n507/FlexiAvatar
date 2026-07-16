"""
ASR (Automatic Speech Recognition) 抽象基类。

所有 ASR 实现必须继承此基类。
支持 FunASR、Whisper、Sherpa-ONNX 等，通过配置切换。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class ASRResult:
    """ASR 识别结果"""
    text: str                # 识别的文本
    confidence: float        # 置信度 0.0 ~ 1.0
    is_final: bool = True    # 是否是最终结果 (流式识别的中间结果时为 False)
    language: str = "zh"     # 识别语言
    emotion: str = "neutral"           # 语音情绪: happy/angry/sad/neutral/surprised/fearful/disgusted
    emotion_confidence: float = 0.0    # 情绪识别置信度 0.0 ~ 1.0


class BaseASR(ABC):
    """
    ASR 抽象基类。

    输入: 16kHz, mono PCM 音频数据 (numpy array)
    输出: ASRResult (文本 + 置信度)
    """

    @abstractmethod
    async def transcribe(self, audio: "np.ndarray") -> ASRResult:
        """
        将一段语音转写为文本。

        Args:
            audio: numpy array, shape=(N,), dtype=float32, 16kHz mono

        Returns:
            ASRResult 包含识别文本和置信度
        """
        ...

    async def stream_transcribe(self, audio: "np.ndarray") -> AsyncIterator[ASRResult]:
        """
        流式转写语音为文本 (async generator)。

        每识别出一个片段就 yield 一个 ASRResult (is_final=False)。
        最后 yield 完整文本 (is_final=True)。

        默认实现：直接调用 transcribe() 一次返回完整结果。
        子类覆盖此方法可获得真正的流式输出。
        """
        result = await self.transcribe(audio)
        yield result

    @abstractmethod
    async def warmup(self) -> None:
        """预热模型（首次加载可能较慢）"""
        ...

    @classmethod
    def get_info(cls) -> dict:
        """返回 ASR 实现的信息"""
        return {
            "name": cls.__name__,
            "version": "unknown",
        }
