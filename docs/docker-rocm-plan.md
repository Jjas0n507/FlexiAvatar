# Docker + AMD ROCm 本地 GPU 部署方案

> 状态: 待审核 | 日期: 2026-07-13 | GPU: AMD RX 6800 XT 16GB (gfx1030)

---

## 目标

将 FlexiAvatar 的模型推理从云端迁移到本地 GPU，降低交互延迟。

| 指标 | 当前 | 预期（本地 GPU） |
|------|------|-------------------|
| LLM 首 token 延迟 | ~2-5s (OpenAI 网络) | ~0.5-1s (Ollama 本地) |
| TTS 延迟 | ~1-3s/句 (Edge-TTS 云) | 不变（暂留 Edge-TTS） |
| ASR 首次加载 | ~50s (懒加载) | 预加载到启动时 |
| 整体首轮延迟 | ~10s | ~3-5s |

---

## 架构变更

```
当前:
  Electron ──spawn python──→ uvicorn (本地进程)
                              ├── ASR: faster-whisper (本地 CPU)
                              ├── LLM: OpenAI API (云端) ← 网络延迟
                              └── TTS: Edge-TTS (云端)   ← 网络延迟

目标:
  Host (Ubuntu 22.04)
  ├── Docker Compose
  │   ├── ollama (ollama/ollama:rocm)      ← LLM 本地, GPU 加速
  │   └── backend (rocm/pytorch 镜像)       ← ASR/TTS/VAD
  └── Electron ──health check──→ localhost:8765
```

---

## 硬件确认

```
$ lspci | grep VGA
03:00.0 VGA: AMD Navi 21 [Radeon RX 6800/6800 XT / 6900 XT] (rev c1)
12:00.0 VGA: AMD Device 164e (Ryzen iGPU)

设备ID: 0x73BF → RX 6800 XT (gfx1030, RDNA2)
显存: 16 GB VRAM
ROCm 支持: ✅ 官方支持 (ROCm 5.4+)

⚠️ 双 GPU 注意: 通过 ROCR_VISIBLE_DEVICES=0 选择独显
```

---

## 新增文件清单

### 1. `Dockerfile`（项目根目录）

```dockerfile
FROM rocm/pytorch:rocm7.2.4_ubuntu22.04_py3.10_pytorch_release_2.10.0

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1

# 系统依赖: ffmpeg（Edge-TTS 需要 MP3→WAV）
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libsndfile1 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python 依赖（分层缓存）
RUN pip install --no-cache-dir \
    fastapi>=0.115.0 uvicorn[standard]>=0.34.0 websockets>=12.0 \
    pyyaml>=6.0 python-dotenv>=1.0 pydantic>=2.0 httpx>=0.28.0 \
    faster-whisper silero-vad edge-tts pydub pypinyin \
    soundfile>=0.12.0 openai>=1.0.0

# 验证 ROCm 可见
RUN python -c "import torch; assert torch.cuda.is_available(), 'ROCm not detected!'"

COPY backend/ /app/backend/
EXPOSE 8765
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8765"]
```

> **注意**: 基础镜像 Python 3.10（非 3.11），项目代码不依赖 3.11 新特性，兼容。
> 开发时通过 docker-compose volume mount 覆盖 `/app/backend`，无需重建镜像。

### 2. `docker-compose.yml`（项目根目录）

```yaml
services:
  ollama:
    image: ollama/ollama:rocm
    container_name: flexiavatar-ollama
    ports: ["11434:11434"]
    volumes: [ollama_data:/root/.ollama]
    devices: [/dev/kfd, /dev/dri:/dev/dri]
    group_add: [video, render]
    environment:
      - ROCR_VISIBLE_DEVICES=0
    restart: unless-stopped
    profiles: [gpu]

  backend:
    build: {context: ., dockerfile: Dockerfile}
    container_name: flexiavatar-backend
    ports: ["8765:8765"]
    volumes:
      - ./backend:/app/backend:ro
      - ./resources/models:/app/resources/models:rw
    devices: [/dev/kfd, /dev/dri:/dev/dri]
    group_add: [video, render]
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY:-}
      - OPENAI_BASE_URL=${OPENAI_BASE_URL:-}
      - HF_ENDPOINT=${HF_ENDPOINT:-https://hf-mirror.com}
      - ROCR_VISIBLE_DEVICES=0
    command: python -m uvicorn backend.main:app --host 0.0.0.0 --port 8765
    restart: unless-stopped
    profiles: [gpu, cpu]

volumes:
  ollama_data:
```

**Profiles 说明**:
- `--profile gpu`: 启动 backend + ollama（全本地）
- `--profile cpu`: 仅启动 backend（云 API 模式，开发/调试用）

### 3. `.dockerignore`（项目根目录）

```
node_modules/
.git/
frontend/
electron/
__pycache__/
*.pyc
.venv/
.DS_Store
*.log
```

### 4. `backend/adapters.py` — 适配器工厂

将引擎选择从硬编码改为配置驱动。当前 `audio_pipeline.py` 直接 import
`SileroVAD`/`WhisperASR`/`EdgeTTSAdapter`/`OpenAIAdapter`，
切换引擎需要改代码。工厂模式让用户只需改 `config.user.yaml` 即可切换。

```python
"""适配器工厂 — 根据 config 的 engine 字段动态创建适配器实例"""

from backend.config import Config


def create_vad(config: Config):
    engine = config.get("vad.engine", "silero")
    if engine == "silero":
        from backend.vad.silero_adapter import SileroVAD
        return SileroVAD(threshold=config.get("vad.speech_threshold", 0.5))
    raise ValueError(f"Unknown VAD engine: {engine}")


def create_asr(config: Config):
    engine = config.get("asr.engine", "whisper")
    if engine == "whisper":
        from backend.asr.whisper_adapter import WhisperASR
        return WhisperASR(
            model_size=config.get("asr.whisper.model_size", "base"),
            language="zh",
            device=config.get("asr.whisper.device", "cpu"),
            compute_type=config.get("asr.whisper.compute_type", "int8"),
            beam_size=config.get("asr.whisper.beam_size", 5),
        )
    elif engine == "funasr":
        from backend.asr.funasr_adapter import FunASRAdapter
        return FunASRAdapter(
            model=config.get("asr.funasr.model", "iic/SenseVoiceSmall"),
            device=config.get("asr.funasr.device", "cpu"),
        )
    raise ValueError(f"Unknown ASR engine: {engine}")


def create_llm(config: Config):
    engine = config.get("llm.engine", "openai")
    if engine == "openai":
        from backend.llm.openai_adapter import OpenAIAdapter
        return OpenAIAdapter()
    elif engine == "ollama":
        from backend.llm.ollama_adapter import OllamaAdapter
        return OllamaAdapter()
    raise ValueError(f"Unknown LLM engine: {engine}")


def create_tts(config: Config):
    engine = config.get("tts.engine", "edge-tts")
    if engine == "edge-tts":
        from backend.tts.edge_tts_adapter import EdgeTTSAdapter
        return EdgeTTSAdapter(
            voice=config.get("tts.edge_tts.voice", "zh-CN-XiaoxiaoNeural"),
            speed=config.get("tts.edge_tts.speed", "+10%"),
        )
    elif engine == "chattts":
        from backend.tts.chattts_adapter import ChatTTSAdapter
        return ChatTTSAdapter()
    raise ValueError(f"Unknown TTS engine: {engine}")
```

### 5. `backend/llm/ollama_adapter.py` — Ollama 适配器

Ollama 暴露 OpenAI 兼容的 `/v1/chat/completions` 端点，直接继承 `OpenAIAdapter`：

```python
"""Ollama LLM 适配器 — 复用 OpenAIAdapter 的流式逻辑"""

from backend.llm.openai_adapter import OpenAIAdapter
from backend.config import config


class OllamaAdapter(OpenAIAdapter):
    def __init__(self):
        base_url = config.get("llm.ollama.base_url", "http://localhost:11434")
        super().__init__(
            model=config.get("llm.ollama.model", "qwen2.5:7b"),
            base_url=f"{base_url.rstrip('/')}/v1",
            api_key="ollama",       # Ollama 不需要 API key
            temperature=config.get("llm.ollama.temperature", 0.7),
            max_tokens=config.get("llm.openai.max_tokens", 1024),
        )
```

### 6. `scripts/start-docker.sh` — 一键启动

```bash
#!/bin/bash
set -e
cd "$(dirname "$0")/.."

echo "=== Pulling Docker images ==="
docker compose --profile gpu pull

echo "=== Starting services ==="
docker compose --profile gpu up -d

echo "=== Pulling Ollama model ==="
docker compose exec ollama ollama pull qwen2.5:7b 2>/dev/null || true

echo "=== Waiting for backend ==="
for i in $(seq 1 30); do
  if curl -s http://127.0.0.1:8765/health >/dev/null 2>&1; then
    echo "Backend ready!"; break
  fi
  sleep 2
done

echo "=== Starting Electron ==="
FLEXIAVATAR_DOCKER=1 npm run electron:dev
```

---

## 修改文件清单

### 1. `backend/audio_pipeline.py`

**删除** L22-28 硬编码 import、**替换** L73-94 构造逻辑为工厂调用：

```python
# 删除:
# from backend.vad.silero_adapter import SileroVAD
# from backend.asr.whisper_adapter import WhisperASR
# from backend.tts.edge_tts_adapter import EdgeTTSAdapter
# from backend.llm.openai_adapter import OpenAIAdapter

# 新增:
from backend.adapters import create_vad, create_asr, create_llm, create_tts

# _init_engines() 中改为:
if self._vad is None:
    self._vad = create_vad(config)
    self._asr = create_asr(config)
    self._llm = create_llm(config)
    self._tts = create_tts(config)
    self._motion = MotionController()
    # ...
```

### 2. `electron/python-bridge.ts`

`start()` 方法新增 Docker 模式路径：

```typescript
async start(): Promise<boolean> {
  if (process.env.FLEXIAVATAR_DOCKER === "1") {
    return this._startWithHealthCheck();  // 只轮询 health, 不 spawn
  }
  return this._startNative();             // 原有逻辑
}
```

`stop()` 方法 Docker 模式下不杀进程（容器由用户管理）。

### 3. `backend/config.default.yaml`

新增配置块：

```yaml
gpu:
  rocm_enabled: false
  device_id: 0

tts:
  engine: "edge-tts"
  chattts:
    seed: 42
    temperature: 0.3

llm:
  engine: "openai"
  ollama:
    base_url: "http://localhost:11434"
    model: "qwen2.5:7b"
    temperature: 0.7
```

**用户切到本地 LLM 只需**在 `config.user.yaml` 中:

```yaml
llm:
  engine: "ollama"
```

---

## 用户手动操作（需要 sudo）

### 步骤 1: 安装 ROCm 内核驱动

Docker 容器共享宿主机内核，ROCm 用户态库在容器内，但内核驱动必须在宿主机：

```bash
# Ubuntu 22.04 — ROCm 6.3
wget https://repo.radeon.com/amdgpu-install/6.3/ubuntu/jammy/amdgpu-install_6.3.60300-1_all.deb
sudo apt install ./amdgpu-install_6.3.60300-1_all.deb
sudo amdgpu-install --usecase=dkms,rocr
sudo usermod -a -G render,video $USER
sudo reboot
```

### 步骤 2: 安装 Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# 重新登录
```

### 步骤 3: 验证 GPU 穿透

```bash
docker run --rm \
  --device=/dev/kfd --device=/dev/dri \
  --group-add=video --group-add=render \
  rocm/pytorch:rocm7.2.4_ubuntu22.04_py3.10_pytorch_release_2.10.0 \
  python -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"

# 输出应为: True / AMD Radeon RX 6800 XT
```

### 步骤 4: 启动项目

```bash
cd FlexiAvatar
cp backend/.env.example backend/.env 2>/dev/null || true  # 确保有 .env
bash scripts/start-docker.sh
```

---

## 模型选择建议

### LLM（Ollama, GPU 加速）

| 模型 | VRAM | 速度 | 适用 |
|------|------|------|------|
| `qwen2.5:7b` | ~5 GB | 快 | 日常对话 ✅ 推荐 |
| `qwen2.5:14b` | ~10 GB | 中 | 复杂推理 |
| `qwen2.5:3b` | ~2 GB | 极快 | 轻量低延迟 |

### ASR: 保持 CPU（暂不切 GPU）

| 选项 | RTF | 内存 | 可行性 |
|------|-----|------|--------|
| faster-whisper base int8 (CPU) | 0.44x | 400MB | ✅ 当前方案 |
| faster-whisper + ROCm | N/A | N/A | ❌ CTranslate2 ROCm 不稳定 |
| openai-whisper + PyTorch ROCm | 1.5x | 2GB | ⚠️ 比 CPU 慢 |
| FunASR SenseVoiceSmall + ROCm | 0.15x | 1GB | 🔮 后续选项 |

### TTS: 暂留 Edge-TTS

本地 TTS（ChatTTS/GPT-SoVITS）需要额外 2-4 GB VRAM，本次不实现。
Edge-TTS 延迟可接受，后续按需添加 `backend/tts/chattts_adapter.py`。

### VRAM 预算

| 组件 | VRAM |
|------|------|
| Ollama qwen2.5:7b (4-bit) | ~5 GB |
| ChatTTS (未来) | ~2 GB |
| PyTorch 框架开销 | ~0.5 GB |
| **合计** | **~7.5 GB** |
| **可用 (RX 6800 XT)** | **16 GB** ✅ |

---

## 验证清单

- [ ] `docker compose up -d backend` → `curl http://127.0.0.1:8765/health` 返回 `{"status":"ok"}`
- [ ] `docker compose --profile gpu up -d` → Ollama 启动
- [ ] `docker compose exec ollama ollama pull qwen2.5:7b` → 模型下载成功
- [ ] WebSocket 连接 → 发送 `{"type":"chat.text","payload":{"text":"你好"}}` → 收到 `tts.audio`
- [ ] `docker compose exec backend python -c "import torch; print(torch.cuda.get_device_name(0))"` → 显示 AMD GPU
- [ ] 延迟对比: 本地 LLM 首 token < 1s vs 当前 ~2-5s

---

## 未覆盖项（后续 Phase）

- **ChatTTS 适配器**: 本地 TTS 消除 Edge-TTS 网络依赖（需 `backend/tts/chattts_adapter.py`）
- **ASR 预加载**: 在 FastAPI `startup` 事件中 warmup，消除首次对话 ~50s 冷启动
- **FunASR 适配器**: 中文识别率更高，GPU 加速 RTF 0.15x（需 `backend/asr/funasr_adapter.py`）
- **前端 UI 切换**: 设置面板支持一键切换云端/本地引擎
