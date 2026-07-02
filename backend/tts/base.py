"""
TTS (Text-to-Speech) 抽象基类。

所有 TTS 实现必须继承此基类。
关键输出: 音频数据 + 音素时间线 (用于驱动 Live2D 嘴型同步)。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class Phoneme:
    """单个音素的时间戳信息"""
    phoneme: str              # 音素符号 (A, I, U, E, O, N 或 IPA)
    start_ms: float           # 起始时间 (ms)
    end_ms: float             # 结束时间 (ms)


@dataclass
class TTSResult:
    """TTS 合成结果"""
    audio_bytes: bytes                   # 音频数据 (WAV 格式)
    sample_rate: int = 24000             # 采样率
    phonemes: list[Phoneme] = field(default_factory=list)  # 音素时间线
    duration_ms: float = 0.0             # 音频总时长 (ms)
    text: str = ""                       # 原始文本


class BaseTTS(ABC):
    """
    TTS 抽象基类。

    输入: 文本字符串
    输出: TTSResult (音频 + 音素时间线)
    """

    @abstractmethod
    async def synthesize(self, text: str) -> TTSResult:
        """
        将文本合成为语音。

        Args:
            text: 待合成的文本

        Returns:
            TTSResult 包含音频数据和音素时间线
        """
        ...

    async def stream_synthesize(self, text: str) -> "AsyncIterator[TTSResult]":
        """
        流式合成语音 (async generator)。

        逐步产出 TTSResult 块，让前端可以在全部音频合成完之前就开始播放。
        默认实现：直接调用 synthesize() 一次返回完整结果。
        子类覆盖此方法可获得真正的流式输出（分句合成）。
        """
        result = await self.synthesize(text)
        if result.audio_bytes:
            yield result

    @abstractmethod
    async def voices(self) -> list[dict]:
        """
        获取可用的声音列表。

        Returns:
            [{"id": "voice-id", "name": "声音名称", "language": "zh-CN"}, ...]
        """
        ...

    @classmethod
    def get_info(cls) -> dict:
        """返回 TTS 实现的信息"""
        return {
            "name": cls.__name__,
            "version": "unknown",
        }
