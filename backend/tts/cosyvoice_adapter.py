"""
CosyVoice 2 适配器（本地 TTS，Apache 2.0）。

零样本音色克隆: 3-10s 参考音频 + 逐字文本 → 任意文本按该音色合成。
换音色 = 换 config 里的 ref_audio/ref_text，无需训练。

依赖（不随默认镜像安装，见 Dockerfile 注释块）:
    git clone https://github.com/FunAudioLLM/CosyVoice /opt/CosyVoice
    pip install -r /opt/CosyVoice/requirements.txt
    export PYTHONPATH=/opt/CosyVoice:/opt/CosyVoice/third_party/Matcha-TTS:$PYTHONPATH

模型权重首次使用时经 ModelScope 自动下载到 model_dir（挂载卷 resources/models/）。
ROCm 注意: load_jit/load_trt 关；fp16 开（gfx1030 实测稳态 RTF 0.91 vs fp32 1.59）。
"""

import asyncio
import io
import logging
import wave
from pathlib import Path

from backend.tts.base import BaseTTS, TTSResult

logger = logging.getLogger("tts")

_INSTALL_HINT = (
    "CosyVoice 未安装。安装方法:\n"
    "  git clone https://github.com/FunAudioLLM/CosyVoice /opt/CosyVoice\n"
    "  pip install -r /opt/CosyVoice/requirements.txt\n"
    "  export PYTHONPATH=/opt/CosyVoice:/opt/CosyVoice/third_party/Matcha-TTS:$PYTHONPATH\n"
    "或将 config tts.engine 改回 edge-tts。"
)


class CosyVoice2Adapter(BaseTTS):
    """CosyVoice2-0.5B 零样本克隆适配器"""

    def __init__(
        self,
        model_dir: str = "resources/models/CosyVoice2-0.5B",
        ref_audio: str = "resources/voices/ref.wav",
        ref_text: str = "",
        speed: float = 1.0,
        fp16: bool = True,
    ):
        self._model_dir = model_dir
        self._ref_audio = ref_audio
        self._ref_text = ref_text
        self._speed = speed
        self._fp16 = fp16
        self._model = None
        self._ref = None
        self._load_lock = asyncio.Lock()
        # ponytail: 推理串行锁 — CosyVoice 模型非并发安全，GPU 推理本身也是串行的
        self._infer_lock = asyncio.Lock()

    # ── 懒加载 ──────────────────────────────────

    async def _ensure_loaded(self):
        if self._model is not None:
            return
        async with self._load_lock:
            if self._model is not None:
                return
            await asyncio.to_thread(self._load_blocking)

    def _load_blocking(self):
        try:
            from cosyvoice.cli.cosyvoice import CosyVoice2
        except ImportError as e:
            raise RuntimeError(_INSTALL_HINT) from e

        model_dir = Path(self._model_dir)
        if not (model_dir / "cosyvoice2.yaml").exists():
            logger.info(f"Downloading CosyVoice2-0.5B to {model_dir} (first run)...")
            from modelscope import snapshot_download
            snapshot_download("iic/CosyVoice2-0.5B", local_dir=str(model_dir))

        if not Path(self._ref_audio).exists():
            raise RuntimeError(f"参考音频不存在: {self._ref_audio}")

        logger.info("Loading CosyVoice2 model...")
        self._model = CosyVoice2(
            str(model_dir), load_jit=False, load_trt=False, fp16=self._fp16,
        )
        # 新版 API：prompt_wav 传文件路径，frontend 内部自行按 16k/24k 加载
        # （其 load_wav 的 torchaudio→TorchCodec 依赖已在容器内补丁为 soundfile 直读）
        self._ref = str(self._ref_audio)
        logger.info(f"CosyVoice2 ready (sample_rate={self._model.sample_rate})")

        # 热身：首句冷启动 RTF ~3.0（MIOpen 算子搜索），跑两句预热后稳态 ~0.9。
        # 放在加载阶段做掉，别让用户的第一句话来付这个钱。
        import time
        for text in ("预热第一句。", "预热第二句，多见一种长度。"):
            t0 = time.time()
            list(self._model.inference_zero_shot(
                text, self._ref_text, self._ref, stream=False, speed=self._speed,
            ))
            logger.info(f"CosyVoice2 warmup: {time.time() - t0:.1f}s")

    # ── 合成 ────────────────────────────────────

    async def synthesize(self, text: str) -> TTSResult:
        if not text.strip():
            return TTSResult(audio_bytes=b"", format="wav", text=text)
        await self._ensure_loaded()
        async with self._infer_lock:
            return await asyncio.to_thread(self._synthesize_blocking, text)

    def _synthesize_blocking(self, text: str) -> TTSResult:
        import numpy as np
        import torch

        chunks = [
            out["tts_speech"]
            for out in self._model.inference_zero_shot(
                text, self._ref_text, self._ref, stream=False, speed=self._speed,
            )
        ]
        if not chunks:
            return TTSResult(audio_bytes=b"", format="wav", text=text)

        audio = torch.cat(chunks, dim=1).squeeze(0).clamp(-1.0, 1.0)
        pcm = (audio.cpu().numpy() * 32767).astype(np.int16)
        sr = self._model.sample_rate

        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm.tobytes())

        return TTSResult(
            audio_bytes=buf.getvalue(),
            format="wav",
            duration_ms=len(pcm) / sr * 1000.0,
            text=text,
        )

    async def voices(self) -> list[dict]:
        # 音色 = 参考音频，config 切换；此处返回当前配置
        return [{
            "id": self._ref_audio,
            "name": f"零样本克隆 ({Path(self._ref_audio).stem})",
            "language": "zh-CN",
        }]
