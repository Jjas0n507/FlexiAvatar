# 当前开发状态

> ⚠️ 此文件记录**动态**信息，每次切换工作内容时更新。
> 最后更新：2026-07-16

## 当前位置

- **分支**: `master`
- **阶段**: Phase 4 完成 → 全部 4 阶段已完成
- **进度**: 全链路已验证通过，Live2D 动画系统全面升级完成（76 tests passing）

## 最近提交

```
a6e8555 feat: Phase 4 集成清理 — unified build_timeline_message, requirements.txt 取消注释, progress memory 更新
f073cf8 feat: Phase 3 空闲行为调度器 — IdleBehaviorScheduler (眨眼/视线漂移/歪头/表情循环)
1b7761f feat: Phase 2 分段情绪时间线 — _split_text_to_segments, build_timeline_message 含口型+表情混合时间线
5a830e7 feat: Phase 1 顺滑口型+韵律 — Phoneme.char/volume, 去强制N帧, prosody.py RMS, 音量驱动口型缩放
84cf542 feat: Phase 0.7 frontend + 0.8 — ModelProfile WS message,前端从 profile 读取所有硬编码值
```

## Live2D 动画升级 — 全部完成 ✅

参考计划: `docs/live2d-animation-upgrade-plan.md`

| Phase | 内容 | 测试数 | 状态 |
|-------|------|--------|------|
| 0 | 模型解耦 (mouth_shapes, ModelProfile, MotionController 重构, 前端 profile 驱动) | 34 | ✅ |
| 1 | 顺滑口型+韵律 (char/volume, 智能闭口, RMS 音量, 缩放) | +21 | ✅ |
| 2 | 分段情绪时间线 (build_timeline_message 混合口型+表情) | +9 | ✅ |
| 3 | 空闲调度器 (IdleBehaviorScheduler: 眨眼/视线/歪头/表情循环) | +12 | ✅ |
| 4 | 集成清理 (统一 timeline, requirements.txt) | — | ✅ |

### 关键成果

1. **ModelProfile 契约层**: YAML 驱动模型配置，前后端共享同一份数据，换模型只需新 YAML
2. **智能口型同步**: 去强制 N 帧，短 gap 自然插值，标点强制闭口，RMS 音量驱动缩放
3. **分段情绪**: 文本按标点切分独立检测情绪，混合口型+表情 time-sorted timeline
4. **空闲调度器**: tick(dt) 驱动眨眼/视线漂移/歪头/表情循环，后端生成指令
5. **向后兼容**: 所有新代码保留 hardcoded fallback (profile=None)

### 新增文件 (7)

```
backend/live2d/mouth_shapes.py, model_profile.py, idle_scheduler.py
backend/audio/__init__.py, prosody.py
tests/test_phoneme.py, test_prosody.py, test_idle_scheduler.py
```

## Phase 4 已完成（基础 Live2D 集成）

1. **Live2D 渲染**: 使用 `live2d-renderer` (npm) 加载 Cubism 3 模型（有马加奈）
2. **口型同步**: 后端 `MotionController` 生成帧 → WebSocket → 前端驱动口型参数
3. **表情系统**: 状态驱动 + 文本情绪检测 + 空闲自主切换
4. **动作系统**: `randomMotion: true` + profile 驱动的 motion group 选择
5. **自动动画**: 呼吸、眨眼、物理模拟由 Cubism SDK 自动处理
6. **语音全链路**: 文本→LLM→TTS→Live2D 口型 + 音频播放，端到端验证通过

## 架构决策

1. 使用 `live2d-renderer` (Moebytes) 而非手动集成 Cubism SDK — 减少 80% 样板代码
2. ModelProfile 抽象层 — 模型参数 ID/口型值/表情/动作全部 YAML 配置
3. MotionController 单例注入 AudioPipeline — 消除双实例
4. 口型同步使用 setTimeout 方案（50ms 偏差无感知），后续可选 AudioContext 升级
5. 自主运动: `randomMotion: true` + `enableMotion: true` + idle scheduler 指令

## 已知问题（高优先级）

1. **延迟极高**: ASR Whisper base 模型加载 ~50s，后续 ~10s。Edge-TTS 网络延迟不稳定。
2. **口型与语音不同步**: 口型用 `setTimeout` 帧序列播放，未与 `AudioContext.currentTime` 同步。

详见 `TODO.md`。
