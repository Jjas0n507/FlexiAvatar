# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Development Commands

```bash
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
| TTS | `backend/tts/base.py::BaseTTS` | `EdgeTTSAdapter` | Only `SentenceBoundary` (no `WordBoundary`). Mouth shapes via `pypinyin`. MP3→WAV via `pydub` (requires ffmpeg). |
| LLM | `backend/llm/base.py::BaseLLM` | `OpenAIStreamingAdapter` | SSE streaming. `stream_chat()`, `chat()`, `chat_with_tools()`. |

### WebSocket Messages

JSON `{type, id, timestamp, payload}`. Handlers in `main.py` via `MESSAGE_HANDLERS` dict.

- **Client → Server**: `audio.chunk` (base64 PCM int16), `chat.text`, `user.interrupt`, `ping`
- **Server → Client**: `state.change`, `asr.result`, `llm.stream`, `tts.audio` (WAV + phonemes), `live2d.control`

### Live2D Mouth Shapes

```
TTS text → pypinyin finals → A/I/U/E/O/N → Cubism parameters
```

Emotion detection: keyword-based (`_EMOTION_KEYWORDS`). State-driven expressions: listening→neutral, processing→thinking, interrupted→surprised.

### Configuration

Singleton Config (`backend/config.py`): `config.default.yaml` → deep-merge `config.user.yaml` (gitignored) → resolve `${VAR_NAME}` from `.env`. Access via `config.get("dot.path")`. Sensitive fields masked in `GET /api/config`.

### Tool System

Drop a Python file into `backend/tools/user_tools/` — auto-discovered. Inherit `Tool`, define `name`, `description`, `parameters_model()` (Pydantic), `execute(**params)`.

## Notes

- **Silero VAD**: 512-sample frames are non-negotiable.
- **Network**: HF via `hf-mirror.com`, Edge-TTS needs no auth. Models cached in `resources/models/` (gitignored).
- **Git**: Feature branches `phase{N}-{name}` from `master`. Run tests before committing.
- **Gitignored**: `resources/models/`, `resources/test_audio/tts_output_*`, `config.user.yaml`, `backend/tools/user_tools/*`
- **ffmpeg**: Required by `pydub` for MP3→WAV conversion. Install via `winget install ffmpeg` on Windows.

## Project Status

动态项目状态（当前分支、进度、待办）见以下文件，`CLAUDE.md` 不记录以免过时：

- [`STATUS.md`](STATUS.md) — 当前分支、阶段、最近提交
- [`NEXT.md`](NEXT.md) — 短期待办、当前优先级
- [`TODO.md`](TODO.md) — 全阶段缺口与优化项

个人偏好和设置请放在本地的 `~/.claude/CLAUDE.md`，不要提交到团队仓库。
