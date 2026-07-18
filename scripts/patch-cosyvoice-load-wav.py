"""Docker 构建期补丁: CosyVoice load_wav → soundfile 直读。

torchaudio 2.10 的 load() 依赖 TorchCodec，ROCm 镜像内不可用；
soundfile 直读等效（load_wav 后续自己做重采样/单声道化）。
上游行变了会 assert 失败 → 构建报错，提醒重新核对 COSYVOICE_REF。
"""
from pathlib import Path

TARGET = Path("/opt/CosyVoice/cosyvoice/utils/file_utils.py")

OLD = "    speech, sample_rate = torchaudio.load(wav, backend='soundfile')\n"
NEW = (
    "    # patched(FlexiAvatar): soundfile 直读 — torchaudio 2.10 load 依赖 TorchCodec\n"
    "    import soundfile as _sf\n"
    "    _data, sample_rate = _sf.read(wav, dtype='float32', always_2d=True)\n"
    "    import torch as _torch\n"
    "    speech = _torch.from_numpy(_data.T)\n"
)

src = TARGET.read_text()
assert OLD in src, f"load_wav 上游代码已变化，请核对 COSYVOICE_REF: {TARGET}"
TARGET.write_text(src.replace(OLD, NEW))
print("patched: load_wav → soundfile")
