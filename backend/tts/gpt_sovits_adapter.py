"""
GPT-SoVITS 适配器（零样本克隆 / 微调权重双模式）。

零样本: 基座预训练权重 + 参考音频 → 克隆任意音色（类似 CosyVoice2）。
微调:   LoRA/全参微调权重 → 专属角色音色（社区 RVC 级效果，TTS 原生）。

依赖安装（不随默认镜像，见 Dockerfile）:
    git clone https://github.com/RVC-Boss/GPT-SoVITS /opt/GPT-SoVITS
    pip install -r /opt/GPT-SoVITS/requirements.txt
    # 基座预训练权重首次运行时自动从 ModelScope 下载。

换音色 = 换 ref_audio + ref_text（零样本）或换 gpt_weights + sovits_weights（微调）。
"""

import asyncio
import io
import logging
import os
import sys
import wave
from pathlib import Path

from backend.tts.base import BaseTTS, TTSResult

logger = logging.getLogger("tts")

_GPT_SOVITS_DEFAULT_ROOT = "/opt/GPT-SoVITS"

_INSTALL_HINT = (
    "GPT-SoVITS 未安装。安装方法:\n"
    "  git clone https://github.com/RVC-Boss/GPT-SoVITS /opt/GPT-SoVITS\n"
    "  pip install -r /opt/GPT-SoVITS/requirements.txt\n"
    "或将 config tts.engine 改回 edge-tts / cosyvoice2。"
)

# 基座预训练权重（零样本克隆必需）—— ModelScope 自动下载
_PRETRAINED_REPO = "iic/GPT-SoVITS"
_PRETRAINED_FILES = {
    "gpt": "gsv-v2final-pretrained/s1bert25hz-2kh-longer-epoch=68e-step=50232.ckpt",
    "sovits": "gsv-v2final-pretrained/s2G488k.pth",
}


class GptSovitsAdapter(BaseTTS):
    """GPT-SoVITS 适配器 — 零样本 + 微调双模式"""

    def __init__(
        self,
        pretrained_dir: str = "resources/models/GPT-SoVITS",
        ref_audio: str = "resources/voices/ref.wav",
        ref_text: str = "",
        ref_language: str = "zh",
        gpt_weights: str = "",       # 空 = 用预训练基座（零样本模式）
        sovits_weights: str = "",    # 空 = 用预训练基座（零样本模式）
        device: str = "cpu",
        is_half: bool = False,
        speed: float = 1.0,
        root: str = "",              # GPT-SoVITS 安装路径，空 = /opt/GPT-SoVITS
    ):
        self._pretrained_dir = pretrained_dir
        self._ref_audio = ref_audio
        self._ref_text = ref_text
        self._ref_language = ref_language
        self._gpt_weights = gpt_weights
        self._sovits_weights = sovits_weights
        self._device = device
        self._is_half = is_half
        self._speed = speed
        self._root = root or _GPT_SOVITS_DEFAULT_ROOT
        self._pkg_path = os.path.join(self._root, "GPT_SoVITS")

        self._loaded = False
        self._load_lock = asyncio.Lock()
        # ponytail: 推理串行锁 — GPT-SoVITS 模型非并发安全
        self._infer_lock = asyncio.Lock()

    # ── 懒加载 ──────────────────────────────────

    async def _ensure_loaded(self):
        if self._loaded:
            return
        async with self._load_lock:
            if self._loaded:
                return
            await asyncio.to_thread(self._load_blocking)

    def _load_blocking(self):
        if self._pkg_path not in sys.path:
            sys.path.insert(0, self._pkg_path)

        try:
            from inference_webui import change_gpt_weights, change_sovits_weights  # noqa: F401
        except ImportError as e:
            raise RuntimeError(_INSTALL_HINT) from e

        # 下载 / 定位基座预训练权重
        gpt_path = self._gpt_weights or self._ensure_pretrained("gpt")
        sovits_path = self._sovits_weights or self._ensure_pretrained("sovits")

        if not Path(gpt_path).exists():
            raise RuntimeError(f"GPT 权重不存在: {gpt_path}")
        if not Path(sovits_path).exists():
            raise RuntimeError(f"SoVITS 权重不存在: {sovits_path}")
        if not Path(self._ref_audio).exists():
            raise RuntimeError(f"参考音频不存在: {self._ref_audio}")

        logger.info("Loading GPT-SoVITS models...")
        # 函数内部有全局状态；加载后 get_tts_wav 直接可用
        change_gpt_weights(gpt_path=str(gpt_path))
        change_sovits_weights(sovits_path=str(sovits_path))
        self._loaded = True
        logger.info("GPT-SoVITS ready")

        # 热身
        import time
        t0 = time.time()
        list(self._synthesize_raw("预热。"))
        logger.info(f"GPT-SoVITS warmup: {time.time() - t0:.1f}s")

    def _ensure_pretrained(self, key: str) -> str:
        """确保预训练基座权重存在，返回本地路径。"""
        local = Path(self._pretrained_dir) / _PRETRAINED_FILES[key]
        if local.exists():
            return str(local)

        logger.info(f"Downloading GPT-SoVITS pretrained models to {self._pretrained_dir}...")
        from modelscope import snapshot_download
        snapshot_download(_PRETRAINED_REPO, local_dir=str(Path(self._pretrained_dir)))
        if not local.exists():
            raise RuntimeError(f"预训练权重下载后仍不存在: {local}")
        return str(local)

    # ── 合成 ────────────────────────────────────

    async def synthesize(self, text: str) -> TTSResult:
        if not text.strip():
            return TTSResult(audio_bytes=b"", format="wav", text=text)
        await self._ensure_loaded()
        async with self._infer_lock:
            return await asyncio.to_thread(self._synthesize_blocking, text)

    def _synthesize_blocking(self, text: str) -> TTSResult:
        import numpy as np

        chunks = list(self._synthesize_raw(text))
        if not chunks:
            return TTSResult(audio_bytes=b"", format="wav", text=text)

        sr, audio = chunks[-1]  # 取最后一段（完整输出）
        if isinstance(audio, np.ndarray):
            pcm = (audio * 32767).astype(np.int16)
        else:
            pcm = audio

        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm.tobytes() if pcm.dtype == np.int16 else pcm.astype(np.int16).tobytes())

        return TTSResult(
            audio_bytes=buf.getvalue(),
            format="wav",
            duration_ms=len(pcm) / sr * 1000.0,
            text=text,
        )

    def _synthesize_raw(self, text: str):
        """调用 GPT-SoVITS 推理，返回 generator of (sr, audio_array)。"""
        from inference_webui import get_tts_wav

        return get_tts_wav(
            ref_wav_path=self._ref_audio,
            prompt_text=self._ref_text,
            prompt_language=self._ref_language,
            text=text,
            text_language="zh",          # 输出语言，后续可从 config 控制
            how_to_cut="不切",            # pipeline 已分句，这里不再切
            top_p=1.0,
            temperature=1.0,
            speed=self._speed,
        )

    async def voices(self) -> list[dict]:
        name = "微调模型" if self._gpt_weights else f"零样本克隆 ({Path(self._ref_audio).stem})"
        return [{"id": self._ref_audio, "name": name, "language": "zh"}]
