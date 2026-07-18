"""
Edge-TTS 适配器。

使用 Microsoft Edge 的免费 TTS 服务（零 GPU 备选引擎）。
输出 24kHz 48kbps CBR MP3 原始字节，前端 decodeAudioData 直接解码。
"""

import logging

import edge_tts

from backend.tts.base import BaseTTS, TTSResult

logger = logging.getLogger("tts")

_ZH_VOICES = [
    {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓 (女)", "language": "zh-CN"},
    {"id": "zh-CN-YunxiNeural", "name": "云希 (男)", "language": "zh-CN"},
    {"id": "zh-CN-XiaoyiNeural", "name": "晓伊 (女)", "language": "zh-CN"},
    {"id": "zh-CN-YunjianNeural", "name": "云健 (男)", "language": "zh-CN"},
    {"id": "zh-CN-XiaochenNeural", "name": "晓辰 (女)", "language": "zh-CN"},
]

# Edge-TTS 默认输出 audio-24khz-48kbitrate-mono-mp3 (CBR)
# duration_ms = bytes * 8 bit / 48 kbps = bytes / 6
_MP3_BYTES_PER_MS = 6


class EdgeTTSAdapter(BaseTTS):
    """Edge-TTS 适配器"""

    def __init__(
        self,
        voice: str = "zh-CN-XiaoxiaoNeural",
        speed: str = "+10%",
        pitch: str = "+0Hz",
    ):
        self._voice = voice
        self._speed = speed
        self._pitch = pitch

    async def synthesize(self, text: str) -> TTSResult:
        if not text.strip():
            return TTSResult(audio_bytes=b"", text=text)

        communicate = edge_tts.Communicate(
            text=text,
            voice=self._voice,
            rate=self._speed,
            pitch=self._pitch,
        )

        audio_chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])

        mp3 = b"".join(audio_chunks)
        return TTSResult(
            audio_bytes=mp3,
            format="mp3",
            duration_ms=len(mp3) / _MP3_BYTES_PER_MS,
            text=text,
        )

    async def voices(self) -> list[dict]:
        return _ZH_VOICES
