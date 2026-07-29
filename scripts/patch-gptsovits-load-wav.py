"""Patch GPT-SoVITS torchaudio.load → soundfile（ROCm 镜像缺 TorchCodec）。"""
import re
from pathlib import Path

TARGET = Path("/opt/GPT-SoVITS/GPT_SoVITS/inference_webui.py")
src = TARGET.read_text()

# soundfile 替换: sf.read → tensor (channels, samples), sf 返回 (samples, channels)
shim = '''
def _sf_load(path):
    import soundfile as sf
    import torch
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    return torch.from_numpy(data.T), sr
'''

# 替换 torchaudio.load(...) → _sf_load(...)
patched = re.sub(r'\btorchaudio\.load\(', '_sf_load(', src)

if patched == src:
    print("No torchaudio.load calls found — already patched?")
else:
    # 在 import torchaudio 之后插入 shim
    patched = patched.replace("import torchaudio", "import torchaudio\n" + shim, 1)
    TARGET.write_text(patched)
    count = len(re.findall(r'_sf_load\(', patched))
    print(f"Patched {count} torchaudio.load calls in {TARGET}")
