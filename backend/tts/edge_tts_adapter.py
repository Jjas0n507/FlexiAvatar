"""
Edge-TTS 适配器。

使用 Microsoft Edge 的免费 TTS 服务。
支持:
- 流式合成
- 句子级边界 (SentenceBoundary) 用于 Live2D 口型同步
- 多种中文声音选择

注意: Edge-TTS v7+ 只提供 SentenceBoundary (句子级时间戳)，
不提供 WordBoundary (词级)。口型同步使用均匀分布策略，
后续可通过 GPT-SoVITS 等引擎获得精确音素时间戳。
"""

import asyncio
import io
import logging
import struct
import wave

import edge_tts

from backend.tts.base import BaseTTS, TTSResult, Phoneme
from backend.live2d.mouth_shapes import pinyin_final_to_mouth
from backend.audio.prosody import extract_volume_envelope

logger = logging.getLogger("tts")

_ZH_VOICES = [
    {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓 (女)", "language": "zh-CN"},
    {"id": "zh-CN-YunxiNeural", "name": "云希 (男)", "language": "zh-CN"},
    {"id": "zh-CN-XiaoyiNeural", "name": "晓伊 (女)", "language": "zh-CN"},
    {"id": "zh-CN-YunjianNeural", "name": "云健 (男)", "language": "zh-CN"},
    {"id": "zh-CN-XiaochenNeural", "name": "晓辰 (女)", "language": "zh-CN"},
]


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
            return TTSResult(audio_bytes=b"", phonemes=[], text=text)

        communicate = edge_tts.Communicate(
            text=text,
            voice=self._voice,
            rate=self._speed,
            pitch=self._pitch,
        )

        audio_chunks: list[bytes] = []
        sentence_boundaries: list[dict] = []

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])
            elif chunk["type"] == "SentenceBoundary":
                sentence_boundaries.append({
                    "text": chunk.get("text", ""),
                    "offset": chunk.get("offset", 0),      # 100ns
                    "duration": chunk.get("duration", 0),   # 100ns
                })

        raw_audio = b"".join(audio_chunks)
        wav_bytes, sample_rate, duration_ms = self._mp3_to_wav(raw_audio)
        phonemes = self._boundaries_to_phonemes(
            sentence_boundaries, duration_ms, wav_bytes, sample_rate
        )

        # Phase 1.4: 提取音量包络并注入到 phoneme
        if phonemes and wav_bytes:
            try:
                volumes = extract_volume_envelope(wav_bytes, frame_ms=50.0)
                self._inject_volumes(phonemes, volumes, duration_ms)
            except Exception:
                pass  # 音量提取失败不阻塞 TTS

        return TTSResult(
            audio_bytes=wav_bytes,
            sample_rate=sample_rate,
            phonemes=phonemes,
            duration_ms=duration_ms,
            text=text,
        )

    async def stream_synthesize(self, text: str):
        """
        流式合成: 按句子切分文本，逐句合成并 yield。

        好处: 第一句话的音频在前端开始播放时，后续句子还在合成中。
        这显著降低了"从 LLM 完成到听到声音"的延迟。
        """
        if not text.strip():
            return

        # 按中文标点切分句子
        sentences = self._split_sentences(text)
        if not sentences:
            return

        for i, sentence in enumerate(sentences):
            if not sentence.strip():
                continue
            result = await self.synthesize(sentence)
            if result.audio_bytes:
                yield result

    async def voices(self) -> list[dict]:
        return _ZH_VOICES

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """将文本按中文标点切分为句子，保留标点"""
        import re
        # 在句末标点处切分，保留标点在句子末尾
        parts = re.split(r'(?<=[。！？!?\n])', text)
        # 合并过短的片段
        result = []
        buffer = ""
        for part in parts:
            if not part.strip():
                continue
            buffer += part
            if len(buffer) >= 4 or any(p in buffer for p in '。！？!?\n'):
                result.append(buffer)
                buffer = ""
        if buffer:
            result.append(buffer)
        return result

    # ── 私有 ──────────────────────────────────────

    @staticmethod
    def _inject_volumes(phonemes: list[Phoneme], volumes: list[float], total_duration_ms: float) -> None:
        """
        Phase 1.4: 将 RMS 音量注入到每个 phoneme 的 volume 字段。

        每个 phoneme 取其时间区间内的平均音量。
        """
        if not volumes or total_duration_ms <= 0:
            return

        frame_ms = total_duration_ms / len(volumes)

        for p in phonemes:
            start_idx = max(0, int(p.start_ms / frame_ms))
            end_idx = min(len(volumes), max(start_idx + 1, int(p.end_ms / frame_ms) + 1))
            relevant = volumes[start_idx:end_idx]
            if relevant:
                p.volume = round(sum(relevant) / len(relevant), 4)

    @staticmethod
    def _mp3_to_wav(mp3_data: bytes) -> tuple[bytes, int, float]:
        """将 MP3 字节转为 WAV PCM (24kHz, 16bit, mono)"""
        from pydub import AudioSegment

        # 直接从内存读取，不写临时文件（Windows 文件锁问题）
        audio = AudioSegment.from_file(io.BytesIO(mp3_data), format="mp3")
        sample_rate = audio.frame_rate
        duration_ms = len(audio)

        wav_buf = io.BytesIO()
        audio.export(wav_buf, format="wav")
        return wav_buf.getvalue(), sample_rate, duration_ms

    @staticmethod
    def _boundaries_to_phonemes(
        boundaries: list[dict],
        total_duration_ms: float,
        wav_bytes: bytes = b"",
        sample_rate: int = 24000,
    ) -> list[Phoneme]:
        """
        将 SentenceBoundary 转为口型时间线。

        Edge-TTS v7+ 只提供句子级边界。使用 syllable boundary detection
        从音频波形中检测音节起始点，匹配到每个字符，获得更准的口型时序。
        检测信心低时 fallback 到均匀分布。
        """
        # 1. 收集所有边界中的文字
        all_chars: list[str] = []
        for sb in boundaries:
            text = sb.get("text", "").strip()
            for c in text:
                if c.strip() and '一' <= c <= '鿿':
                    all_chars.append(c)

        if not all_chars:
            return []

        # 2. 尝试音节检测
        aligned = None
        if wav_bytes:
            try:
                from backend.audio.syllable_detector import (
                    detect_syllable_onsets,
                    align_characters_to_onsets,
                )
                onsets = detect_syllable_onsets(wav_bytes, sample_rate)
                aligned = align_characters_to_onsets(
                    all_chars, onsets, total_duration_ms, fallback="uniform"
                )
            except Exception:
                pass  # 音节检测失败时用均匀分布

        if aligned is None:
            aligned = _uniform_char_timing(all_chars, total_duration_ms)

        # 3. 构建 Phoneme 列表
        phonemes = []
        for char, start_ms, end_ms in aligned:
            mouth = EdgeTTSAdapter._char_to_mouth(char)
            phonemes.append(Phoneme(
                phoneme=mouth,
                start_ms=round(start_ms, 1),
                end_ms=round(end_ms, 1),
                char=char,
            ))

        return phonemes

    @staticmethod
    def _char_to_mouth(char: str) -> str:
        """将汉字映射到 Live2D 五口型 (A/I/U/E/O/N)"""
        if not ('一' <= char <= '鿿'):
            return "N"

        try:
            from pypinyin import pinyin, Style
            py_list = pinyin(char, style=Style.FINALS, strict=False)
            if py_list and py_list[0]:
                final = py_list[0][0]
                if final:
                    return pinyin_final_to_mouth(final)
        except ImportError:
            pass

        return "E"  # 默认中等开口


# ── 模块级辅助 ────────────────────────────────────

def _uniform_char_timing(
    chars: list[str], total_duration_ms: float
) -> list[tuple[str, float, float]]:
    """
    ponytail: 均匀分配字符时间（音节检测失败时的 fallback）。
    保留 15% 的间隙作为字符间过渡。
    """
    if not chars:
        return []
    char_dur = total_duration_ms / len(chars)
    return [
        (
            c,
            round(i * char_dur, 1),
            round((i + 0.85) * char_dur, 1),
        )
        for i, c in enumerate(chars)
    ]
