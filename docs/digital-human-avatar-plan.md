# 数字人形象接入 — 施工计划（修订版：运行期形象选择）

> 承接 `docs/digital-human-avatar-proposal.md`（方案选型）与
> `docs/digital-human-avatar-implementation.md`（库/素材/代码要点）。
> 本文件是**施工依据**：把"配置期切换形象"修订为"**开始界面运行期选择形象**"。
> 基线：分支 `phase-digital-human`，HEAD = `3f013c5`（与 `master` 零差异）
> 最后更新：2026-07-25

---

## 0. 需求与结论

### 0.1 需求

1. 开始界面提供"**数字人 / Live2D**"两个模式的选择。
2. 选定模式后，用户可进一步选择**该模式下的具体模型**。
3. 选择完成后进入主界面，交互链路（VAD → ASR → LLM → TTS → 口型/表情 → `playback.done`）保持现状不变。
4. 选择页**本版不做模型实时预览**，但架构必须保证**后续加预览不与主画布冲突**。

### 0.2 已确认的决策

| 项 | 决策 |
|---|---|
| 选择页预览 | 本版不做；预留扩展点，且预览不得与主画布争 WebGL 上下文 / 音频桥 |
| 选择持久化 | **仅进程内**（每次启动都要选）。不写 `config.user.yaml`（Docker 下为挂载文件，重写有覆盖风险） |
| 素材路线 | **先用公开素材跑通验证**（已实测可用，见 §0.4），A1（ReadyPlayerMe）/ A2（VRoid）共用同一抽象后补 |
| 质量目标 | **跑通优先**：本阶段只求端到端闭环可跑，不求表现质量；但**接口必须留缝**，后续升级不推翻 |
| 形象关联 | 选择条目**预留 `persona` / `voice` 关联字段**（本版不消费），让将来"选角色（形象+人设+音色）"是增量而非重构 |
| 耦合处理 | 模型 ↔ 人设 ↔ 记忆 的耦合点在 §2.5 显式补齐，其中"按形象生效的情绪映射"本版即落地 |

### 0.3 一句话架构

> 渲染器可插拔 + 形象清单由后端发现 + 选择经 WS 握手 → **交互链路一行不改**。

```
appPhase: startup → picking → loading → ready
         开始界面   形象选择页   握手+加载   主界面

AvatarPicker ── GET /api/avatars ──→ 后端扫描目录得到清单
     │
     └─ ws: avatar.select {id} ──→ 后端校验 + 加载 profile + 热换 MotionController
                                    ←─ ws: avatar.profile {type, ...}（判别联合）
                                    → setSelectedAvatar + setAppPhase("loading")

AvatarCanvas key={selectedAvatar.id} ─┬─ type="live2d"        → <Live2DCanvas/>
                                      └─ type="digital_human" → <DigitalHumanCanvas/>
```

### 0.4 验证用公开素材（本机实测结论）

**本机网络实测（2026-09，配代理复测）**：

| 目标 | 结果 |
|---|---|
| `readyplayer.me` / `models.readyplayer.me` / `api.` / `docs.` | ❌ **DNS 层不存在**（权威 NS 返回 NXDOMAIN / 仅 SOA，无 A 记录） |
| `github.com` / `raw.githubusercontent.com` | ✅ 200 |
| `vroid.com/en/studio` / `hub.vroid.com` | ✅ 200（走代理） |
| Sketchfab / Mixamo / Khronos | ✅ 200（走代理） |

> **RPM 已不可用，不是代理问题**：用 DoH（Cloudflare/Google）直查权威解析，`readyplayer.me`
> 只有 SOA 无 A 记录，`models.readyplayer.me` 是权威 NXDOMAIN；`docs.readyplayer.me`
> 同样不解析；第三方监测显示站点持续 Down。对照同期 GitHub/VRoid/Sketchfab/Mixamo 全部 200，
> 排除本机网络与代理因素。
>
> **RPM 路线作废**，替代方案见 §0.5。

**已下载并解析（不是猜的）**：

| 素材 | 大小 | morph 实测结果 | 承担什么验证 |
|---|---|---|---|
| `examples/models/gltf/facecap.glb`<br>（three.js，MIT） | 325 KB | **完整 ARKit 52 blendshape**：`jawOpen`、`eyeBlink_L/R`、`mouthSmile_L/R`、`browInnerUp`、`browDown_L/R`、`eyeWide_L/R`、`cheekSquint_L/R`、`mouthFrown_L/R`、`mouthPress_L/R`… | ✅ **口型 / 眨眼 / 情绪 blendshape 的完整真实验证**（本版 3D 主验证素材） |
| `examples/models/gltf/RobotExpressive/RobotExpressive.glb`<br>（three.js，MIT） | 453 KB | 3 个**整脸** morph：`Angry` / `Surprised` / `Sad`；14 条骨骼动画（`Idle`/`Wave`/`ThumbsUp`…） | ✅ 身形 + 骨骼动画 + **整脸 morph 预设**（同时验证"非逐 blendshape"的第二类模型） |

**关键发现（决定 profile schema 必须做成两类通吃）**：

1. `facecap.glb` 的命名是 `browDown_L` / `eyeBlink_L` 这种 **`_L/_R` 后缀**，
   而 RPM/ARKit 是 `browDownLeft` / `eyeBlinkLeft` 这种 **`Left/Right` 后缀**（RPM 另有 `viseme_*`）。
   → profile 的 morph 名**必须逐项显式映射**（本来就该如此），且**不做任何命名猜测/硬编码**。
2. `RobotExpressive.glb` 证明存在一整个**没有逐 blendshape、只有整脸表情 morph** 的模型类别
   （不少免费/游戏资产如此）。若 profile 只支持 `{blendshape: weight}` 形式，这类模型**直接无法接入**。
   → profile 的 `expressions` 需同时支持 **两类**：
   - `type: "blendshapes"`：多 morph 加权（facecap / RPM / VRoid 这类）
   - `type: "morph"`：单个整脸 morph 名（RobotExpressive 这类）
3. **两个公开素材都没有"下颌/嘴部独立通道 + 完整表情"之外的东西**：
   `facecap.glb` 只有头（无身体、无骨骼动画），`RobotExpressive.glb` 无嘴部 morph。
   → 本版可验证**口型、眨眼、情绪表情、打断**；**"写实数字人外观 + 身体 idle 动画"仍要等真实素材**，
   这部分是**素材缺口，不是代码缺口**。

**落盘策略**：不入库二进制。新增 `scripts/fetch-placeholder-avatars.sh` 按需下载到
`frontend/public/avatar/_placeholder/`（该目录 gitignore），并随附各自 `avatar_profile.yaml`。
理由：仓库保持轻量、Docker 构建不依赖外网、真素材到位后删掉即可。

### 0.5 素材来源（RPM 作废后的替代路径）

| 路径 | 可达性 | 特点 | 状态 |
|---|---|---|---|
| **VRoid 示例 VRM**（three-vrm 官方，MIT） | ✅ 脚本一键下载 | 真实二次元素材：完整身体/发型/MToon 材质、57 morph、口型 A/I/U/E/O（**viseme 级**）、眨眼、标准情绪 | **已接入并实测渲染通过**（`digital_human/vroid`） |
| VRoid Studio 自建 + 导出 VRM | ✅ 官网可达 | 捏人自由，导出即带标准表情/口型 preset | 推荐，需人工操作 |
| VRoid Hub 下载 | ✅ 可达 | 社区模型；注意各模型授权条款 | 可选 |
| three.js `facecap.glb` | ✅ 已入库脚本 | 完整 ARKit 52 blendshape，口型/眨眼/情绪齐全；只有头 | 已接入（占位验证用） |
| three.js `RobotExpressive.glb` | ✅ 已入库脚本 | 整脸 morph + 骨骼动画，无嘴部 morph | 已接入（验证"整脸 morph"schema 与降级） |
| Sketchfab / Mixamo | ✅ 可达 | 商用需买授权；Mixamo 只出动画不带 blend shape | 备选 |

**VRM 的已知限制**（素材缺口，非代码缺口）：
- 静止是 **T-pose** —— 本渲染器不驱动骨骼动画。要待机动作需接 `three-vrm`，
  或换带 `AnimationClip` 的 GLB（现有 `AnimationMixer` 通道已就绪）。
- **无眼球注视 morph**（VRM 把 lookAt 放在扩展里）→ 眼神跟随整条通道跳过（有日志，不影响其余）。

**结论：本轮无需 RPM 也能拿到"真实可用"的数字人素材** —— VRoid 路线同时满足
"可一键获取 + 真实外观 + viseme 级口型潜力"。


---

## 1. 现状锚点（施工时必须对齐的真实契约）

| 关注点 | 现状 | 位置 |
|---|---|---|
| 桥接口 | `registerSpeaker({speak,stop})` / `registerExpressionSetter(fn)`，**模块级单例、无 owner 身份** | `frontend/src/hooks/useAudioPlayback.ts:17-22, 31-46` |
| 播放泵 | FIFO 队列 + `pump()`；打断 `stopAll()`；`playback.done` 300ms 防抖 | 同上 `:49-91` |
| 解码/播放/RMS | **内联在 Live2DCanvas 的 speak 桥里**（`<audio>` 预热 50ms 静音 WAV、`OfflineAudioContext` 解码、时长看门狗、blob 回收） | `frontend/src/components/Live2DCanvas.tsx:388-514` |
| RMS 消费点 | `beforeModelUpdate` 钩子里按 `el.currentTime` 取采样窗口 → 写 LipSync 组参数 | `Live2DCanvas.tsx:205-229`，状态在 `:106-113` |
| profile 推送 | WS **连接时**推 `live2d.profile` = `ModelProfile.to_frontend_dict()` | `backend/main.py:349-356` |
| profile 前端落点 | `useWebSocket.ts:131-137` → `agent-store.ts:164-165`（`modelProfile`） | — |
| 情绪名来源 | `detect_emotion()` → `happy/sad/surprised/thinking/neutral`；persona 可覆盖 | `backend/live2d/motion_controller.py:55-87` |
| 逐句表情 | 塞进 `tts.audio.payload.expressions[0].name` | `backend/audio_pipeline.py:328-334` |
| 打断表情 | `live2d.control{command:"interrupt"}` → `setExpression("surprised")` | `Live2DCanvas.tsx:569-573` |
| 应用阶段 | `AppPhase = "startup" \| "loading" \| "ready"` | `frontend/src/stores/agent-store.ts:22` |
| 开始界面 | `StartScreen` 已有 `startup/loading/error` 三态，源码里留着 `TODO: 未来可在此添加模型选择` | `frontend/src/components/StartScreen.tsx:30-32` |
| 开始界面样式 | `.start-screen/.start-card/.start-title/.start-subtitle/.start-btn/.start-spinner/.start-status/.start-error` | `frontend/src/App.css:288-370` |
| 静默资源 | `frontend/public/live2d/有马加奈/{有马加奈.model3.json, model_profile.yaml}`；`public/` 由 Vite 直出，`dist/**` 已进 electron-builder `files` | `frontend/vite.config.ts`、`frontend/package.json:44-49` |
| 已知技术债 | 表情"直接设值"无 lerp（`NEXT.md` 技术债第 1 条） | — |
| 网络实测（2026-07-25） | `readyplayer.me` / `models.readyplayer.me` / `vroid.com` **不可达**（000，Cloudflare）；`github.com` / `raw.githubusercontent.com` / `registry.npmjs.org` **可达**（200） | — |
| 验证素材实测 | `facecap.glb` = 完整 ARKit 52 blendshape（`jawOpen`/`eyeBlink_L/R`…）；`RobotExpressive.glb` = 仅整脸 morph（`Angry`/`Surprised`/`Sad`）+ 14 条骨骼动画 | 见 §0.4 |

---

## 2. 修订要点（相对原计划的四个实质变化）

| # | 变化 | 原因 |
|---|---|---|
| R1 | 新增 `picking` 阶段 + `AvatarPicker` + `avatar.select` WS 消息 + `GET /api/avatars` | 形象选择从"配置期"变为"运行期" |
| R2 | `registerSpeaker` / `registerExpressionSetter` **加 owner token** | 运行期换渲染器会产生**注册竞态**：旧画布 unmount 的 cleanup 会把新画布的桥置 `null` → 音频全断。这是本次**最高风险项** |
| R3 | profile 契约从单数 `ModelProfile` 改为**按 `type` 判别的联合**（`avatar.profile`）；后端 `motion_controller` 支持热替换 | 一份连接要能承载两种形象类型，且选择后要重新推送 |
| R4 | 模型路径从单值 `live2d.model_dir` 改为**目录扫描清单** | 用户要能在多个模型间选 |
| R5 | profile schema 的 `expressions` **同时支持两类**：`type:"blendshapes"`（多 morph 加权）与 `type:"morph"`（单个整脸 morph）；`mouth_open` 支持加权或**发声时整体加偏置** | 公开素材实测证明两类模型都存在（`facecap.glb` vs `RobotExpressive.glb`），只支持一类会堵死后续素材 |
| R6 | 选择条目预留 `persona` / `voice` 关联字段（本版只做解析与传递，不消费） | "选角色"将来是增量而非重构（§3.3） |
| R7 | 后端 `_apply_avatar()` 增加**按形象生效的情绪映射校验**（缺失 → `WARNING` + 回退 `neutral`） | 见 §2.5 耦合点 ① |

---

## 2.5 模型 ↔ 人设 ↔ 记忆 的关系（耦合点补齐）

先明确代码事实（已逐条核对）：

```
模型（Avatar）             人设（Persona）              记忆（Memory）
─────────────             ──────────────              ──────────────
只管"长什么样"             只管"是什么性格"              只管"记得什么"
morph / blendshape        system prompt                long_term_memory.json
MotionController          persona.py 七层 XML          MemoryManager
表情名集合                情绪→表情名映射表              与形象/人设零交互
```

| 环节 | 代码位置 | 事实 |
|---|---|---|
| 人设组装 | `backend/llm/persona.py:15` | `build_system_prompt(persona_cfg)` 只读 `config.persona`，**完全不碰模型** |
| 人设注入 | `backend/audio_pipeline.py:100-102` | `system_prompt` → `Message(role="system")` 进对话历史 |
| 记忆注入 | `backend/audio_pipeline.py:108-113` | `memory.get_context()` 拼成 `<user_memory>` **追加在 system prompt 之后** |
| 记忆落盘 | `backend/memory.py:73-75` | `data/long_term_memory.json`（`data/` 已 gitignore），**独立文件，与形象/人设无关** |
| 记忆提取 | `backend/audio_pipeline.py:497-508` | 会话 shutdown 时用同一个 LLM 抽取，与形象无关 |
| 配置分层 | `config.default.yaml:116-134` | `live2d:` / `avatar:` 与 `persona:` 是**并列独立段** |

**基线结论：换模型不改人设、不丢记忆；改人设不动模型；记忆跨形象持续。** 本方案不破坏这一点。

### 耦合点 ①（必须本版处理）：情绪名 ↔ 模型表情名

数据流：

```
detect_emotion() → "happy" → tts.audio.expressions[0].name
                                   │
                  ┌────────────────┴─────────────────┐
        Live2D: profile.expressions["happy"]      数字人: profile.expressions["happy"]
        → {type:"native", name:"害羞"}             → {type:"blendshapes", params:{...}}
```

`persona.emotion_expression_map` 可把情绪名覆盖成任意名（README 的傲娇猫娘示例 `happy→smug`）。
对 Live2D 只要该模型 profile 里有 `smug` 即成立；**对数字人若 profile 里没有 `smug`，表情会静默失效**。

**对策**：
1. 明确 `emotion_expression_map` 的语义为"**按当前形象生效**"，而非全局。
2. `_apply_avatar()` 内做**兼容性校验**：遍历 persona 映射产出的情绪名，检查在当前形象的 profile 里是否存在；
   缺失 → `WARNING` 日志列出缺失清单 + 该情绪回退 `neutral`（**不静默、不崩**）。
3. 后续把 `smug` 这类角色特有情绪**下沉到各模型 profile**，persona 只保留"该角色的情绪倾向"。

### 耦合点 ②（本版只留缝）：声音 ↔ 形象

`config.user.yaml` 当前绑定的是 **GPT-SoVITS 角色音色**（`resources/GPT-SoVITS-YouXiang/` + `ref_short.wav`）。
用户认知里"选形象"常常等于"选角色（形象 + 声音 + 人设）"。

**对策**：本版按已确认决策**只选形象**，但选择条目预留可选 `persona` / `voice` 字段（§3.3），
让将来"选角色"= 一次选中形象 + 人设 + 音色，而非推翻重做。

### 耦合点 ③（本版顺手修）：system prompt 里的形象描述

`config.default.yaml:90` 现为"**你有 Live2D 形象**"，切到数字人后不成立，且 LLM 会据此自称。

**对策**：改为中性表述；进一步可让 `build_system_prompt` 从当前形象 profile 取一句外形描述注入 `<Identity>`
（本版只做中性化，不做动态注入，避免扩大改动面）。

### 收尾对照表

| 维度 | 选形象会变吗 | 说明 |
|---|---|---|
| 渲染器 / 口型驱动 | ✅ 变 | 交换 `AvatarCanvas` 分支 |
| 后端 `MotionController` 用的 profile | ✅ 变 | `_apply_avatar()` 热替换，失败回滚 |
| **System prompt / 人设** | ❌ **不变** | 只读 `config.persona` |
| **长期记忆** | ❌ **不变** | `data/long_term_memory.json` 跨会话/跨形象持续 |
| 对话历史 | ❌ 无影响 | 切换只发生在**进入主界面之前**，此时历史必为空 |
| 音色（当前实现） | ❌ 不变 | 本版不联动，接口预留（耦合点 ②） |
| 情绪映射表 | ⚠️ 需校验 | 本版落地校验 + 告警（耦合点 ①） |

---

## 2.6 实现期新发现（施工后补记）

以下都是**动手后才暴露**的问题，不是设计阶段能预判的；写在这里避免后人重踩。

| # | 发现 | 影响 | 处理 |
|---|---|---|---|
| D1 | **`/api` 反代只加了 web 那份 vite config** | `npm run electron:dev`（README 主推路径）上 `/api/*` 被 SPA 兜底成 HTML → 选择页整页不可用 | 两份 config 各配一份代理；两套路径**各自在 HTTP 层验证**（§3.7） |
| D2 | **NTFS 挂载存不住可执行位**（仓库在 `/media/jason/D`，fuseblk + `default_permissions`） | npm script 里的裸命令（`vite`/`tsc`/`oxlint`）一律 `Permission denied`（exit 126）；`chmod +x` 无效 | `package.json` 的 script 改为 **node 显式调用 CLI**（对任何文件系统有效） |
| D3 | **Electron 二进制同样没有可执行位** | `vite-plugin-electron` 用 `spawn()` 直接执行 `node_modules/electron/dist/electron` → 启动失败 | dev 时把 dist 复制到 ext4 侧，用 `ELECTRON_OVERRIDE_DIST_PATH` 指过去（见 README 故障排查） |
| D4 | **StrictMode 复用同一 `<canvas>` 节点** | 上次 cleanup 的 `forceContextLoss()` 让节点永久拿不到上下文 → 第二次 `new WebGLRenderer` 崩溃 | 渲染器每次实例化**新建 canvas**；且不再调 `forceContextLoss()` |
| D5 | **Three.js 进主包** | 主包 829KB → 1.5MB，选择页就得先下两份渲染器 | 两个渲染器 `React.lazy` 按需加载（主包回到 213KB，各成 chunk） |
| D6 | **zustand `subscribe` 会立即用当前值回调一次** | 残留的 `avatarProfile` 会立刻"结算"刚发出的选择请求 | 发请求前主动清空 `avatarProfile`，使"非 null 到达"成为无歧义回执 |

---

## 3. 详细设计

### 3.1 后端：形象清单发现

新增 `backend/avatar/catalog.py`：

```python
@dataclass
class AvatarEntry:
    id: str            # slug，如 "live2d/有马加奈"、"digital_human/avatar"
    name: str          # 展示名
    type: str          # "live2d" | "digital_human"
    model_path: str    # 前端可直接 fetch 的 public 路径，如 "/avatar/avatar.glb"
    profile_path: str  # 同名 profile yaml 路径
    valid: bool        # 缺文件/解析失败 → False
    reason: str        # valid=False 时的原因（供 UI 置灰+说明）
    # ── 预留关联字段（R6：本版只解析并透传到前端，不消费）──
    persona_id: str = ""   # 关联的 persona 预设标识（将来"选角色"用）
    voice_id: str = ""     # 关联的音色标识（将来"选角色"用）
    extras: dict = field(default_factory=dict)  # 未知字段透传，避免升级改结构
```

> **预留字段的边界（R6）**：本版 `persona_id` / `voice_id` **只解析、只透传、只显示**，
> **绝不消费**——不切换 persona、不换音色。这样将来接"选角色"时是**填语义**，而不是**改结构**。
> `extras` 透传未知字段，后续 profile 加字段不需要改后端解析代码。

扫描规则：

| 类型 | 扫描目录 | 命中条件 | 展示名来源 |
|---|---|---|---|
| `live2d` | `frontend/public/live2d/*/` | 目录内存在 `model_profile.yaml` | `model_profile.yaml` 的 `model.name`；解析失败回退目录名 |
| `digital_human` | `frontend/public/avatar/*/` | 目录内存在 `avatar_profile.yaml` | `avatar_profile.yaml` 的 `name`；回退目录名 |

**关键约束**：
- `model_path` / `profile_path` 一律转成 **public 相对 URL**（`/live2d/...`、`/avatar/...`），前端不做路径拼接猜测。
- 扫描结果**排序稳定**（按 `type` 再按 `id`），避免每次启动顺序抖动。
- `valid:false` 的条目**保留在清单里**，带 `reason` 让 UI 置灰 —— 静默消失会让用户以为模型丢了。
- 目录不存在时返回空清单，不抛异常（3D 素材未就位是预期状态）。

### 3.2 后端：选择握手

新增 WS 消息处理器 `avatar.select`（`backend/main.py`）：

```
client → { type: "avatar.select", payload: { id } }
server → { type: "avatar.profile", payload: { type: "digital_human"|"live2d", ... } }
         + { type: "state.change", payload: { state, reason: "avatar_selected" } }
出错   → { type: "error", payload: { code: "AVATAR_LOAD_FAILED" | "AVATAR_NOT_FOUND", recoverable: true } }
```

处理流程：
1. **白名单校验**：`id` 必须存在于 `discover_avatars()` 结果且 `valid=True`。**绝不接受客户端传来的任意文件路径**（路径穿越）。
2. 按 `type` 加载 profile：`live2d` → 复用现有 `ModelProfile.load()`；`digital_human` → 新增 `AvatarProfile.load()`。
3. 热替换：把现在 `main.py:44-68` 那段模块级构建封装成 `_apply_avatar(entry) -> bool`，成功则换掉全局 `motion_controller` / 当前 profile；**失败必须回滚**到切换前的形象并回 `error`（不允许半死不活的状态）。
4. 重推 `avatar.profile`（所有客户端；本应用单客户端，但仍走 `broadcast` 保持一致性）。

**profile 双发兼容策略**：
- 始终发 `avatar.profile`（新，带 `type` 判别字段）。
- **仅当** `type == "live2d"` 时**额外**发 `live2d.profile`（保持旧契约，零成本向后兼容）。
- 前端只认 `avatar.profile`；`modelProfile` 保留供 Live2D 渲染器消费。

### 3.3 后端：配置段

`backend/config.default.yaml` 新增（旧 `live2d.model_dir` **保留**，作为无 `avatar` 段时的回退）：

```yaml
avatar:
  type: "live2d"                 # 默认模式（用户未选择时的初始值）
  selected: ""                   # 运行期选择的 id（进程内状态，不落盘）
  digital_human:
    dir: "frontend/public/avatar"
  live2d:
    dir: "frontend/public/live2d"
```

`_apply_avatar()` 在换完 profile 后，**必须执行 §2.5 耦合点 ① 的情绪映射校验**（缺失 → `WARNING` + 回退 `neutral`）。

### 3.4 前端：桥的 owner token（最高风险项的解法）

`frontend/src/hooks/useAudioPlayback.ts` 改为：

```ts
let _bridge: SpeakerBridge | null = null;
let _bridgeOwner: symbol | null = null;

export function registerSpeaker(bridge: SpeakerBridge | null, owner: symbol): void {
  if (bridge === null) {
    if (_bridgeOwner !== owner) return;   // 旧画布的 cleanup 不得踢掉新画布
    _bridge = null; _bridgeOwner = null;
    return;
  }
  _bridge = bridge; _bridgeOwner = owner;
  if (_queue.length > 0) void pump();
}
```

`registerExpressionSetter` 同样处理。渲染器侧：

```ts
const ownerRef = useRef(Symbol("avatar"));
useEffect(() => { registerSpeaker(bridge, ownerRef.current); /* ... */ }, [...]);
```

**同时必须处理的三个细节**：
1. **StrictMode 双挂载**：owner 是每次组件实例化新建的 `Symbol`，双挂载时第二个实例合法接管；第一次的 cleanup 因 owner 不匹配而无效。
2. **切形象的交接窗口**：新桥注册前，`pump()` 会因 `_bridge === null` 保留队列（现有逻辑 `:63`），注册后 `registerSpeaker` 主动补泵 —— 这个行为要保留。
3. **切换时先停后起**：`AvatarPicker` 选择后先 `stopAll()`（停音频+清队列+表情复位），再卸载旧画布、挂新画布，避免旧画布残留音频跨越切换。

### 3.5 前端：公共口型模块

新增 `frontend/src/hooks/useLipSyncAudio.ts`，从 `Live2DCanvas.tsx:388-514` **等值搬运**：
`<audio>` 预热 50ms 静音 WAV、`OfflineAudioContext` 解码、时长看门狗（onended 丢失不卡泵）、blob URL 回收、`stop()` 解锁 pending speak。

对外只暴露**拉取式**接口：

```ts
export interface LipSyncController {
  getRMS(): number;   // 与 <audio>.currentTime 同源；播完返回 0
  reset(): void;
}
export function useLipSyncAudio(opts?: { gain?: number; smoothing?: number }): LipSyncController;
```

**为什么是拉取式而不是 push 回调**：Live2D 必须在 `beforeModelUpdate`（动作已应用、core 求值前）消费 RMS；Three.js 在 `requestAnimationFrame` 消费。拉取式让两种时钟语义都保留，Live2D 迁移时是纯搬运，回归风险最低。

**`gain` 必须参数化**：3D `jawOpen` 敏感度与 Live2D `ParamMouthOpenY` 不同，不能沿用 `*5`（`Live2DCanvas.tsx:219`），需按模型标定后写进 profile。

### 3.6 前端：渲染器组件参数化（**为"后续加预览不冲突"做的关键设计**）

新增 `AvatarCanvas.tsx`（主画布分发）与 `DigitalHumanCanvas.tsx`。为让预览将来能复用同一份渲染器而不冲突，渲染器组件必须满足：

```ts
interface AvatarRendererProps {
  profile: AvatarProfile;         // 判别联合，含 type
  mode: "main" | "preview";       // preview 不注册音频桥、不做交互、可禁声
  interactive?: boolean;          // 拖拽/缩放/眼神跟随
  className?: string;
  onReady?: () => void;
  onError?: (msg: string) => void;
}
```

配套的隔离原则（**这就是"后续加预览不会冲突"的落地保证**）：

| 冲突面 | 隔离手段 |
|---|---|
| **WebGL 上下文** | 每个渲染器实例各自持有自己的 `renderer`/canvas；卸载时 `setAnimationLoop(null)` + `renderer.dispose()` + `renderer.forceContextLoss()`；**选择页不挂任何渲染器**（本版），将来只挂"选中项"的 1 个 preview 实例 |
| **音频桥** | `mode==="preview"` 直接**不调用** `registerSpeaker/registerExpressionSetter`；即便将来要预览口型，也走独立 `useLipSyncAudio` 实例 + owner token |
| **模块级单例** | 除 `useAudioPlayback` 的播放泵必须单例外，其余（RMS 控制器、交互状态）一律**实例级**，禁止新增模块级可变状态 |
| **DOM/CSS** | 预览用独立容器与 class 前缀（`.avatar-preview-*`），复用 `.live2d-canvas-container` 的定位语义但不共用 id |
| **扩展点** | `AvatarPicker` 里预留 `<div className="avatar-preview-slot" data-avatar-id={id} />`，本版渲染占位图/图标；将来把 preview 渲染器挂进这个 slot 即可，不动任何其它文件 |

### 3.7 前端：store / 类型 / 消息接线

- `AppPhase` 增加 `"picking"`（`agent-store.ts:22`）。
- 新增状态：`avatarCatalog`、`selectedAvatar`、`avatarProfile`（含 `type`）。
- `useWebSocket.ts` 新增订阅 `avatar.profile` → `setAvatarProfile`；保留 `live2d.profile` → `setModelProfile`。
- 新增 `hooks/useAvatarCatalog.ts`：`fetch("/api/avatars")` + 处理"**WS 未连上就点了选**"（`wsClient.send` 返回 false 时排队，`onConnected` 后补发）。
- **`/api` 反向代理必须两套 vite config 各配一份**（`vite.config.ts` 给 Electron、`vite.config.web.ts` 给 `dev:web`）。
  漏了任一份，该路径下 `/api/*` 会被 Vite 的 SPA 兜底成 `index.html`，前端 JSON 解析直接失败
  （`Unexpected token '<'`），选择页整页不可用。**实测踩到**：只改了 web 那份，
  于是 `npm run electron:dev`（README 的主推路径）上选择页是坏的，而 web 端正常。
- `AvatarCanvas`：`key={selectedAvatar?.id ?? "default"}` 强制重建；`avatarProfile.type` 缺失/非法时**回退 Live2D**并 `console.error`（不允许黑屏）。

### 3.8 前端：选择页

`components/AvatarPicker.tsx`，复用 `StartScreen` 的视觉语言与 CSS class（`.start-screen/.start-card/.start-title/.start-btn`，`App.css:288-370`）：

- 顶部模式切换（数字人 / Live2D）→ 下方网格列出该模式的模型卡片。
- 卡片：名称 + 类型徽标；`valid:false` → 置灰 + 显示 `reason`（disabled）。
- 清单为空 → 明确提示（如"未发现数字人模型，请将 .glb 与 avatar_profile.yaml 放入 frontend/public/avatar/"），**不是空白页**。
- 点击卡片 → 选中态 → "开始对话"按钮 → 发 `avatar.select` → 收到 `avatar.profile` → `setAppPhase("loading")`（复用现有 loading→ready 逻辑，含 `MIN_LOADING_MS`、连接超时、自动开麦）。
- 加载失败 / `AVATAR_LOAD_FAILED` → 回到 `picking` 并显示错误（不整页崩）。

### 3.9 数字人 profile 契约（已实现，含实测回填）

新增 `backend/avatar/digital_human_profile.py` + `frontend/public/avatar/<model>/avatar_profile.yaml`：

**schema 必须两类通吃（R5）**——`expressions` 支持 `blendshapes`（多 morph 加权）与 `morph`（单整脸 morph）；
`mouth_open` 支持加权或"发声时整体加偏置"。理由见 §0.4 实测：RPM/facecap 是逐 blendshape，RobotExpressive 只有整脸 morph。

```yaml
name: "小助手"
model_path: "avatar/<模型>/model.glb"     # 相对 public
camera: { position: [0, 1.55, 0.65], target: [0, 1.5, 0], fov: 30 }
# 关联字段（R6：本版只解析/透传/显示，不消费）
persona_id: ""
voice_id: ""

# 口型：要么 morph 名（加权，配 gain），要么 {add: 名, amount: x}（无嘴部 morph 时发声整体加偏置）
morphs:
  mouth_open: "jawOpen"
  blink_left: "eyeBlink_L"
  blink_right: "eyeBlink_R"
lip_sync: { gain: 5.0, smoothing: 0.5 }   # 按模型实测标定，禁用 Live2D 的 *5

expressions:
  neutral:   { type: "blendshapes", params: {} }
  happy:     { type: "blendshapes", params: { mouthSmile_L: 0.6, mouthSmile_R: 0.6, cheekSquint_L: 0.4, cheekSquint_R: 0.4 } }
  sad:       { type: "blendshapes", params: { browInnerUp: 0.5, mouthFrown_L: 0.4, mouthFrown_R: 0.4 } }
  surprised: { type: "blendshapes", params: { browInnerUp: 0.7, eyeWide_L: 0.6, eyeWide_R: 0.6, jawOpen: 0.25 } }
  thinking:  { type: "blendshapes", params: { browDown_L: 0.4, browDown_R: 0.4, mouthPress_L: 0.3, mouthPress_R: 0.3 } }

# 只有整脸 morph 的模型（如 RobotExpressive）改用第二种写法：
#   happy:      { type: "morph", name: "Angry" }
#   surprised:  { type: "morph", name: "Surprised" }
#   morphs.mouth_open: { add: "Angry", amount: 0.35 }   # 无嘴部 morph 时的发声代理

idle:
  blink_interval: [2.5, 6.0]
  expression_cycle: ["neutral", "happy", "thinking", "surprised"]
  expression_interval: [6.0, 14.0]
  look_at_range: 0.8
```

**四条硬约束**：

1. **morph 名逐项显式映射**：实测 `browDown_L`（facecap）vs `browDownLeft`（ARKit/RPM），
   命名不统一且不可猜 → 代码**零硬编码、零命名猜测**。
2. **morph 缺失必须降级不崩**：找不到口型/眨眼 morph 时 `console.warn` 出缺失清单，该通道静默跳过，
   渲染器继续跑 —— 这样没有嘴部 morph 的素材也能接入。
3. **两类写法走同一条代码路径**：渲染器只消费"最终 morph 权重表"，由 profile 的 `type` 解析成权重表，
   渲染器不关心来源（这是后续升级不改代码的关键）。
4. **`neutral` 必须存在**：它是打断/复位/心跳的归零目标；缺失时按全 0 处理。


### 3.10 表情平滑（已实现）

数字人链路**从第一版就做 lerp**（`cur += (target - cur) * k`，k≈0.2/帧，参数走 profile），顺手还掉 `NEXT.md` 技术债第 1 条；Live2D 是否一并改造**本阶段不做**（避免扩大回归面），列为后续独立条目。

---

## 4. 施工阶段与提交切分

| 阶段 | 内容 | 依赖 | 预估 | 提交信息 |
|---|---|---|---|---|
| **Stage 0** | `three` + `-D @types/three`；建 `frontend/public/avatar/` + `.gitkeep`；**`scripts/fetch-placeholder-avatars.sh` 下载两个公开验证素材**；`.gitignore` 忽略 `frontend/public/avatar/_placeholder/`；清理 `git status` 杂音（`.gitignore` 仅 CRLF→LF 无内容变化 → `git checkout --`；`resources/lora/` 与本次无关，单独处理） | 无 | 0.5h | `chore: 依赖 + 验证素材脚本 + 目录准备` |
| **Stage 1** | 抽 `useLipSyncAudio`（等值搬运）；**桥加 owner token（R2）**；`Live2DCanvas` 改用它 | 无 | 1d | `refactor(frontend): 抽出公共口型模块 + 桥 owner token` |
| **Stage 2** | `AvatarCanvas` 分发 + `store/types` 扩展 + `key` 强制重建（此时 `avatarType` 仍由后端 profile 决定，无选择页） | Stage 1 | 0.5d | `feat(frontend): AvatarCanvas 分发壳` |
| **Stage 3** | 后端 `catalog.py`（含预留字段）+ `GET /api/avatars` + `avatar.select` + 判别联合 profile + `_apply_avatar()` 热替换 + **耦合点①情绪映射校验** + 测试 | 无（可与 1-2 并行） | 1d | `feat(backend): 形象清单发现 + avatar.select 握手` |
| **Stage 4** | `AvatarPicker` 选择页 + `picking` 阶段接线 + `useAvatarCatalog` + preview slot 占位 | Stage 2 + 3 | 1d | `feat(frontend): 开始界面形象选择` |
| **Stage 5** | **morph 探针脚本** → 写两个占位 `avatar_profile.yaml`（facecap 逐 blendshape / robot 整脸 morph）→ `DigitalHumanCanvas` 最小闭环（RMS 口型 + 情绪权重表 + lerp + 打断 + morph 缺失降级 + 资源释放） | Stage 2 | 1.5d | `feat(frontend): DigitalHumanCanvas 最小闭环` |
| **Stage 6** | 数字人空闲行为（眨眼/眼神/表情循环）+ 拖拽缩放 + **双向切换回归** | Stage 4 + 5 | 1d | `feat(frontend): 数字人空闲行为与交互` |
| **Stage 7** | 回归 + 文档（`STATUS.md`/`NEXT.md` + 本文件回填实测 morph 名与 `gain`） | 全部 | 0.5d | `docs: 数字人接入记录与回归清单` |

**并行建议**：Stage 3（后端）与 Stage 1-2（前端）互不依赖，可同时推进。

**实际结果（2026-07-25 全部完成）**：Stage 0-7 已按序落地，共 7 个独立可回滚提交；
选择页 → 数字人闭环 → 双向切换全部跑通，**全程未依赖真实数字人素材**。
- 提交：`6a85652`(前置) `4e12bae`(口型模块+owner token) `71c8dd6`(分发壳)
  `70606ae`(后端清单/握手) `8d62b4e`(选择页) `6ac70b2`(数字人闭环) `ba04d2c`(空闲行为+切换回归)

**"跑通优先"的路径说明**：因为 Stage 0 就有可用的公开素材（§0.4），
**Stage 4 结束时即可选择形象、Stage 5 结束时数字人闭环可跑** —— 全程不阻塞在"没有真实数字人素材"上。
真实素材（RPM/VRoid）到位后，**只改 `avatar_profile.yaml`，不改代码**：
- 逐 blendshape 模型 → 填 `type:"blendshapes"` + 真实 morph 名
- 换用 `_R/_L` 或 `Left/Right` 命名 → 改 profile 里的名字即可
- 有身体/骨骼动画的模型 → 复用 `AnimationMixer` 通道（robot 占位已打通该路径）

---

## 5. 验收清单

### 5.1 Live2D 零回归（Stage 1-2 后必须全绿）
- [ ] 语音/文字对话全链路正常；口型跟随、害羞/哭泣表情、比心动作、打断恢复正常
- [ ] `playback.done` 不假超时（`respond()` 只认最后一段后的 done）
- [ ] `[Live2D] FPS` 日志与改前同级；无 `webglcontextlost`

### 5.2 选择链路（Stage 3-4 后）
- [ ] `GET /api/avatars` 正确分组；缺 profile 的目录以 `valid:false + reason` 出现，**不静默消失**
- [ ] 非法 / 不存在的 `avatar.select` id 被拒并回 `AVATAR_NOT_FOUND`，后端无异常栈
- [ ] 未连 WS 就点选 → 连上后补发成功（不丢选择）
- [ ] 选择后进入主界面，`avatar.profile.type` 正确驱动渲染器分发
- [ ] `AVATAR_LOAD_FAILED` 时回退到 `picking` 并显示错误，不黑屏

### 5.3 运行期切换（Stage 4-6 后，**本次核心风险验证**）
- [ ] **Live2D ↔ 数字人来回切换 ≥ 5 次**：音频不断、口型跟随新渲染器、无 GPU 内存持续增长（CDP Performance）
- [ ] 切换瞬间旧画布 cleanup **未能**把新画布的桥置 null（owner token 生效）
- [ ] 每次切换只存在 **1 个** WebGL 上下文（CDP 查 canvas 数量与 context 泄漏告警）
- [ ] StrictMode 双挂载下不出现"桥被第二次 cleanup 踢掉"

### 5.4 数字人链路

> 拆成两档：**A 档用公开占位素材即可验收**（本版目标）；**B 档必须等真实素材**（素材缺口，非代码缺口）。

**A 档 — 公开素材即可验收（本版交付标准）** ✅ 已实测（CDP + 真实后端 + 真实 GLB）
- [x] `facecap.glb`：加载成功（识别出 52 个 morph）；`jawOpen` 随 RMS 起伏 ——
      RMS=0.9 → 轨迹 0.749→0.900（lerp），RMS=0.45 → 0.4500（线性），RMS=null → 0（闭嘴）
- [x] `facecap.glb`：眨眼定时器驱动 `eyeBlink_L/R`（截图可见半闭状态）
- [x] `facecap.glb`：`tts.audio.expressions` → 情绪权重表切换且有 lerp ——
      注入 happy → `mouthSmile_L` 0.625→0.700
- [x] `RobotExpressive.glb`：整脸 morph 写法可用（3 个 morph：Angry/Surprised/Sad）
- [x] `RobotExpressive.glb`：无口型/眨眼 morph 时降级不崩 ——
      `[DigitalHuman] 以下 morph 在模型中不存在，已跳过：眨眼(左), 眨眼(右)` 后继续渲染；
      add 型发声代理生效（RMS=0.6 → `Surprised`=0.27 = 0.45×0.6）
- [x] 打断/停止：`stopAll()` → `speak` 的 stop 回调 → 停音频 + 口型归零 + 表情复位
- [x] 首句出声路径复用既有 `<audio>` 管线预热（未改动）
- [x] 渲染器 unmount 后上下文释放：canvas 数在 7 轮切换中恒为 1（无上下文泄漏）；
      已移除 `forceContextLoss()`（见「已知噪声」）
- [x] 切换回归：Live2D ↔ 数字人 **7/7 轮全部就绪**，类型正确、音频桥每轮都被新渲染器接管
- [ ] 长时间挂机（≥30min）无内存/显存持续增长 —— **未做**（需人工长时间观察）

**已知噪声（非本版引入，dev-only）**
- Live2D 挂载时会有 1 次 `[Live2D] WebGL context LOST`：该监听器自 `Live2DCanvas`
  原始实现起就存在，源自 PIXI 在 StrictMode 双挂载下销毁旧上下文。
  实测：卸载数字人期间 0 次、canvas 数不增长、功能无影响。

**B 档 — 等真实素材（RPM/VRoid/自建）到位后补验**
- [ ] 写实/二次元数字人外观（公开素材是扫描头/机器人，**外观不代表最终效果**）
- [ ] 下颌/嘴部灵敏度按真实模型重新标定 `lip_sync.gain`
- [ ] `viseme_*` 或 `aa/ih/ou/ee/oh` 类口型（如素材自带）
- [ ] 身体 idle 动画 + 说话动作（需 Humanoid 骨骼 + Mixamo 类素材）

### 5.5 后端
- [x] 形象相关测试全绿：`test_avatar_profile.py`(29) + `test_avatar_catalog.py`(32) = **61 passed**；
      与既有 `test_model_profile.py`/`test_motion_controller.py` 合并跑 **92 passed**
- [x] 覆盖：发现/嵌套/噪声过滤/坏条目带 reason/URL 编码/路径穿越拒绝/加载校验/
      选择回滚/情绪覆盖校验/`to_frontend_dict` 的 model_path 为可 fetch URL
- [ ] 全量 `pytest tests/` —— **本机解释器缺 torch/fastapi 等重依赖**，历史用例收集即失败（与本轮无关）；
      完整环境（Docker）下需另跑

### 5.6 前端静态检查
- [x] `tsc -b` 通过；`oxlint` **0 error**（3 warning 均为既有的 exhaustive-deps 类型）
- [x] `vite build --config vite.config.web.ts` 通过（产物见上）

### 5.7 端到端（真实浏览器 + 真实后端）
- [x] `GET /api/avatars` 返回 1 个 Live2D + 2 个数字人（路径为可 fetch 的 public URL）
- [x] WS 握手发 `avatar.profile{type}`；Live2D 时**额外**发旧契约 `live2d.profile`
- [x] `avatar.select` 成功回 profile；`../../etc/passwd` → `AVATAR_NOT_FOUND`
- [x] 选择页：模式页签 + 卡片 + 「占位素材」徽标 + 不可用条目置灰带原因
- [x] 主界面：`data-avatar-type` 与所选一致；截图确认数字人渲染画面（张嘴/眨眼/表情）
- [x] **Electron 真实会话**（CDP `:9223`，`npm run electron:dev`）：选择页渲染 2 个模式页签 + 数字人卡片、
      无错误横幅；进入主界面后 3D 模型正常渲染；`PythonBridge` 在 Docker 模式正确复用容器（未重复 spawn）
- [x] 两套 vite config 的代理**各自在 HTTP 层验证**一次（`curl 5173/api/avatars` → `server: uvicorn` + JSON）

---

## 6. 风险与对策

| 风险 | 严重度 | 影响 | 对策 |
|---|---|---|---|
| **桥注册竞态**（旧画布踢掉新桥） | 🔴 高 | 切换后音频全断 | owner token（§3.4）；§5.3 专项验收 |
| **真实数字人素材不可达**（本机已实测） | 🟡 中 | 只影响"最终外观"，**不阻塞开发** | Stage 0 即备好公开验证素材（§0.4）；全链路用占位素材跑通；真素材到位后只改 profile |
| 公开素材**能力不全**（facecap 只有头、robot 无嘴部 morph） | 🟡 中 | 部分通道无法用占位素材验收 | 验收拆 A/B 档（§5.4）；代码层强制"morph 缺失降级不崩"；B 档明确标注为**素材缺口而非代码缺口** |
| 占位素材被误当成品 | 🟢 低 | 观感落差/误解进度 | 目录名 `_placeholder` 强制前缀 + `.gitignore` + 选择页显示"占位素材"徽标 + 文档显式声明 |
| WebGL 上下文泄漏 | 🔴 高 | Electron GPU 崩/卡 | 一次只挂一个主渲染器；dispose + forceContextLoss；`key` 强制重建；§3.6 隔离原则 |
| blendshape 命名不统一 | 🟡 中 | 口型/表情失效 | profile 显式映射（不硬编码）；探针脚本先出全量清单；缺名时 `console.warn` + `jawOpen`/`mouthOpen` 兜底 |
| RMS 抽取引入 Live2D 回归 | 🟡 中 | 历史最痛回退 | Stage 1 单独提交、等值搬运；Stage 1 回归通过后再动 Stage 5 |
| `jawOpen` 增益不适配 | 🟡 中 | 嘴不动或爆开 | `gain` 进 profile，实测标定后回填文档 |
| 配置重写风险（Docker 挂载） | 🟡 中 | 用户配置被覆盖 | **本版不做落盘**（已确认）；持久化另立条目 |
| 中文目录名/slug 编码 | 🟢 低 | 清单 id/URL 异常 | id 用相对路径 slug 并统一 `encodeURI`；前端不做字符串拼接猜测路径 |
| 选择页预览将来冲突 | 🟢 低 | 后续返工 | §3.6 已把 preview 隔离为 slot + 参数化渲染器 + 实例级状态 |
| Three.js 体积/ESM | 🟢 低 | 构建失败 | 与 PIXI 同栈（ESM/WebGL）；若新 loader 引用 Node 内置模块，沿用 `vite.config.ts:47-56` 的 alias shim 手法 |

---

## 7. 明确不做（本版边界）

本版目标是**跑通优先**：只求端到端可跑 + 接口留缝，不求表现质量。以下明确不做（但架构不堵死）：

1. **选择页模型实时预览**（已确认不做，仅留 slot 扩展点）。
2. **选择持久化落盘**（仅进程内）。
3. **viseme 级口型**（第一版 RMS 档）。
4. **Live2D 表情 lerp 改造**（仅数字人做 lerp；Live2D 保持现状以免扩大回归面）。
5. **A2 路线（VRoid / `@pixiv/three-vrm`）**（共用抽象后补）。
6. **云端数字人 SaaS（方案 C）/ LivePortrait（方案 B）**。
7. **`persona_id` / `voice_id` 的实际消费**（R6：本版只解析/透传/显示）。
8. **写实外观打磨**（材质/光照/阴影/后期）—— 等真实素材到位后单独立项。
9. **数字人的口型精度**（RMS 打底即可，追求精度需 viseme 或音素级方案）。

## 8. 待办追踪

- [x] 本文档评审通过（2026-07-25：确认"公开素材跑通 + 预留关联字段 + 耦合点补计划"）
- [x] Stage 0 → Stage 7 全部完成（Stage 3 与 Stage 1-2 并行推进），7 个独立提交
- [x] `scripts/fetch-placeholder-avatars.sh` 落地，两个素材 + 解码器下载可用且幂等
- [x] 实测 morph 名与标定 `gain` 已回填 §3.9 / §0.4
- [ ] 真实素材（RPM/VRoid/自建）到位后：只改 `avatar_profile.yaml`，跑 B 档验收
- [ ] 长时间挂机（≥30min）内存/显存观察（需人工）
- [ ] 完整环境（Docker）下跑全量 `pytest tests/`
- [x] 两套 vite config 的 `/api` 代理各自验证（Electron :5173 与 dev:web 端口）
- [x] npm script 改为 node 调用 CLI（兼容 NTFS/exFAT 等存不住可执行位的挂载）
- [ ] 可选：封装 `scripts/dev-frontend-local.sh` 自动处理 `ELECTRON_OVERRIDE_DIST_PATH`（见 README）
