# 当前开发状态

> ⚠️ 此文件记录**动态**信息，每次切换工作内容时更新。
> 最后更新：2026-07-05

## 当前位置

- **分支**: `phase4-live2d`（从 `phase3-streaming-pipeline` 切出）
- **阶段**: Phase 4 — Live2D 角色集成（基本完成）
- **进度**: 全链路已验证通过，Live2D 自主运动已实现

## 最近提交

```
056bae2 docs: simplify CLAUDE.md for team sharing, add STATUS.md/NEXT.md for dynamic progress tracking
35f1179 docs: add TODO.md tracking gaps across Phases 1-3
02f2797 fix(config): load .env from project root, read OPENAI_API_KEY/BASE_URL from env
b9f4e6f feat(tts): add streaming synthesis (sentence-by-sentence)
a3987ea feat(asr): add streaming transcription support
```

## Phase 4 已完成

1. **Live2D 渲染**: 使用 `live2d-renderer` (npm) 加载 Cubism 3 模型（有马加奈）
2. **模型集成**: `resources/有马加奈` → `frontend/public/live2d/有马加奈/`
3. **口型同步**: 后端 `MotionController` 生成帧 → WebSocket → 前端 `setTimeout` 驱动 `ParamMouthOpenY` + `ParamMouthForm`
4. **表情系统**: 状态驱动（processing → thinking, interrupted → surprised）+ 空闲自主切换（5-12s 间隔）
5. **动作系统**: `live2d-renderer` 内置 `MotionController` 自动循环 `randomMotion`，`Idle` 优先级
6. **自动动画**: 呼吸、眨眼、物理模拟由 Cubism SDK 自动处理
7. **自主运动**: 关闭鼠标跟随（`autoInteraction: false`），靠内置 motion 循环 + 自主表情定时器实现
8. **语音全链路**: 文本→LLM(DeepSeek)→TTS(Edge-TTS)→Live2D 口型 + 音频播放，端到端验证通过
9. **麦克风采集**: `useMicCapture` hook，16000Hz/单声道/512 sample frames

## Phase 4 期间修复的 Bug

| 问题 | 根因 | 修复 |
|------|------|------|
| 状态变更不广播 | `on_transition` 只记日志 | 加入 `broadcast_state()` 调用 (`main.py:60`) |
| 前端 WS 不响应 | `wsClient.isConnected` 是非 reactive getter | 改为 Zustand store 订阅 (`useWebSocket.ts:129`) |
| Live2D CubismCore 不加载 | CDN WASM 404 + Emscripten 异步初始化 | 本地部署 JS + 100×100ms 轮询 (`Live2DCanvas.tsx:31-49`) |
| TTS 异常导致状态卡死 | `NoAudioReceived` 异常未捕获 | try/except 包裹 TTS 循环，单句失败跳过 (`main.py:228-241`) |
| ffmpeg 缺失 | 系统未安装 | conda install 到 ai-agent env |

## 架构决策

1. 使用 `live2d-renderer` (Moebytes) 而非手动集成 Cubism SDK — 减少 80% 样板代码
2. 此模型使用 `ParamMouthOpenY` + `ParamMouthForm` 组合口型参数，而非标准 A/I/U/E/O 独立参数
3. Cubism Core WASM 从本地 `public/live2d/` 加载（JS 内含 asm.js fallback）
4. `live2d.control` WebSocket 消息格式：后端 snake_case (`lip_sync`)，前端 TS 类型已对齐
5. 自主运动方案：`randomMotion: true` + `enableMotion: true` 利用 live2d-renderer 内置循环，加前端定时器切换表情

## 已知问题（高优先级）

1. **延迟极高**: 用户输入到回复延迟大。首轮 ASR 模型（Whisper base）加载需 ~50s，后续回合 ~10s。Edge-TTS 网络延迟不稳定。
2. **口型与语音不同步**: 口型用 `setTimeout` 帧序列播放，未与 `AudioContext.currentTime` 同步，视觉上口型与听到的声音有偏差。

详见 `TODO.md`。