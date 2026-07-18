"""
TTS (Text-to-Speech) 抽象基类。

所有 TTS 实现必须继承此基类。
输出为原始音频字节（mp3/wav），口型由前端 RMS 音量驱动，不需要时间戳。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TTSResult:
    """TTS 合成结果"""
    audio_bytes: bytes           # 原始音频数据（format 指定编码）
    format: str = "mp3"          # "mp3" | "wav" — 适配器输出什么就传什么
    duration_ms: float = 0.0     # 时长估算，仅用于后端超时兜底
    text: str = ""               # 原始文本


class BaseTTS(ABC):
    """
    TTS 抽象基类。

    输入: 文本字符串
    输出: TTSResult (音频字节 + 时长估算)
    """

    @abstractmethod
    async def synthesize(self, text: str) -> TTSResult:
        """将文本合成为语音。"""
        ...

    @abstractmethod
    async def voices(self) -> list[dict]:
        """
        获取可用的声音列表。

        Returns:
            [{"id": "voice-id", "name": "声音名称", "language": "zh-CN"}, ...]
        """
        ...
