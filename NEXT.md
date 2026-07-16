# 下一步行动

> ⚠️ 此文件记录**短期**待办，完成后划掉或删除。
> 最后更新：2026-07-16

## 当前优先级

### 🔴 高优先级

- [ ] **输入→回复延迟优化**: 首轮 ASR Whisper base 模型加载 ~50s，后续 ~10s。方案：启动时预加载模型（`_init_engines()` 在 startup 调用）、Edge-TTS 考虑备选（Azure TTS / 本地模型）
- [ ] **口型-语音同步**: 当前用 `setTimeout` 帧序列独立播放，与 `AudioContext.currentTime` 无关联。方案：前端收到 TTS WAV + phonemes 后，用 `AudioContext` 解码播放，口型帧绑定 `currentTime` 偏移量

### 🟡 中优先级

- [ ] JS bundle code splitting（live2d-renderer 懒加载，584KB）
- [ ] `ScriptProcessorNode` → `AudioWorklet`（麦克风采集，已弃用 API）
- [ ] 模型 `随机姿势.motion3.json` 7MB，首帧加载延迟

### 🟢 技术债

- [ ] 表情切换加平滑过渡（lerp 参数值而非直接设）
- [ ] WebSocket 断线自动重连 + 指数退避（已实现基础版）
- [ ] Electron 打包集成测试
- [ ] 前端 `live2d.control` `timeline` command 处理（后端已发 timeline，前端仍用旧 switch/case）

### 已完成 ✅

- [x] **Live2D 动画系统全面升级** (Phase 0-4, 76 tests)
  - ModelProfile 模型解耦、拼音表统一、MotionController 重构
  - 顺滑口型 (去强制N帧) + RMS 音量驱动缩放
  - 分段情绪时间线 (build_timeline_message)
  - IdleBehaviorScheduler 空闲行为调度器
  - 前端从 profile 读取所有值，完全消除硬编码

### 下一阶段（Phase 5 — 工具系统）

- [ ] 后端工具系统已就位（`backend/tools/`），待集成测试
- [ ] LLM 工具调用端到端验证
- [ ] 天气、时间、计算等内置工具完善

### 下一阶段（Phase 6 — 前端完善）

- [ ] 前端对话气泡 + ChatBubble 动画
- [ ] 设置面板 UI（声音/模型/ASR 选择）
- [ ] Electron 打包 + 系统托盘 + 全局快捷键
- [ ] 启动画面 + 模型加载进度
