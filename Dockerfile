FROM rocm/pytorch:rocm7.2.4_ubuntu22.04_py3.10_pytorch_release_2.10.0

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1

# 系统依赖: ffmpeg（Edge-TTS MP3→WAV 转换）
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libsndfile1 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python 依赖（分层缓存）
RUN pip install --no-cache-dir \
    fastapi>=0.115.0 uvicorn[standard]>=0.34.0 websockets>=12.0 \
    pyyaml>=6.0 python-dotenv>=1.0 pydantic>=2.0 httpx>=0.28.0 \
    faster-whisper silero-vad edge-tts pydub pypinyin \
    soundfile>=0.12.0 openai>=1.0.0 \
    funasr>=1.2.0

# 注意: ROCm GPU 验证在运行时进行（docker compose up 时挂载 /dev/kfd /dev/dri）
# 构建时不验证（docker build 没有 GPU 设备）

COPY backend/ /app/backend/
EXPOSE 8765
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8765"]
