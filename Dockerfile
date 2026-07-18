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
    faster-whisper silero-vad edge-tts pydub pypinyin \
    soundfile>=0.12.0 openai>=1.0.0 \
    funasr>=1.2.0

# ── 可选: CosyVoice2 本地 TTS（config tts.engine: cosyvoice2）─────────
# 默认不安装（pynini 等依赖在部分环境构建易失败，不拖累默认镜像）。
# 需要时取消注释重新 build，或进容器手动执行:
# RUN git clone --depth 1 https://github.com/FunAudioLLM/CosyVoice /opt/CosyVoice \
#     && cd /opt/CosyVoice && git submodule update --init --recursive \
#     && pip install --no-cache-dir -r requirements.txt
# ENV PYTHONPATH=/opt/CosyVoice:/opt/CosyVoice/third_party/Matcha-TTS

# 注意: ROCm GPU 验证在运行时进行（docker compose up 时挂载 /dev/kfd /dev/dri）
# 构建时不验证（docker build 没有 GPU 设备）

COPY backend/ /app/backend/
EXPOSE 8765
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8765"]
