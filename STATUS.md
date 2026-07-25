# 当前开发状态

> ⚠️ 此文件记录**动态**信息，每次切换工作内容时更新。
> 最后更新：2026-07-25

## 当前位置

- **分支**: `master`
- **阶段**: Persona 配置化性格系统已完成；CosyVoice2 本地音色克隆 + playback.done 上行链路定案
- **进度**: 性格设置 0→1（`config.user.yaml` 覆盖 persona 段，换人设不改代码）；待用户听感验收 → 后续记忆系统

## 最近提交

```
a8e0b50 feat(persona): 可替换性格设置 — system prompt 模板化 + emotion map 覆盖
5a492d7 Merge pull request #5 from Jjas0n507/phase-cosyvoice-tuning
d04cf27 fix: playback.done 双重上行断路 — 后端接收循环自死锁 + 前端孤儿 socket
```

## 本轮核心变化

### Persona 配置化性格系统（2026-07-25）

- `backend/llm/persona.py`: `build_system_prompt()` XML 七层结构化 prompt 组装
- `config.default.yaml`: 新增 `persona` 配置段（默认小助手人设）
- `config.user.yaml` 覆盖即可换人设，**不改代码**；空时回退 `llm.system_prompt`
- `motion_controller.py`: `detect_emotion()` + `MotionController` 支持 `emotion_expression_map` 覆盖（如傲娇人设 `happy→smug`）
- README 新增 persona 字段说明 + 傲娇猫娘完整示例

### CosyVoice2 激活（config 切换，edge-tts 保留为零 GPU 备选）

- `config.user.yaml`: `tts.engine: cosyvoice2`，ref 音频剪至 3.84s（`ref_short.wav`，funasr 验证文本）
- 重模型进程单例（`adapters.py::_cached`）：多 WS 客户端共享，杜绝重复加载
- 启动后台预加载（`main.py::_preload_tts`）：TTFA 25s → ~5-6.5s
- 实测：短句 RTF ~1.5-2，长句 ~0.7-1.0（每次合成有固定 prompt 开销，长段摊薄）

### playback.done 定案（历史遗留 100% 假超时）

1. **后端自死锁（主因）**: `handle_chat_text` 在 WS 接收循环里同步 `await respond()`，done 只能从被堵死的同一循环读出 → 改 `create_task` + IDLE 门卫
2. **前端孤儿 socket（副因）**: StrictMode 双挂载重复 connect，旧 socket 能收不能发 → connect 幂等 + 回调身份守卫
3. respond() 只认最后一段发出后的 done（RTF>1 时排空间隙的防抖 done 是中间信号）
4. `speak()` 时长看门狗：onended 丢失不再永久卡死播放泵

详见 `docs/live2d-fps-collapse-postmortem.md` 补记。

## 已知残留

1. **段间死寂**（听感似截断）: CosyVoice 短句 RTF>1，首句播完后 2-5s 静默才等到下一句。缓解选项：`min_segment_length` 调大 / `stream=True` 流式（见 NEXT.md）
2. **容器内 CosyVoice 安装未固化**: restart 幸存，**recreate 即失**（Dockerfile 待补层）
3. **preload.js 加载失败**（ESM/CJS 冲突），当前功能未依赖 preload，影响面待查

详见 `NEXT.md` / `TODO.md`。

## 上一轮核心变化
