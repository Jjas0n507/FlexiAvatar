# TODO — 已完阶段遗留 & 后续优化

> 对照 `DESIGN_AND_PLAN.md` 阶段 1-3，记录未完成项、可选跳过项、优化机会。
> 标记说明: ❌ 未做 | ⚠️ 部分/可优化 | 📦 属于后续阶段 | ✅ 已完成
> 最后核对：2026-07-19

---

## 阶段 1 — 基础骨架

### ❌ 缺失

- **`backend/session/context.py`** — 计划中定义的独立对话上下文模块。当前上下文管理直接写在 `AudioPipeline` 中，功能等效但未按计划抽离。如果后续上下文逻辑变复杂（摘要、RAG、多模态），应独立出来。

### ⚠️ 可优化

- **Python 进程管理** — `electron/python-bridge.ts` 已实现健康检查和重启。但没有实现 stdio JSON-RPC 通道（计划中设计的第二层通信）。当前仅靠 HTTP health 轮询，没有优雅关闭指令通路。
- **preload.js 加载失败** — vite-plugin-electron 产物为 ESM，sandbox 按 CJS 执行报 "Cannot use import statement outside a module"。当前无功能依赖 preload（通信全走 WebSocket），确认后删掉或修 format。

---

## 阶段 2 — 语音链路

### ✅ 已补齐（原列缺失）

- **`backend/asr/funasr_adapter.py`** — 已实现且为**主力 ASR**（SenseVoiceSmall，ASR+SER 一模型，非自回归 ~70ms/10s）。Whisper 降为备选。
- **`frontend/src/hooks/useMicCapture.ts`** — 麦克风采集已对接（计划名 useAudioCapture）。
- **`frontend/src/hooks/useAudioPlayback.ts`** — RMS 播放泵已实现（FIFO 队列 + speak 桥 + playback.done）。

### ⚠️ 可优化

- **VAD 参数调优** — 当前 `silence_end_frames=12`（~384ms 静音判定结束），`interrupt_frames=4`（~128ms 打断窗口）。通用值，应根据用户习惯和环境噪音微调。
- **ASR 运行时热切换** — config 可切 whisper/funasr，但无运行时热切换能力。
- **VAD 自适应阈值** — 阈值固定 0.5，没有自动增益或环境自适应。嘈杂环境易误触发。
- **ffmpeg** — funasr/torchaudio 依赖系统 ffmpeg；TTS 链路已不需要（音频直传前端解码）。

### 📦 属于后续阶段（暂划 Phase 6）

- **TTS 声音选择 + 试听 UI**、**ASR 引擎切换 UI**、**麦克风设备选择**

---

## 阶段 3 — LLM 对接

### ✅ 已补齐（原列缺失）

- **`backend/llm/ollama_adapter.py`** — 已实现且为当前主力（Docker 内 qwen2.5:7b）。
- **LLM 后端切换** — 已工厂化（`adapters.py::create_llm`），config 切换 openai/ollama。
- **流式 TTS 首句策略** — `Segmenter` 已实现（`min_segment_length=15` + 首句宽标点集提前切）。

### ❌ 缺失

- **`backend/llm/claude_adapter.py`** — 计划中标注为"可选"，未实现。

### ⚠️ 部分/可优化

- **工具调用实测** — `chat_with_tools()` 代码完整，但真正的 tool-calling 循环要等 Phase 5 工具系统就绪后实测。
- **对话历史 token 预算** — 当前按消息数量裁剪（`max_history_messages=20`），`max_context_tokens` 级预算未实现。
- **上下文自动摘要** — 未实现。

---

## 阶段 4 — Live2D 角色集成（已重做，历史项作废）

> 2026-07 语音重做（PR #4）**整体废除**了原音素/时间线架构：prosody、syllable_detector、
> mouth_shapes、phoneme 时间轴、timeline 消息全部删除，口型改为前端 RMS 音量驱动
> （`<audio>` 播放 + OfflineAudioContext 解码 + beforeModelUpdate 每帧写参）。
> 渲染器由 live2d-renderer 换为 pixi-live2d-display@0.4.0。
> 原"timeline command 前端处理 / TimelineEntry 类型"等待办随架构一并作废。

### ✅ 现存有效资产

- **ModelProfile 抽象层**（`model_profile.py` + yaml，前后端共享契约）
- **MotionController**（表情/打断部分保留；时间轴函数已删）
- **SenseVoice SER 语音情绪融合**（`get_expression_for_text` 双路径：语音情绪优先，文本关键词兜底）

### ⚠️ 可优化

- **IdleBehaviorScheduler 前端集成** — 后端 `idle_scheduler.py` 就绪但未接前端；前端目前用自己的自主表情定时器。二选一收敛（后端调度删掉或前端接上），避免双头。
- **清理 live2d-renderer 残留** — `package.json` 依赖 + `frontend/scripts/patch-live2d.cjs` 待删（见 NEXT.md 高优先级）。

---

## 跨阶段 — 通用

### ❌ 缺失

- **`docs/` 文档** — 已有 `live2d-fps-collapse-postmortem.md`；计划中的 `tool-development.md`、`live2d-setup.md`、`troubleshooting.md` 仍未创建。
- **`backend/tools/builtin/`** — 目录不存在，4 个内置工具 (`time_tool`, `weather_tool`, `calculator`, `web_search`) 均未实现。属于 Phase 5。`ToolRegistry.discover_builtin_tools()` 对目录缺失是静默失败，应改为明显警告。
- **日志文件输出** — 日志仅控制台，无文件持久化。长时间运行调试时需要。
- **`.env.example` / `config.user.yaml.example`** — 均未提供，新开发者引导缺失。

### ⚠️ 可优化

- **错误处理** — LLM API 请求未设 timeout；"异常状态自动恢复 (any → IDLE)"仅有 try/except 兜底，无超时/重试。
- **启动体验** — TTS 已启动预加载（~10s 后台完成）；ASR warmup 仍在首个连接时触发（funasr 快，影响小）。"启动画面 + 加载进度"未实现（Phase 6）。
- **架构约束（教训固化）** — WS 消息处理器**不得在接收循环里同步 await `respond()`**（playback.done 只能从该循环读出，同步等待=自死锁）。文字/语音路径现均为 `create_task`，新增消息类型时注意。

---

## 优化机会（技术债偿还）

| 项目 | 优先级 | 描述 |
|------|--------|------|
| 段间死寂 | 中 | CosyVoice 短句 RTF>1，句间 2-5s 静默。短期调大 `min_segment_length`；终极 `stream=True` 流式（见 NEXT.md） |
| TTS 缓存 | 低 | 常用短语（"你好"、"好的"）可缓存 TTS 结果，避免重复合成。 |
| VAD 帧大小检查 | 低 | `SileroVAD.frame_generator()` 丢弃不足 512 samples 的末尾帧且无警告。 |
| WebSocket 心跳 | 低 | 当前前端主动 ping。可改后端主动 ping 检测断线。 |
| `.env.example` | 中 | 为新开发者提供模板，列出所有环境变量（含 MKL-OpenMP 冲突说明）。 |
