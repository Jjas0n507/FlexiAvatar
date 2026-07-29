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
        for p in (self._root, self._pkg_path):
            if p not in sys.path:
                sys.path.insert(0, p)

        # 所有相对路径 → 绝对路径（CWD 即将切换到 self._root）
        _resolve = lambda p: str(Path(p).resolve()) if p else p
        self._ref_audio = _resolve(self._ref_audio)
        self._gpt_weights = _resolve(self._gpt_weights)
        self._sovits_weights = _resolve(self._sovits_weights)
        self._pretrained_dir = _resolve(self._pretrained_dir)

        # 解析权重路径（在 import 之前——inference_webui module-level 就会加载）
        gpt_path = self._gpt_weights or self._ensure_pretrained("gpt")
        sovits_path = self._sovits_weights or self._ensure_pretrained("sovits")

        if not Path(gpt_path).exists():
            raise RuntimeError(f"GPT 权重不存在: {gpt_path}")
        if not Path(sovits_path).exists():
            raise RuntimeError(f"SoVITS 权重不存在: {sovits_path}")
        if not Path(self._ref_audio).exists():
            raise RuntimeError(f"参考音频不存在: {self._ref_audio}")

        # 下载 BERT/Hubert 预训练模型到本地（cnhubert 需要 os.path.exists）
        pretrained = Path(self._root) / "GPT_SoVITS" / "pretrained_models"
        pretrained.mkdir(parents=True, exist_ok=True)
        # fast-langdetect 缓存目录（split_lang 依赖）
        (pretrained / "fast_langdetect").mkdir(exist_ok=True)
        bert_local = pretrained / "chinese-roberta-wwm-ext-large"
        hubert_local = pretrained / "chinese-hubert-base"

        from huggingface_hub import snapshot_download
        for local, repo in (
            (bert_local, "hfl/chinese-roberta-wwm-ext-large"),
            (hubert_local, "TencentGameMate/chinese-hubert-base"),
        ):
            if not (local / "config.json").exists():
                logger.info(f"Downloading {repo} → {local}")
                snapshot_download(repo, local_dir=str(local))

        # inference_webui module-level 通过环境变量获取路径
        os.environ["gpt_path"] = str(Path(gpt_path).resolve())
        os.environ["sovits_path"] = str(Path(sovits_path).resolve())
        os.environ["bert_path"] = str(bert_local)
        os.environ["cnhubert_base_path"] = str(hubert_local)

        # inference_webui 以 CWD 解析相对路径（weight.json 等）
        _prev_cwd = os.getcwd()
        os.chdir(self._root)

        try:
            from inference_webui import change_gpt_weights, change_sovits_weights  # noqa: F401
        except ImportError as e:
            os.chdir(_prev_cwd)
            raise RuntimeError(_INSTALL_HINT) from e

        logger.info("GPT-SoVITS models loaded")
        self._loaded = True

        # 热身（CWD 仍在 self._root）
        import time
        t0 = time.time()
        list(self._synthesize_raw("预热。"))
        logger.info(f"GPT-SoVITS warmup: {time.time() - t0:.1f}s")

        os.chdir(_prev_cwd)

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
            if np.issubdtype(audio.dtype, np.floating):
                pcm = (audio * 32767).astype(np.int16)
            else:
                pcm = audio.astype(np.int16)
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
        from inference_webui import get_tts_wav, dict_language

        # 短码 → 显示名（dict_language key 是显示名，value 是短码）
        _code_to_name = {v: k for k, v in dict_language.items()}
        ref_lang = _code_to_name.get(self._ref_language, self._ref_language)
        out_lang = _code_to_name.get("zh", "Chinese-English Mixed")

        # GPT-SoVITS 依赖 CWD 解析所有相对路径
        _prev = os.getcwd()
        os.chdir(self._root)
        try:
            return get_tts_wav(
                ref_wav_path=self._ref_audio,
                prompt_text=self._ref_text,
                prompt_language=ref_lang,
                text=text,
                text_language=out_lang,
                how_to_cut="不切",
                top_p=1.0,
                temperature=1.0,
                speed=self._speed,
            )
        finally:
            os.chdir(_prev)

    async def voices(self) -> list[dict]:
        name = "微调模型" if self._gpt_weights else f"零样本克隆 ({Path(self._ref_audio).stem})"
        return [{"id": self._ref_audio, "name": name, "language": "zh"}]
