# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Environment

```bash
conda activate ai-agent          # Python 3.11 conda env (from environment.yml)
cd frontend && npm install        # Install frontend dependencies (one-time)
```

### Backend (Python)

```bash
# Start the backend server
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8765

# Run individual tests (backend must NOT be running for non-integration tests)
python tests/test_basic.py      # Config + state machine + tool registry
python tests/test_vad.py        # Silero VAD: synthetic, Chinese speech, interrupt, silence
python tests/test_asr.py        # Faster-Whisper: 3 Chinese speech files with confidence checks
python tests/test_tts.py        # Edge-TTS: synthesis, mouth shapes, edge cases, voice listing

# Integration/E2E tests (backend must be running first)
python tests/test_integration.py  # WebSocket ping/pong, chat, REST health/tools/state
python tests/test_e2e_voice.py    # Send WAV frame-by-frame → verify ASR→TTS→Live2D chain
```

### Frontend (TypeScript/React/Electron)

```bash
cd frontend
npm run dev              # Vite dev server (web only, no Electron)
npm run electron:dev     # Vite + Electron dev mode
npm run lint             # oxlint
npm run build            # TypeScript build + Vite bundle
```

## Architecture: The Big Picture

### Hybrid Process Model

```
Electron Main Process (Node)
  ├── Creates BrowserWindow → React renderer (WebGL Live2D + UI)
  └── Spawns Python subprocess → FastAPI + WebSocket on 127.0.0.1:8765
```

Electron manages two processes: the renderer (React/TypeScript) for UI and Live2D rendering, and a Python child process for all ML inference (VAD/ASR/TTS/LLM). They communicate exclusively over WebSocket. The Python bridge (`electron/python-bridge.ts`) handles startup, health-check polling (`GET /health`), and auto-restart (max 5 retries). On packaged builds, it finds Python at `~/anaconda3/envs/ai-agent/python.exe`; otherwise falls back to system `python`.

### Session State Machine

The session has exactly 5 states with strict allowed transitions:

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

Key rules implemented in `backend/session/manager.py`:
- `INTERRUPTED` can only be reached from `PROCESSING` or `SPEAKING`
- `INTERRUPTED` always transitions to `LISTENING` (after a short cooldown)
- `cancel_event` (`asyncio.Event`) is set on entering `INTERRUPTED` — all async tasks (LLM generation, TTS synthesis) must check this and abort
- `on_transition` decorator allows registering async listeners

### The Audio Pipeline (Core Orchestration)

`backend/audio_pipeline.py` is the central orchestrator. One pipeline instance per WebSocket client. The main loop (`run()`) is a while-true async loop that:

1. Polls `_input_queue` for audio frames from the frontend
2. Checks `session_manager.state` at each frame to decide behavior:
   - **IDLE**: Low-frequency VAD scanning — if `should_interrupt()` returns true, transition to LISTENING
   - **LISTENING**: Buffer frames, run `process_frame()`. On `speech_end` event, flush the queue (critical: prevents residual frames from triggering false interrupts during SPEAKING), then spawn `_process_speech()` as a background task
   - **SPEAKING**: Run `should_interrupt()` on each frame — if true, trigger interrupt + send Live2D interrupt command
   - **INTERRUPTED**: Wait 300ms cooldown, then transition to LISTENING

`_process_speech()` runs the full ASR → (LLM/Echo) → TTS → Live2D chain, checking `cancel_event` between each stage.

### Model Adapter Pattern

Every ML component follows the same pattern: **abstract base class → adapter implementation, selected by config**.

| Module | Base Class | Current Adapter | Key Constraint |
|--------|-----------|----------------|----------------|
| VAD | `backend/vad/base.py::BaseVAD` | `SileroVAD` | Frame size must be exactly **512 samples** (32ms @ 16kHz). Model expects torch tensors, not numpy. |
| ASR | `backend/asr/base.py::BaseASR` | `WhisperASR` | Uses Faster-Whisper (CTranslate2). `HF_ENDPOINT` auto-set to `hf-mirror.com` for China network. |
| TTS | `backend/tts/base.py::BaseTTS` | `EdgeTTSAdapter` | Edge-TTS v7 only provides `SentenceBoundary` (not `WordBoundary`). Mouth shapes derived via `pypinyin` final→mouth mapping (A/I/U/E/O). MP3 output converted to WAV via `pydub`. |
| LLM | `backend/llm/base.py::BaseLLM` | Not yet implemented | Abstract with `stream_chat()`, `chat()`, `chat_with_tools()`. Defined but adapter TBD in Phase 3. |

To replace any model: implement the respective base class, then change the `engine` field in config.

### WebSocket Message Protocol

All messages are JSON with `{type, id, timestamp, payload}`. Message routing in `main.py` uses a `MESSAGE_HANDLERS` dict keyed by `type`:

**Frontend → Backend:**
- `audio.chunk` — base64-encoded 16-bit PCM int16 audio frame. Decoded to float32, fed to pipeline.
- `chat.text` — text fallback (echo mode until LLM integrated).
- `user.interrupt` — manual interrupt button.
- `ping` → server responds `pong`.

**Backend → Frontend:**
- `state.change` — session state transitions (broadcast on connect and on every change).
- `asr.result` — `{text, isFinal, confidence}`.
- `llm.stream` — `{text, isFirstChunk, isLastChunk}`.
- `tts.audio` — `{audio: base64 WAV, format, sampleRate, durationMs, phonemes: [{phoneme, startMs, endMs}]}`.
- `live2d.control` — `{command, lipSyncFrames, expression, motion, idleEnabled}`.

### Live2D Mouth-Shape Pipeline

```
TTS text → pypinyin (get finals) → _PHONEME_TO_MOUTH dict → A/I/U/E/O/N
                                                            ↓
                                          MotionController.phonemes_to_lip_sync()
                                          → Cubism parameters (ParamMouthOpenY,
                                            ParamMouthForm, ParamMouthA/I/U/E/O)
```

Emotion detection (`detect_emotion()`) uses keyword lists for happy/sad/surprised/thinking. State-driven expressions: listening→neutral, processing→thinking, interrupted→surprised.

### Configuration System

`backend/config.py` — singleton Config class with layered resolution:
1. Load `config.default.yaml` (committed, safe defaults)
2. Deep-merge `config.user.yaml` (gitignored, user overrides)
3. Resolve `${VAR_NAME}` references from environment variables (`.env` file)

Sensitive fields (containing `api_key` or `secret`) are masked in `GET /api/config`. Access via dot-path: `config.get("llm.openai.model")`.

### Tool System

Tools are declarative Pydantic-based classes inheriting from `Tool` (`backend/tools/base.py`):

- Each tool defines `name`, `description`, `parameters_model()` (returns a Pydantic BaseModel subclass), and `execute(**params)`.
- `parameters_schema` property auto-generates OpenAI function-calling JSON Schema from the Pydantic model.
- `ToolRegistry` (`backend/tools/registry.py`) is a singleton that auto-discovers:
  - Built-in tools from `backend/tools/builtin/*.py` (any class inheriting `Tool`)
  - User tools from `backend/tools/user_tools/*.py` (hot-loaded via `importlib.util`)
- `get_all_schemas()` returns schemas ready for LLM `tools` parameter.
- `get_llm_tools_description()` generates a text description for LLMs without native function calling.
- `execute_tool(name, **params)` validates params through Pydantic, then calls `tool.execute()`.

Adding a new tool means dropping a Python file in `user_tools/` — no other changes needed.

### Meta-Project Extensibility Points

This project is designed as a "meta-project" that users adapt for specific scenarios. The extension points are:

1. **Model replacement**: Implement any Base* abstract class, change config `engine` field
2. **Tool system**: Drop Python files into `backend/tools/user_tools/` — auto-discovered and registered
3. **LLM system prompt**: Edit `config.user.yaml` → `llm.system_prompt` to change personality/behavior
4. **Live2D model**: Swap `live2d.model_path` to a different Cubism model
5. **RAG / knowledge base**: Add tools that query a vector DB
6. **Custom emotions**: Extend `_EMOTION_KEYWORDS` in `motion_controller.py`

### China Network Considerations

- HuggingFace downloads route through `hf-mirror.com` (set in `whisper_adapter.py` as `HF_ENDPOINT` env var)
- GitHub downloads may be blocked — models are cached in `resources/models/` (gitignored)
- Edge-TTS accesses Microsoft's free TTS API (no auth needed, works in China)

### Silero VAD Frame Size

**Critical**: The Silero VAD ONNX model requires exactly **512 samples** at 16kHz (32ms). This is non-negotiable — passing any other frame size causes errors or incorrect results. The `frame_generator()` helper produces correctly-sized frames, and `should_interrupt()` uses a separate detection window (default 4 frames = ~224ms response time).

### Git Workflow

- Feature branches from `master`: `phase{N}-{feature-name}`
- Backend tests run locally before committing (not in CI)
- `resources/models/`, `resources/test_audio/tts_output_*`, `config.user.yaml`, and `backend/tools/user_tools/*` are gitignored
