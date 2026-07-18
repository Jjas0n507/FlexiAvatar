# 当前开发状态

> ⚠️ 此文件记录**动态**信息，每次切换工作内容时更新。
> 最后更新：2026-07-18

## 当前位置

- **分支**: `phase-voice-upgrade`
- **阶段**: 语音+Live2D 同步链路重做（RMS 口型架构）
- **进度**: 后端+前端已提交，协议级 E2E 通过；待 Electron 视觉验证 → 删依赖 → CosyVoice2 适配器

## 最近提交

```
41b5e74 feat(rework 3): frontend RMS playback engine — library lipsync + FIFO pump
3e309c4 feat(rework 1+2): RMS lip-sync backend — delete phoneme machinery, unified respond() pipeline
c534205 fix: remove double model.update() — library autoAnimate already renders
```

## 同步链路重做 — 核心变化

旧架构（已删）：后端估算音素时间轴（pypinyin + 音节检测/均匀分布）→ 前端另一个时钟对齐 → 永远失步。
新架构：**RMS 音量驱动** — `tts.audio` 直传原始 MP3 → 前端 `model.inputAudio()`（live2d-renderer 内置：decodeAudioData + 播放 + 每帧 RMS 驱动 LipSync 参数）。音频和口型读同一份采样数据。

1. **失步根除**: 口型不依赖任何时间戳/时钟对齐，引擎无关 → TTS 可自由替换
2. **截断修复**: 前端 FIFO 队列泵（不再互踩）；后端 worker try/finally 必投递、失败句占位、消费者 sentinel 收尾
3. **统一管线**: 语音/文字聊天共用 `AudioPipeline.respond()`，都等 `playback.done`（删 sleep 估算）
4. **打断**: utteranceId 标记 + `stopAll()`（停音频 + 清 `wavController.samples` 防无声空翻）
5. **净删 ~2000 行**: prosody/syllable_detector/mouth_shapes/timeline/诊断模块全删

计划文档: 见 `~/.claude/plans/sequential-coalescing-river.md`（本机）；测试: 61 passing（Docker 内跑）

## 待办（按序）

1. Electron 视觉验证（口型/FPS≥55/打断即停）→ 确认后删 `pydub`/`pypinyin` 依赖
2. CosyVoice2 适配器（Apache 2.0，真流式，3s 零样本克隆；默认引擎仍 edge-tts，config 切换）

## 已知问题（高优先级）

1. **延迟极高**: ASR Whisper base 模型加载 ~50s（后续 ~10s）。已有 funasr(SenseVoice) 备选。

详见 `TODO.md`。
