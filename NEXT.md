# 下一步行动

> ⚠️ 此文件记录**短期**待办，完成后划掉或删除。
> 最后更新：2026-07-19

## 当前优先级

### 🔴 高优先级

- [ ] **用户听感验收**: CosyVoice 音色是否满意（换音色 = 换 3-10s 参考音频 + 文本，config 两行）；段间死寂是否可接受；比心是否两只手；情绪句是否出害羞/哭泣表情
- [ ] **Dockerfile 固化 CosyVoice 层**: 当前容器内手工安装（clone `/opt/CosyVoice` + pip 依赖 + `cosyvoice.pth` + `setuptools<81` + `load_wav` soundfile 补丁），**recreate 即失**。需写进 Dockerfile
- [ ] **依赖清理**: 删 `pydub`/`pypinyin`（requirements.txt + Dockerfile）；删 `live2d-renderer` 依赖 + `frontend/scripts/patch-live2d.cjs`（已换 pixi-live2d-display）
- [ ] **push `phase-cosyvoice-tuning` + PR**（以上完成后一并收尾）

### 🟡 中优先级

- [ ] **段间死寂缓解**（CosyVoice 短句 RTF>1，首句后 2-5s 静默）: 短期 `tts.streaming.min_segment_length` 15→25（段长摊薄 RTF，代价 TTFA +1-2s）；终极方案 CosyVoice `stream=True` 分块流式 + 前端流式播放（注意：稳态 RTF<1 才不卡顿，需实测）
- [ ] **preload.js 加载失败**: "Cannot use import statement outside a module"（vite-plugin-electron 产物 ESM vs sandbox CJS）。当前无功能依赖 preload，确认后删掉或修 format
- [ ] `ScriptProcessorNode` → `AudioWorklet`（麦克风采集，已弃用 API）
- [ ] 模型 `随机姿势.motion3.json` 7MB，首帧加载延迟
- [ ] 口型美观微调: RMS 同时驱动 `ParamMouthForm` 若怪异 → 从 model3.json LipSync 组移除该参数（改资产零代码）

### 🟢 技术债

- [ ] 表情切换加平滑过渡（lerp 参数值而非直接设）
- [ ] Electron 打包集成测试
- [ ] useWebSocket exhaustive-deps lint warning（zustand setter 实际稳定，可静默或补依赖）

### 已完成 ✅（本阶段）

- [x] 同步链路重做（RMS 口型架构）+ pixi-live2d-display 渲染器（PR #4）
- [x] CosyVoice2 适配器 + config 激活 + ref 剪裁（3.84s funasr 验证）
- [x] 重模型进程单例 + TTS 启动预加载（TTFA 25s→~6s）
- [x] playback.done 定案：后端接收循环自死锁 + 前端孤儿 socket + speak 看门狗（d04cf27）
- [x] 比心四只手（motion3.json 资产修复）、害羞/哭泣表情恢复（废除清零机制）
- [x] dev 排查口：Electron CDP :9223 + `window.__wsClient`（仅 isDev）

### 下一阶段（Phase 5 — 工具系统）

- [ ] 后端工具系统已就位（`backend/tools/`），待集成测试
- [ ] LLM 工具调用端到端验证
- [ ] 天气、时间、计算等内置工具完善（`backend/tools/builtin/` 目录待建）

### 下一阶段（Phase 6 — 前端完善）

- [ ] 前端对话气泡 + ChatBubble 动画
- [ ] 设置面板 UI（声音/模型/ASR 选择）
- [ ] Electron 打包 + 系统托盘 + 全局快捷键
- [ ] 启动画面 + 模型加载进度
