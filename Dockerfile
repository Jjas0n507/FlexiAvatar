FROM rocm/pytorch:rocm7.2.4_ubuntu22.04_py3.10_pytorch_release_2.10.0

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1

# 系统依赖: ffmpeg（funasr/torchaudio 音频解码）
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libsndfile1 git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python 依赖（分层缓存）
RUN pip install --no-cache-dir \
    fastapi>=0.115.0 uvicorn[standard]>=0.34.0 websockets>=12.0 \
    pyyaml>=6.0 python-dotenv>=1.0 pydantic>=2.0 httpx>=0.28.0 \
    faster-whisper silero-vad edge-tts \
    soundfile>=0.12.0 openai>=1.0.0 \
    funasr>=1.2.0

# ── CosyVoice2 本地 TTS（零样本音色克隆，config tts.engine: cosyvoice2）──
# 固化自 2026-07 手工验证的容器环境（此前进容器手装，recreate 即失）：
# - torch/torchaudio 用 ROCm 基础镜像自带 → 排除上游 CUDA 版
# - tensorrt/deepspeed/onnxruntime-gpu 为 CUDA 专属 → 排除；onnxruntime 用 CPU 版
# - 上游会锁 fastapi==0.115.6/uvicorn==0.30.0/pydantic==2.7.0 等（实测兼容）
# - setuptools<81: 依赖链仍 import pkg_resources
# - openai-whisper 升为 20250625: 上游 pin 20231117 的 sdist 在
#   setuptools>=81 的构建隔离环境里 import pkg_resources 必挂（与容器实况一致）
ARG COSYVOICE_REF=074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc
RUN git init /opt/CosyVoice \
    && cd /opt/CosyVoice \
    && git remote add origin https://github.com/FunAudioLLM/CosyVoice.git \
    && git fetch --depth 1 origin ${COSYVOICE_REF} \
    && git checkout FETCH_HEAD \
    && git submodule update --init --recursive --depth 1 \
    && grep -vE "^--extra-index|^torch|^torchaudio|tensorrt|deepspeed|onnxruntime|^openai-whisper" requirements.txt > /tmp/cosyvoice-req.txt \
    && pip install --no-cache-dir -r /tmp/cosyvoice-req.txt \
       onnxruntime==1.23.2 "setuptools<81" \
       openai-whisper==20250625 \
    && rm /tmp/cosyvoice-req.txt \
    && rm -rf /opt/CosyVoice/.git /opt/CosyVoice/third_party/Matcha-TTS/.git

# sys.path 注入（.pth 比 ENV PYTHONPATH 稳：任何入口/子进程都生效）
RUN SP=$(python -c "import site; print(site.getsitepackages()[0])") \
    && printf '%s\n%s\n' "/opt/CosyVoice" "/opt/CosyVoice/third_party/Matcha-TTS" > "$SP/cosyvoice.pth"

# load_wav → soundfile 直读补丁（torchaudio 2.10 的 load 依赖 TorchCodec，镜像内不可用）
COPY scripts/patch-cosyvoice-load-wav.py /tmp/
RUN python /tmp/patch-cosyvoice-load-wav.py && rm /tmp/patch-cosyvoice-load-wav.py

# 注意: ROCm GPU 验证在运行时进行（docker compose up 时挂载 /dev/kfd /dev/dri）
# 构建时不验证（docker build 没有 GPU 设备）

COPY backend/ /app/backend/
EXPOSE 8765
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8765"]
