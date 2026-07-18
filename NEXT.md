# 下一步行动

> ⚠️ 此文件记录**短期**待办，完成后划掉或删除。
> 最后更新：2026-07-18

## 当前优先级

### 🔴 高优先级

- [ ] **Electron 视觉验证**（重做后首次）: 口型随音量动、多句无重叠无卡顿、打断即停（含口型）、FPS≥55 → 通过后删 `pydub`/`pypinyin`（requirements.txt + Dockerfile）
- [ ] **CosyVoice2 适配器**: `backend/tts/cosyvoice_adapter.py`，ModelScope `iic/CosyVoice2-0.5B`，零样本克隆（ref wav + ref text），config `tts.engine: cosyvoice2` 切换；后续可用 `stream=True` 真流式再降 TTFA
- [ ] **输入→回复延迟优化**: 首轮 ASR Whisper base 模型加载 ~50s，后续 ~10s。方案：启动时预加载模型（`_init_engines()` 在 startup 调用）

### 🟡 中优先级

- [ ] JS bundle code splitting（live2d-renderer 懒加载，584KB）
- [ ] `ScriptProcessorNode` → `AudioWorklet`（麦克风采集，已弃用 API，主线程占用影响 FPS）
- [ ] 模型 `随机姿势.motion3.json` 7MB，首帧加载延迟
- [ ] 口型美观微调: RMS 同时驱动 `ParamMouthForm` 若怪异 → 从 model3.json LipSync 组移除该参数（改资产零代码）；`lipsyncSmoothing` 构造参数可调平滑度

### 🟢 技术债

- [ ] 表情切换加平滑过渡（lerp 参数值而非直接设）
- [ ] WebSocket 断线自动重连 + 指数退避（已实现基础版）
- [ ] Electron 打包集成测试
- [ ] 锁定 `live2d-renderer` 精确版本（stop 桥依赖其公开字段 `wavController.samples`）

### 已完成 ✅

- [x] **同步链路重做（RMS 口型架构）**: 删除音素时间轴整条链路，`tts.audio` 直传 MP3 → 前端 `model.inputAudio()` 内置 RMS 口型；语音/文字统一 `respond()` 管线；utteranceId 打断丢弃。详见 STATUS.md

### 下一阶段（Phase 5 — 工具系统）

- [ ] 后端工具系统已就位（`backend/tools/`），待集成测试
- [ ] LLM 工具调用端到端验证
- [ ] 天气、时间、计算等内置工具完善

### 下一阶段（Phase 6 — 前端完善）

- [ ] 前端对话气泡 + ChatBubble 动画
- [ ] 设置面板 UI（声音/模型/ASR 选择）
- [ ] Electron 打包 + 系统托盘 + 全局快捷键
- [ ] 启动画面 + 模型加载进度
