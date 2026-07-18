# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Development Commands

### Local (venv)

```bash
# 创建虚拟环境（首次）
python3 -m virtualenv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt    # PyAudio 需要 portaudio19-dev

# Backend
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8765

# Tests (backend must NOT be running for unit tests)
python -m pytest tests/ -v
# python tests/test_integration.py     # needs backend running
# python tests/test_e2e_voice.py       # needs backend running

# Frontend
cd frontend
npm install                   # One-time
npm run dev                   # Vite dev server
npm run electron:dev          # Vite + Electron
npm run lint                  # oxlint
npm run build                 # TS build + Vite bundle
```

### Docker (推荐，一键启动)

```bash
# 前置条件: Docker + AMD ROCm GPU (/dev/kfd, /dev/dri)
# 首次使用需在 .env 中配置 OPENAI_API_KEY

# 构建并启动所有服务（Ollama + Backend）
docker compose --profile gpu build backend
docker compose --profile gpu up -d

# 等待后端就绪
curl http://127.0.0.1:8765/health

# 启动 Electron 前端（连接 Docker 后端）
cd frontend
unset ELECTRON_RUN_AS_NODE
FLEXIAVATAR_DOCKER=1 npm run electron:dev

# 或一键启动脚本
bash scripts/start-docker.sh

# 查看日志
docker compose logs -f backend

# 停止服务
docker compose --profile gpu down
```

**Docker 架构说明：**

```
┌─ Docker ─────────────────────────────────────────────┐
│  ollama (rocm)         backend (rocm/pytorch)         │
│  :11434                 :8765                         │
│  qwen2.5:7b             FastAPI + WebSocket           │
│                         ├─ funasr (SenseVoiceSmall)   │
│ Volumes:                ├─ faster-whisper (备选)       │
│  ollama_data            ├─ silero-vad                 │
│  modelscope_cache       ├─ cosyvoice2 (默认 TTS)      │
│                         └─ edge-tts (零 GPU 备选)     │
└──────────────────────────────────────────────────────┘
        │                         │
        │                   backend:8765
        │                   mounted: ./backend:/app/backend:ro
        │                         │
  本地 Electron ◄── WebSocket ─────┘
  (Vite + React + Live2D)
```

**Docker 相关文件：**

| 文件 | 用途 |
|------|------|
| `Dockerfile` | 基于 `rocm/pytorch`，安装 funasr/whisper/vad/tts |
| `docker-compose.yml` | 编排 ollama + backend，profiles: gpu/cpu |
| `scripts/start-docker.sh` | 一键启动脚本 |
| `backend/config.user.yaml` | 覆盖引擎选择：asr=funasr / llm=ollama / tts=cosyvoice2（gitignored） |

## Architecture

### Hybrid Process Model

```
Electron Main Process (Node)
  ├── Creates BrowserWindow → React renderer (WebGL Live2D + UI)
  └── Spawns Python subprocess → FastAPI + WebSocket on 127.0.0.1:8765
```

Electron and Python communicate exclusively over WebSocket. The Python bridge (`electron/python-bridge.ts`) handles startup, health-check polling (`GET /health`), and auto-restart (max 5 retries).

### Session State Machine

5 states with strict transitions (`backend/session/manager.py`):

```
IDLE ──(vad_speech_start)──→ LISTENING ──(vad_speech_end)──→ PROCESSING
  ↑                               │                              │
  │                          (vad_timeout)                  (processing_done)
  │                               ↓                              ↓
  └──(speaking_done)────── IDLE                           SPEAKING ──┐
                                                                     │
                                           INTERRUPTED ←──(interrupt)─┘
                                                │
                                                └──(interrupt_handled)──→ LISTENING
```

Key: `cancel_event` (`asyncio.Event`) is set on entering `INTERRUPTED` — all async tasks must check this and abort. `INTERRUPTED` → `LISTENING` after 300ms cooldown.

### Audio Pipeline (`backend/audio_pipeline.py`)

Central orchestrator, one instance per WebSocket client. The main loop polls `_input_queue` for audio frames and behaves differently per state (IDLE→VAD scan, LISTENING→buffer, SPEAKING→interrupt check, INTERRUPTED→cooldown). `_process_speech()` runs ASR → LLM → TTS → Live2D, checking `cancel_event` between each stage.

### Model Adapter Pattern

Abstract base class → adapter implementation, selected by config `engine` field.

| Module | Base Class | Adapter | Key Constraint |
|--------|-----------|---------|----------------|
| VAD | `backend/vad/base.py::BaseVAD` | `SileroVAD` | **512 samples** exactly (32ms @ 16kHz). Torch tensors, not numpy. |
| ASR | `backend/asr/base.py::BaseASR` | `WhisperASR` | Faster-Whisper (CTranslate2). `HF_ENDPOINT` → `hf-mirror.com`. |
| ASR | `backend/asr/base.py::BaseASR` | `FunASRAdapter` | SenseVoiceSmall (ModelScope). **ASR+SER 一模型**，输出 `<\|HAPPY\|>文本`。非自回归 ~70ms/10s。 |
| TTS | `backend/tts/base.py::BaseTTS` | `EdgeTTSAdapter` | MP3 原始字节直传（24kHz 48kbps CBR），`duration_ms=len/6` 估算。口型由前端 RMS 驱动，不需要时间戳。 |
| TTS | `backend/tts/base.py::BaseTTS` | `CosyVoice2Adapter` | 零样本音色克隆（3-10s ref wav + 逐字文本，换音色=换 config）。WAV 直传，时长精确。ROCm: fp16 开、load_jit/trt 关。**进程单例**（`adapters.py::_cached`）+ 启动预热；短句 RTF ~1.5（段间有静默），长句 ≤1.0。 |
| LLM | `backend/llm/base.py::BaseLLM` | `OpenAIStreamingAdapter` | SSE streaming. `stream_chat()`, `chat()`, `chat_with_tools()`. |

### WebSocket Messages

JSON `{type, id, timestamp, payload}`. Handlers in `main.py` via `MESSAGE_HANDLERS` dict.

- **Client → Server**: `audio.chunk` (base64 PCM int16), `chat.text`, `user.interrupt`, `playback.done`, `ping`
- **Server → Client**: `state.change`, `asr.result`, `llm.stream`, `tts.audio` (`{utteranceId, seq, audio: base64 mp3/wav, format, durationMs, expressions}`), `live2d.control` (仅打断等控制)

### Live2D Lip Sync

```
tts.audio (mp3/wav bytes) → useAudioPlayback FIFO 泵 → speak 桥（Live2DCanvas）:
OfflineAudioContext 解码（纯内存，不开输出流） + <audio> 媒体线程播放 →
每帧按 el.currentTime 取窗口 RMS → model3.json LipSync 组参数
```

渲染器 pixi-live2d-display@0.4.0：参数**每帧回滚**（update 末尾 `loadParameters`），
持久效果必须在 `beforeModelUpdate` 钩子里每帧重写，单帧写入不可见、"清零复位"有害。
口型与播放头同源（`el.currentTime`），结构上不失步；`speak()` 带时长看门狗（onended 丢失不卡泵）。
语音/文字聊天共用后端 `AudioPipeline.respond()`（分句 → 有界并发 TTS → 按 seq 有序发送 → 等 `playback.done`）。

**约束**: WS 消息处理器**不得在接收循环里同步 `await respond()`** —— `playback.done`
只能从该循环读出，同步等待 = 自死锁（必假超时）。一律 `asyncio.create_task`（语音/文字路径均已如此）。

Emotion detection: **双路径融合** — SenseVoice SER 语音情绪优先，fallback 文本关键词 (`_EMOTION_KEYWORDS` + `_SPEECH_EMOTION_MAP`)。State-driven expressions: listening→neutral, processing→thinking, interrupted→surprised。

### Configuration

Singleton Config (`backend/config.py`): `config.default.yaml` → deep-merge `config.user.yaml` (gitignored) → resolve `${VAR_NAME}` from `.env`. Access via `config.get("dot.path")`. Sensitive fields masked in `GET /api/config`.

### Tool System

Drop a Python file into `backend/tools/user_tools/` — auto-discovered. Inherit `Tool`, define `name`, `description`, `parameters_model()` (Pydantic), `execute(**params)`.

## Notes

- **Silero VAD**: 512-sample frames are non-negotiable.
- **Network**: HF via `hf-mirror.com`, Edge-TTS needs no auth. Models cached in `resources/models/` (gitignored).
- **Git**: Feature branches `phase{N}-{name}` from `master`. Run tests before committing.
- **Gitignored**: `resources/models/`, `resources/test_audio/tts_output_*`, `config.user.yaml`, `backend/tools/user_tools/*`
- **ffmpeg**: funasr/torchaudio 依赖系统 ffmpeg；TTS 链路已不需要（MP3 直传前端解码）。
- **前端启动**: 必须经 `scripts/dev-frontend.sh`（或任何非 snap 终端）——snap VSCode 终端泄漏 core20 库路径会打崩 Electron GPU 加速。
- **Dev 排查口**: dev 模式 Electron 开 CDP `127.0.0.1:9223`（可读 renderer console / 远程执行），renderer 暴露 `window.__wsClient`（均仅 isDev）。

## Project Status

动态项目状态（当前分支、进度、待办）见以下文件，`CLAUDE.md` 不记录以免过时：

- [`STATUS.md`](STATUS.md) — 当前分支、阶段、最近提交
- [`NEXT.md`](NEXT.md) — 短期待办、当前优先级
- [`TODO.md`](TODO.md) — 全阶段缺口与优化项

个人偏好和设置请放在本地的 `~/.claude/CLAUDE.md`，不要提交到团队仓库。
