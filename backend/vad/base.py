"""
VAD (Voice Activity Detection) 抽象基类。

所有 VAD 实现必须继承此基类。
替换方案时，只需实现此接口并在配置中切换 engine 即可。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class VADEventType(Enum):
    SPEECH_START = "speech_start"      # 检测到语音开始
    SPEECH_CONTINUE = "speech_continue" # 语音持续中
    SPEECH_END = "speech_end"          # 语音结束 (静音超时)
    SILENCE = "silence"                 # 静音


@dataclass
class VADResult:
    """VAD 单帧检测结果"""
    event: VADEventType
    speech_prob: float       # 语音概率 0.0 ~ 1.0
    frame_duration_ms: int   # 本帧时长 (ms)
    timestamp: float         # Unix 时间戳


class BaseVAD(ABC):
    """
    VAD 抽象基类。

    所有实现必须处理: 16kHz, 16bit, mono PCM 音频帧。
    推荐帧长: 30ms (480 samples)。
    """

    @abstractmethod
    def process_frame(self, audio_frame: "np.ndarray") -> VADResult:
        """
        处理一帧音频数据。

        Args:
            audio_frame: numpy array, shape=(480,), dtype=float32, 范围 [-1, 1]

        Returns:
            VADResult 包含事件类型和语音概率
        """
        ...

    @abstractmethod
    def reset(self) -> None:
        """重置 VAD 的内部状态（新一轮对话开始时调用）"""
        ...

    @classmethod
    def get_info(cls) -> dict:
        """返回 VAD 实现的信息"""
        return {
            "name": cls.__name__,
            "version": "unknown",
        }
