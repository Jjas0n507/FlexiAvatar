# TODO — 已完阶段遗留 & 后续优化

> 对照 `DESIGN_AND_PLAN.md` 阶段 1-3，记录未完成项、可选跳过项、优化机会。
> 标记说明: ❌ 未做 | ⚠️ 部分/可优化 | 📦 属于后续阶段

---

## 阶段 1 — 基础骨架

### ❌ 缺失

- **`backend/session/context.py`** — 计划中定义的独立对话上下文模块。当前上下文管理直接写在 `AudioPipeline` 中，功能等效但未按计划抽离。如果后续上下文逻辑变复杂（摘要、RAG、多模态），应独立出来。

### ⚠️ 可优化

- **Python 进程管理** — `electron/python-bridge.ts` 已实现健康检查和重启。但没有实现 stdio JSON-RPC 通道（计划中设计的第二层通信）。当前仅靠 HTTP health 轮询，没有优雅关闭指令通路。

---

## 阶段 2 — 语音链路

### ❌ 缺失

- **`backend/asr/funasr_adapter.py`** — 计划首选 FunASR SenseVoiceSmall，实际实现了 Whisper。FunASR 已安装，模型已下载，但适配器未写。SenseVoiceSmall 在 CPU 上 RTF ~0.26x（和 tiny 持平），且中文识别率更高。**建议后续补上作为可选项。**

- **`frontend/src/hooks/useAudioCapture.ts`** — 计划中的麦克风捕获 hook。当前测试时音频来自 WAV 文件，前端尚未对接真实麦克风采集。

- **`frontend/src/hooks/useAudioPlayback.ts`** — 计划中的音频播放 hook。当前 TTS 输出通过 WebSocket 发送到前端，但前端没有对应的播放逻辑。

- **ffmpeg** — Edge-TTS 返回 MP3，`pydub` 需要 ffmpeg 转 WAV。当前 Windows 环境未安装，导致 `test_tts.py` 失败。安装方式：
  ```bash
  winget install ffmpeg   # 或从 https://ffmpeg.org/download.html 下载
  ```

### ⚠️ 可优化

- **VAD 参数调优** — 当前 `silence_end_frames=12`（~384ms 静音判定结束），`interrupt_frames=4`（~128ms 打断窗口）。这些值是通用的，实际使用中应根据用户习惯和环境噪音微调。

- **ASR 模型选择** — 当前默认 `base`（RTF 0.44x），用户可在 `config.user.yaml` 切换 `tiny`（RTF 0.27x，更快但略有错）或 `small`（RTF 1.36x，实时勉强）。没有运行时热切换能力。

- **VAD 自适应阈值** — 计划中提到"嘈杂环境误触发"风险。当前阈值固定 0.5，没有自动增益或环境自适应。

### 📦 属于后续阶段（暂划 Phase 6）

- **TTS 声音选择 + 试听 UI** (Phase 6 — 设置面板)
- **ASR 引擎切换 UI** (Phase 6 — 设置面板)
- **麦克风设备选择** (Phase 6)

---

## 阶段 3 — LLM 对接

### ❌ 缺失

- **`backend/llm/ollama_adapter.py`** — 计划中的本地 LLM 适配器。Ollama 兼容 OpenAI API（`/v1/chat/completions`），实际上 OpenAIAdapter 改 `base_url` 就能用，但仍需独立的健康检查、模型列表等功能。**建议 Phase 5/6 补充。**

- **`backend/llm/claude_adapter.py`** — 计划中标注为"可选"，未实现。Anthropic Messages API 与 OpenAI 格式不同，需独立适配器。

### ⚠️ 部分/可优化

- **流式 TTS 首句策略** — 计划中"首句优先：超过 15 字或遇到句号就立即合成"。当前实现为逐句串行合成，没有 15 字阈值和优先队列。LLM 生成长文本时，第一句话要等 LLM 写完一整句才开始 TTS。

- **工具调用实测** — `chat_with_tools()` 代码完整，但仅在单元测试中验证了 `stream_chat()`。真正的 tool-calling 循环要等 Phase 5 工具系统就绪后实测。

- **LLM 后端切换** — 抽象基类 `BaseLLM` 支持多适配器，但 pipeline 中硬编码了 `OpenAIAdapter`（第 68 行）。切换 Ollama 需要改 pipeline 代码，而非仅改配置。

- **对话历史 token 预算** — 当前按消息数量裁剪（`max_history_messages=20`），计划中还有 `max_context_tokens=4000` 的 token 级预算未实现。对于长对话，消息数限制不等于 token 限制。

- **上下文自动摘要** — 计划中提到超长对话自动摘要，未实现。

### 📦 属于后续阶段

- **前端对话气泡 + ChatBubble 动画** (Phase 6)
- **LLM 调用进度指示** (Phase 5/6)

---

## 跨阶段 — 通用

### ❌ 缺失

- **`docs/` 目录** — 计划中的 `tool-development.md`、`live2d-setup.md`、`troubleshooting.md` 均未创建。

- **`backend/tools/builtin/`** — 工具基类和注册中心已就绪，但计划中的 4 个内置工具 (`time_tool`, `weather_tool`, `calculator`, `web_search`) 均未实现。属于 Phase 5。

- **`backend/tools/user_tools/`** — 目录不存在。用户自定义工具的热加载逻辑在 registry 中已实现，但没有目录就无法工作。

- **前端 Live2D 组件** — `Live2DCanvas.tsx`、`Live2DModel.ts`、`LipSyncEngine.ts`、`ExpressionController.ts`、`useLive2D.ts` 均未实现。属于 Phase 4。后端 `motion_controller.py` 已就绪。

- **日志文件输出** — 当前日志仅输出到控制台（`logging.basicConfig`），没有文件持久化。长时间运行调试时需要。

### ⚠️ 可优化

- **错误处理** — 计划中要求"所有外部 API 调用加超时 + 重试"、"异常状态自动恢复 (any → IDLE)"。当前 `_process_speech()` 有 try/except 兜底，但没有超时/重试逻辑。LLM API 请求未设 timeout。

- **启动体验** — 计划中"启动画面 + 模型加载进度"未实现。ASR 模型 warmup 需要 22 秒，用户在此期间看不到任何反馈。

- **MKL-OpenMP 冲突** — 已在 `whisper_adapter.py` 和 `test_asr.py` 中修复，但 `.env.example` 中未记录。建议添加注释说明此已知问题。

- **工具注册中心** — `test_basic.py` 输出 `0 tools, 0 schemas`。`ToolRegistry` 的 `discover_builtin_tools()` 尝试 `import backend.tools.builtin` 但目录不存在会静默失败。应改为更明显的警告。

### 📦 属于后续阶段

- **Electron 打包** (Phase 6)
- **系统托盘 + 全局快捷键** (Phase 6)
- **设置面板 UI** (Phase 6)
- **连续 30 分钟稳定性测试** (Phase 6)

---

## 优化机会（技术债偿还）

| 项目 | 优先级 | 描述 |
|------|--------|------|
| ASR 模型预加载时机 | 中 | 当前 warmup 在第一个 WebSocket 连接时触发（22s）。改为启动时后台预加载可消除首次对话延迟。 |
| TTS 缓存 | 低 | 常用短语（"你好"、"好的"）可缓存 TTS 结果，避免重复合成。 |
| VAD 帧大小检查 | 低 | `SileroVAD.frame_generator()` 会丢弃不足 512 samples 的末尾帧，但没有警告。应添加。 |
| WebSocket 心跳 | 低 | 计划要求 10s ping/pong，实际是前端主动 ping。应改为后端主动发 ping 检测断线。 |
| `.env.example` | 中 | 应为新开发者提供 `.env.example` 模板，列出所有需要的环境变量。 |
| `config.user.yaml.example` | 低 | 提供一个示例用户配置文件，展示如何覆盖默认值。 |

---

## 下一步：Phase 4 (Live2D)

Phase 4 尚未开工，以下是从计划中提取的高层任务：

1. 前端集成 Cubism SDK + 加载模型
2. 口型同步引擎（接收 `motion_controller.py` 的音素帧）
3. 表情系统（neutral/happy/thinking/surprised/sad）
4. 身体动作（呼吸、眨眼、状态触发动作）
5. 交互优化（点击触发、视线追踪）

> 参见 `DESIGN_AND_PLAN.md` 第 1543-1624 行获取完整计划。
