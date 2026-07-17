# 语音交互升级计划：延迟 · 口型同步 · 性格 · 记忆

> 依据：`docs/amadeus-report.docx`、`docs/ZerolanLiveRobot_技术报告.docx`、`docs/ZerolanLiveRobot_唇同步深度技术报告.docx` 三份报告的对照分析。
> 制定日期：2026-07-18
> 状态：待实施
>
> 分支约定：每个 Phase 从 `master` 拉 `phase{N}-{name}` 分支，完成并通过测试后合并。
> 测试约定：单元测试在 Docker 内跑（`docker compose exec backend python -m pytest tests/ -v`），集成/E2E 需后端运行。

---

## 现状诊断（一句话版）

| 维度 | 现状 | 根因位置 |
|---|---|---|
| 延迟 | LLM 流式但 TTS 等全文生成完才开始（"半流式"） | `backend/audio_pipeline.py:226-264` |
| 口型不同步 | ① 前后端疑似消息类型不匹配 ② 口型用 wall clock 对齐而非音频时钟 ③ 无插值过渡 | `backend/main.py:167` / `frontend/src/components/Live2DCanvas.tsx:479-516` |
| 性格 | 仅一段简单 system_prompt，无 persona 概念 | `backend/config.default.yaml:64-67` |
| 记忆 | 仅内存 `_history`，按 20 条裁剪，无持久化 | `backend/audio_pipeline.py:63,212-218` |

**已做对、无需改动的部分**：SenseVoice ASR+SER 一模型出情绪（避开了两个开源项目"额外 LLM 情感分析 +1~3s"的坑）；pypinyin 韵母→A/I/U/E/O/N 的音素级口型方案（比两个项目的 RMS 响度驱动高两个等级，L3 vs L0）。

---

## Phase A（P0）：修复音频消息协议不匹配 — 半天

**问题**：后端发送 `tts.audio`（`backend/main.py:167`），前端只监听 `tts.speech`（`frontend/src/hooks/useWebSocket.ts:109`）。AudioContext 播放路径可能收不到任何音频消息，这可能是当前不同步（甚至链路异常）的直接原因。

**步骤**：

- [ ] 复现确认：启动前后端，说一句话，在浏览器 DevTools 里确认 `tts.audio` 消息是否被丢弃、声音实际从哪条路径播出。
- [ ] 统一消息类型：二选一（推荐改前端，后端命名与 CLAUDE.md 文档一致）：
  - 前端 `useWebSocket.ts:109` 增加/改为监听 `tts.audio`；
  - 同步检查 `frontend/src/types/index.ts` 中消息类型定义。
- [ ] 回归：`tests/test_e2e_voice.py`（需后端运行）。

**验收**：前端 `useAudioPlayback` 路径确实收到音频并经 AudioContext 播放；口型 timeline 与音频出自同一次消息往返。

---

## Phase B（P0）：LLM 流式分句 → TTS 提前提交 — 1~2 天

**目标**：首句可听延迟从「全文 LLM + 首句 TTS」降为「首句 LLM + 首句 TTS」。Zerolan 报告估算此类优化可将首句延迟从 ~4.3s 降至 ~1.5s，是全链路最大杠杆。

**方案**（借鉴 Amadeus §2.2「按标点分句 + TTS 提前提交」）：

1. 在 `_process_speech()` 的 `stream_chat` 循环（`backend/audio_pipeline.py:226-241`）内做**增量分句**：
   - 维护 `pending_text` 缓冲，每收到 chunk 追加；
   - 满足「长度 ≥ `min_segment_length`（默认 15 字）且以 `。！？!?；;\n` 结尾」即切出一句，立刻提交 TTS 任务；
   - LLM 流结束后把剩余 `pending_text` 作为最后一句提交。
   - 分句函数复用/抽取 `edge_tts_adapter.py:121-138` 的 `_split_sentences()` 逻辑到公共 util（首句可放宽到逗号切分，进一步压低首句延迟——Zerolan 报告建议）。
2. **句间并行合成、按序播放**（借鉴 Amadeus §2.3-2.4 线程池 + 保序队列）：
   - 每句 `asyncio.create_task(tts.synthesize(sentence))`，并发上限 2~3（Edge-TTS 是网络服务，勿开太大）；
   - 结果带 `segment_order` 入 `asyncio.Queue`，独立协程按序取出、依次执行现有的 `_on_tts_audio` + `_on_live2d`（`audio_pipeline.py:264-283` 的逻辑搬进消费协程）；
   - 每个任务开头和句间都检查 `cancel_event`（打断语义不变：INTERRUPTED 时丢弃未播句子）。
3. **播放结束判定改为前端回报**：
   - 现状 `asyncio.sleep(total_duration_ms/1000)` 估算（`audio_pipeline.py:288`），误差进状态机；
   - 前端播放完最后一段音频后发 `playback.done` 消息（`useAudioPlayback.ts` 的 `source.onended`），后端收到后才触发 `speaking_done`；
   - 保留超时兜底（估算时长 × 1.5）防消息丢失卡死状态机。

**配置新增**（`config.default.yaml`）：

```yaml
tts:
  streaming:
    min_segment_length: 15     # 首句成句最小字数
    first_segment_punc: "，,。！？!?；;"   # 首句允许逗号切分
    rest_segment_punc: "。！？!?；;"
    max_concurrent_synthesis: 2
```

**验收**：

- [ ] 日志埋点测量 TTFA（ASR 结束 → 首段音频发出）：优化前后对比，目标降低 ≥50%。
- [ ] 打断测试：SPEAKING 中途打断，未播放句子被丢弃，状态机正常回 LISTENING。
- [ ] `tests/test_integration.py` 通过；新增 `tests/test_streaming_tts.py` 覆盖分句边界（短句、无标点长句、纯英文）。

---

## Phase C（P1）：口型同步时钟统一 + 插值过渡 — 1~2 天

**目标**：口型偏差进入 <40ms 不可察觉区间（唇同步报告 §2.1 感知阈值：<40ms 不可察觉，40-100ms 可容忍，>100ms 明显脱节）。

**违反的设计原则与修法**（唇同步报告第四部分「六大原则」）：

### C-1 单一时钟源（原则一）

- 现状：timeline 路径用 `Date.now() - 后端Unix时间戳`（`Live2DCanvas.tsx:479-516`）——前后端时钟偏差 + 网络延迟 + WS 排队全部混入。
- 改法：**废弃跨机 wall-clock 对齐**。timeline 帧时间全部改为**相对于本段音频起点的偏移（ms）**；前端在 `source.start()` 的瞬间记 `t0 = audioCtx.currentTime`，每帧用 `(audioCtx.currentTime - t0) * 1000` 查 timeline。代码里正确路径已存在（`Live2DCanvas.tsx:306-308` 的 rAF + 音频时钟），让 timeline 命令路径并入它即可。
- 后端配合：`build_timeline_message`（`motion_controller.py:369-438`）不再发 `audio_start_time` 绝对时间戳，只发相对偏移；`tts_start_time`（`audio_pipeline.py:269`）逻辑可删。

### C-2 同一时刻启动（原则二）

- 音频 buffer 与该段 timeline 绑定为同一消息或带同一 `segment_id`；前端必须在 `source.start()` 同一个调用栈里激活对应 timeline，不允许各自异步就位。

### C-3 过渡优于跳变（原则六）

- 现状：`applyLipSync` 阶跃 `setParameter`（`Live2DCanvas.tsx:319-344`）；表情用 `setTimeout` 调度（:507-513）。
- 改法：相邻口型帧之间做 60ms 线性插值（协同发音），移植唇同步报告 §3.3 的 `interpolate_visemes()`：gap ≤60ms 全程插值；否则「稳定区 + 尾部 60ms 过渡区」。表情切换也从 `setTimeout` 改为 rAF 循环内按音频时钟触发。

### C-4 字级时间戳加权（可选增强）

- 现状：句内汉字**均匀**分配时长（`edge_tts_adapter.py:176-216`）。
- 改法：按音节权重分配——韵母带鼻音/复韵母（ang/iao…）权重 1.3，单韵母 1.0，标点后插入 100~150ms 静默（闭嘴帧）。纯启发式，不引入新依赖。

**验收**：

- [ ] 录屏逐帧检查（60fps 录屏，1 帧 ≈16.7ms）：爆破音（"爸""怕"）张嘴时刻与声音起点偏差 <3 帧（≈50ms）。
- [ ] 连续播放 5 句以上无累积漂移（最后一句与第一句偏差无可见差别）。
- [ ] 嘴型无高频抖动、无阶跃跳变。

---

## Phase D（P1）：persona 配置化性格系统 — 1~2 天

**目标**：性格设置从 0 到 1，换人设不改代码。借鉴 Amadeus §6.1 七层结构化 prompt。

**步骤**：

1. **配置结构**（`config.default.yaml` 新增 `persona` 段，用户在 `config.user.yaml` 覆盖，走现有 Config 深合并）：

```yaml
persona:
  name: "小助手"
  identity: "友好的桌面 AI 伙伴"          # <Identity>
  personality: "温和、好奇、偶尔调皮"      # <Personality>
  speaking_style: "口语化短句，像实时语音聊天，不用列表和markdown，单次回复不超过100字"
  language: "中文"
  background: ""                          # 角色背景知识，可为空
  few_shot_examples: []                   # [{user: "...", assistant: "..."}]
  emotion_expression_map: {}              # 可覆盖 _SPEECH_EMOTION_MAP，人设专属表情倾向
```

2. **prompt 组装器**：新建 `backend/llm/persona.py`，`build_system_prompt(persona_cfg) -> str`，按七层 XML 标签结构组装：
   - 角色身份 / 性格 / 说话风格（**必含**"你的回复会被 TTS 朗读并实时对话，像真人说话"——抑制列表和长段输出）
   - 语言控制 / 角色背景
   - **ASR 容错层**：`<ASRNote>用户输入来自语音识别，可能有同音错字，按发音合理推断意图，不要复述错字。</ASRNote>`（Amadeus 的 Whisper 容错提示，对 SenseVoice 同样适用）
   - few-shot 对话样本（若配置）
3. **注入点替换**：`audio_pipeline.py:87-89` 从 `llm.system_prompt` 改为 `build_system_prompt(config.get("persona"))`；保留 `llm.system_prompt` 作为兜底（persona 未配置时）。
4. **情绪联动**：`motion_controller.py:55-96` 的 `_SPEECH_EMOTION_MAP` 支持被 `persona.emotion_expression_map` 覆盖（如"傲娇"人设 happy→smug）。

**验收**：

- [ ] 修改 `config.user.yaml` 的 persona 后重启，对话风格明显变化，且回复长度受控。
- [ ] `GET /api/config` 中 persona 正常展示（无敏感字段，无需 mask）。
- [ ] 单元测试：`build_system_prompt` 各层拼装、few-shot 注入、空配置兜底。

---

## Phase E（P2）：本地长期记忆 — 约 1 周

**目标**：跨会话记住用户信息与偏好。借鉴 Amadeus §4 分层架构，但**本地化**（不用 mem0ai 云端——其报告 §7.4 自己指出了隐私/网络依赖问题；也不用 Milvus——桌面单用户场景过重）。

**架构**：

```
对话轮结束 ──异步──▶ MemoryStore.add(qa_pair)          # 不阻塞响应
                        │  sqlite: memories(id, text, embedding BLOB, created_at)
                        │  embedding: Ollama /api/embed（本地，qwen 系或 nomic-embed-text）
下一轮输入到达 ──────▶ MemoryStore.search(query, top_k=3)
                        │  query = 用户输入 + 最近2轮对话   # 报告指出只用当前输入会检索偏题
                        ▼
        "相关记忆：\n{memories}\n\n用户说：{prompt}" 注入 LLM 上下文
```

**步骤**：

1. 新建 `backend/memory/`：`base.py`（BaseMemory 抽象，沿用项目 adapter 模式）+ `local_store.py`（sqlite + 余弦检索；千条量级 numpy 暴力检索足够，无需向量库）。
2. Ollama embedding 调用复用现有 ollama 连接配置；embedding 模型名入 config。
3. 写入策略：每轮问答对 + 每 10 轮生成一次语义摘要（用主 LLM，低优先级异步任务，`cancel_event` 感知）。
4. 检索注入：`_process_speech()` 在构建 LLM messages 前检索 top-3，按 Amadeus 格式拼接注入。
5. **短期记忆顺带修正**：`audio_pipeline.py:212-218` 目前只按条数裁剪，config 里 `max_context_tokens: 4000` 未使用——裁剪时叠加 token 估算（len/1.5 近似即可），超限时优先丢最旧非 system 消息。
6. 存储路径：`resources/memory.db`（加入 .gitignore）。config 开关 `memory.enabled: false` 默认关闭，稳定后再默认开。

**验收**：

- [ ] 会话 A 告知"我叫 XX，喜欢 YY"→ 重启后端 → 会话 B 问"我叫什么"，回答正确。
- [ ] 记忆写入不增加响应延迟（异步验证：TTFA 无回归）。
- [ ] 单元测试：add/search/摘要生成/token 裁剪。

---

## Phase F（P3）：迁移 CosyVoice 2 TTS — 1~2 周

**目标**：一次引擎升级同时命中三个痛点（两份报告共同推荐）：

| 收益 | 说明 |
|---|---|
| 口型 L3 满血 | 原生字符级时间戳 `{token, start_time, end_time}`，替代 Edge-TTS 句内均匀估算；配合唇同步报告 §3.3 的拼音→Viseme 映射表 |
| 延迟 | 流式推理首包 <200ms；且本地推理消除 Edge-TTS 网络往返 |
| 听觉人设 | 自定义音色克隆，与 Phase D persona 联动（`persona.voice_id`） |

**步骤**：

1. 新建 `backend/tts/cosyvoice_adapter.py`，继承 `BaseTTS`，config `tts.engine: cosyvoice` 切换（adapter 模式，Edge-TTS 保留为 fallback）。
2. 部署：CosyVoice 2 跑在 Docker ROCm 容器内（与 funasr 同栈，ModelScope 下载，走 `modelscope_cache` volume）；先验证 ROCm 推理可行性，不行则退 CPU 或保持 Edge-TTS。
3. 时间戳链路：字符时间戳 → pypinyin 声母+韵母 → 唇同步报告 §3.3 的「拼音-Viseme-Live2D 参数」映射表（声母决定闭合帧：b/p/m→闭嘴、f→齿唇；韵母决定元音帧）→ 现有 timeline 消息格式不变，前端零改动。
4. 音色：录制/选取参考音频生成 voice embedding，路径入 persona 配置。

**验收**：

- [ ] A/B 对比录屏：CosyVoice 时间戳驱动 vs Edge-TTS 估算驱动，口型贴合度肉眼可辨提升。
- [ ] 本地推理 RTF < 0.5（1 秒音频合成耗时 <500ms），否则不切默认引擎。

---

## 实施顺序与依赖

```
Phase A（协议修复）──▶ Phase C（时钟统一）     A 是 C 的前置
Phase B（流式TTS）独立，可与 A/C 并行
Phase D（persona）独立
Phase E（记忆）独立，建议在 D 之后（记忆注入格式受 persona 影响）
Phase F（CosyVoice）最后，依赖 C 的时钟框架
```

建议节奏：**A → B → C**（先把"听得快、对得上"解决）→ **D → E**（人设与记忆）→ **F**（长期）。

## 全局验收指标

| 指标 | 当前（估） | 目标 |
|---|---|---|
| 首句可听延迟 TTFA | 全文 LLM + 首句 TTS | 降低 ≥50% |
| 口型-声音偏差 | wall-clock 路径，不可控 | <40ms（录屏逐帧验证） |
| 口型过渡 | 阶跃跳变 | 60ms 插值，无抖动 |
| 性格 | 硬编码一段 prompt | config 可换人设 |
| 记忆 | 重启即忘 | 跨会话检索命中 |
