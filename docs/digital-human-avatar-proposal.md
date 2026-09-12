# 数字人形象接入 — 技术方案与素材调研

> 目标：在**不改变现有交互模式**（VAD → ASR → LLM → TTS → playback.done 的语音/文字对话闭环）
> 的前提下，新增"数字人"形象，替换/并存当前的 Live2D 形象。
> 最后更新：2026-07-25

---

> ⚠️ **本文档是选型/调研阶段的输入材料**，其中的"落地步骤清单"等章节已由
> [`digital-human-avatar-plan.md`](digital-human-avatar-plan.md) 承接并**全部实施完成**
> （含实测数据回填）。以 plan 为准，本文档保留作决策依据。


## 0. 结论先行（TL;DR）

| 方案 | 拟真度 | 实现成本 | 本地/离线 | 依赖 | 推荐度 |
|------|--------|----------|-----------|------|--------|
| **A. 3D 数字人（Three.js + GLB/VRM）** | 中高（可写实可卡通） | 中 | ✅ 纯前端本地渲染 | 新增 `three` 依赖 | ⭐ 首选 |
| B. 实时照片说话人（LivePortrait / FasterLivePortrait） | 高（照片级） | 高 | ✅ 本地但要 NVIDIA GPU | 后端加 GPU 推理服务 | 进阶备选 |
| C. 云端数字人 SaaS（腾讯云数智人 / 火山引擎 / 阿里云） | 高 | 中（接入） | ❌ 依赖云 + 按量付费 | 厂商 SDK/API | 商业化时再评估 |
| D. 2.5D 伪口型（Rive / Lottie / 帧动画） | 低 | 低 | ✅ | 无重依赖 | 快速打样可选 |

**推荐路径：先做 A（3D 数字人），把抽象层立起来；需要照片级拟真时再叠加 B。**

关键结论：当前代码里，**交互逻辑与形象渲染已经被两个桥接口彻底解耦**，这是接入任何新形象的最大利好：

- `registerSpeaker({ speak, stop })` —— `frontend/src/hooks/useAudioPlayback.ts` 定义，`Live2DCanvas.tsx` 注册；
  `speak(buf, mime)` 负责"播放音频 + 驱动口型"，`stop()` 负责打断停止。
- `registerExpressionSetter(fn)` —— 播放泵按句调用 `fn(expression)` 切换表情。

**只要新形象渲染器实现同样两个接口，后端音频/表情/打断链路一行都不用改。**

---

## 1. 现状梳理（本项目）

### 1.1 交互链路（不变的部分）

```
麦克风/文字 → 后端 AudioPipeline
  VAD(512样本/帧) → ASR(SenseVoice) → LLM(流式) → 分句 → 有界并发 TTS
  → 按 seq 有序推送 tts.audio（base64 音频 + expressions）
  → 前端 useAudioPlayback FIFO 泵 → speak 桥 → 口型/表情
  → 播放完 → playback.done 上行 → speaking_done → IDLE
```

### 1.2 形象渲染（要替换/并存的部分）

- 渲染器：`pixi-live2d-display@0.4.0` + `pixi.js@6.5.10`（WebGL），组件 `Live2DCanvas.tsx`。
- 口型：前端 RMS 驱动 —— `<audio>` 播放 + `OfflineAudioContext` 解码采样窗口，每帧在
  `beforeModelUpdate` 钩子把 RMS 写到 `ParamMouthOpenY` 等 Cubism 参数。
- 表情：情绪名 → 原生 `.exp3.json` 或参数覆写（`setExpression`）。
- 空闲：自主表情循环定时器 + 眨眼 + 眼神跟随（`focusController`）+ 拖拽/缩放。

### 1.3 前后端契约（可复用/需泛化的部分）

| 消息 | 作用 | 数字人场景 |
|------|------|-----------|
| `tts.audio` | 音频字节 + `expressions` | ✅ 原样复用（数字人口型同样吃这段音频） |
| `live2d.control` | `expression`/`motion`/`interrupt`/`state` | 语义复用；`motion`（动作）数字人可映射为动画/姿态，可先忽略 |
| `live2d.profile` | `ModelProfile`（Cubism 参数名、表情、动作映射） | ⚠️ 需泛化为 `avatar.profile`（带 `type` 判别） |
| `state.change` / `asr.result` / `llm.stream` | 会话状态/文本 | ✅ 原样复用 |

---

## 2. 三个主方案详解

### 方案 A：3D 数字人（Three.js + GLB/VRM）— 首选

用 **Three.js（WebGL）** 渲染一个 3D 人形模型，通过**变形器（morph target / blend shape）**实现口型和表情。

- 模型格式：`.glb` / `.gltf`（推荐），或二次元风格的 `.vrm`。
- 素材来源：
  - **ReadyPlayerMe**：上传一张正面照 → 自动生成带 **ARKit 52 个 blendshape** 的全身/半身 GLB，
    含 `jawOpen`、`mouthOpen`、`mouthSmile*`、`eyeBlink*`、`brow*`、以及 `viseme_*` 等，可导出离线自托管。
  - **VRoid Studio**（二次元）：导出 `.vrm`，带表情 blendshape（`Fcl_MTH_*` 等）。
  - **定制建模**（Maya/Blender）：导出带标准 blendshape 命名的 GLB。
- 口型：音频 RMS（沿用现有 RMS 泵）→ `jawOpen`（或 `mouthOpen`）blendshape 权重。
  若想更精致，可升级为**音素级 viseme**（离线算 viseme 权重序列），但第一版 RMS 足够。
- 表情：情绪名 → blendshape 权重映射表（放 profile yaml），例如：
  - `happy` → `mouthSmileLeft/Right` + `cheekSquint` + `eyeSquint`
  - `surprised` → `browInnerUp` + `eyeWideLeft/Right` + `jawOpen`
  - `sad` → `browInnerUp` + `mouthFrown*` + `mouthShrug*`
  - `thinking` → `browDownLeft/Right` + 轻微 `mouthPress*`
- 空闲行为：眨眼定时器（`eyeBlinkLeft/Right`）、眼神跟随（头部/眼球朝向鼠标）、拖拽旋转 + 缩放。

**优点**：本地离线、无 GPU 推理、改动集中在"新增一个渲染器 + 一套 profile 抽象"、可写实可卡通、素材免费（ReadyPlayerMe 个人用途）。
**代价**：写实度不如 LivePortrait；Three.js 为新依赖；需做一次 `ModelProfile` 泛化。

### 方案 B：实时照片说话人（LivePortrait / FasterLivePortrait）— 高拟真进阶

用一张**真人照片**，由神经网络实时驱动口型与头部动作（[FasterLivePortrait](https://github.com/warmshao/FasterLivePortrait)，
TensorRT 在 RTX 3090 上 30+ FPS 实时；也支持 JoyVASA 音频驱动）。

- 架构：后端（或独立 sidecar）跑 LivePortrait 推理，输出**视频帧流**（WebRTC / MJPEG / WebSocket 帧）给前端 `<video>` 或 `<canvas>` 显示；TTS 音频同时喂给驱动模块保证口型同步。
- 素材：一张正面、无遮挡、光照均匀的人像图（≥512，或 5-10s 正面视频）；模型权重（onnx/trt，约数 GB）；NVIDIA GPU（TensorRT，CPU 推理"超级慢"不可用）。

**优点**：照片级拟真，效果震撼。
**代价**：强依赖 NVIDIA GPU + TensorRT；链路从"前端渲染"变成"后端视频流"，集成复杂度高、时延和同步要重新设计；打断/表情/眼神跟随都要围绕视频流重构。**与当前纯前端 RMS 架构差异大，不建议作为第一版。**

### 方案 C：云端数字人 SaaS — 商业化时再评估

腾讯云数智人、火山引擎数字人、阿里云智能数字人等，提供"形象授权 + 语音驱动渲染"，按路数/时长计费，输出视频或实时流。

**优点**：省事、拟真高、可多端。
**代价**：**打破本项目"本地优先"定位**（本地 TTS/LLM、离线可用）；有网络依赖、按量成本、形象授权与数据出域问题。与现有 Electron 桌面离线形态冲突，仅在需要 ToC 大规模发布时考虑。

### 方案 D：2.5D 伪口型（Rive/Lottie/帧动画）— 快速打样

用分层 2D 素材（嘴/眼/眉分层图）+ 简单形变/切换实现"类数字人"，工程量小、无重依赖，但拟真度低，介于 Live2D 与 3D 之间，通常不值得单独投入。

---

## 3. 推荐方案 A 的落地设计

### 3.1 前端：渲染器抽象 + 按类型分发

```
App.tsx
  └─ <AvatarCanvas type={avatarType} />     ← 新增统一入口
        ├─ type === "live2d"  → <Live2DCanvas />   （现状，零改动）
        └─ type === "digital_human" → <DigitalHumanCanvas /> （新增）
```

`DigitalHumanCanvas.tsx`（新）实现与 `Live2DCanvas` 相同的两个桥：

```ts
// 复用现有 useAudioPlayback 的桥，接口签名完全一致
registerSpeaker({
  speak: async (buf, mime) => { /* Three.js 播放音频 + 每帧 RMS 驱动 jawOpen */ },
  stop: () => { /* 停音频、复位口型 */ },
});
registerExpressionSetter((name) => { /* 情绪 → blendshape 权重 */ });
```

- 音频播放：沿用 `<audio>` + `OfflineAudioContext` 解码方案（已有成熟实现，直接抽成公共模块复用）。
- 口型：`AnalyserNode` 或解码后采样窗口算 RMS → 每帧 `mesh.morphTargetInfluences[jawIndex] = rms`。
- 表情：目标权重 `lerp` 过渡（避免跳变，对应 Live2D 现在"直接设值"的技术债，这次直接做平滑）。
- 交互：拖拽 = 绕 Y 轴旋转；滚轮 = 缩放；眼神跟随 = 头部/眼球看向指针（`head.lookAt` 或手动算角度）。

### 3.2 后端：`ModelProfile` 泛化为 `AvatarProfile`

最小侵入做法（**Live2D 路径完全不动**）：

1. 新增配置段：
   ```yaml
   avatar:
     type: "digital_human"          # live2d | digital_human
     digital_human:
       model_path: "frontend/public/avatar/avatar.glb"
       profile_path: "frontend/public/avatar/avatar_profile.yaml"
   ```
2. 新增 `backend/avatar/avatar_profile.py`（类比 `model_profile.py`），定义：
   - `mouth_blendshape`（如 `jawOpen`）
   - `expressions: { happy: { mouthSmileLeft: 0.6, ... }, ... }`
   - `idle`（眨眼间隔、表情循环、眼神范围）
3. `main.py` 连接时按 `avatar.type` 发送 `avatar.profile` 消息（或复用 `live2d.profile` 并加 `type` 字段），前端据此选择渲染器。
4. `motion_controller.py` 的**情绪检测逻辑复用**（SER + 关键词 → `happy/sad/surprised/thinking/neutral`），只是最终"表情名"由前端 profile 映射到 blendshape，而非 `.exp3.json`。

### 3.3 改动清单（预估）

| 文件 | 改动 | 性质 |
|------|------|------|
| `frontend/src/components/DigitalHumanCanvas.tsx` | 新增 Three.js 渲染器 + 桥实现 | 新增 |
| `frontend/src/components/AvatarCanvas.tsx` | 按类型分发 | 新增 |
| `frontend/src/App.tsx` | `<Live2DCanvas/>` → `<AvatarCanvas/>` | 小改 |
| `frontend/src/hooks/useAudioPlayback.ts` | 抽公共"解码播放 + RMS"模块（可选） | 重构 |
| `frontend/src/types/index.ts` | 新增 `AvatarProfile` 类型 | 新增 |
| `frontend/package.json` | `+ three`（及 `@types/three`） | 新增 |
| `backend/avatar/avatar_profile.py` | AvatarProfile 契约 | 新增 |
| `backend/main.py` | 发送 `avatar.profile` | 小改 |
| `config.default.yaml` | 新增 `avatar` 段 | 新增 |
| `frontend/public/avatar/` | 放 GLB + profile yaml | 资产 |

---

## 4. 需要准备的素材（模型资产）

### 4.1 方案 A（3D 数字人）所需素材

1. **3D 模型文件 `.glb`/`.gltf`（必需）**
   - 推荐 ReadyPlayerMe：一张正面照 → 生成并**导出 .glb 离线自托管**（约 1–5MB）。
   - 或 VRoid 导出的 `.vrm`（二次元）。
   - 或定制建模导出（注意**blendshape 命名要规范**，至少要有口型、眨眼、眉、嘴角）。
2. **Blendshape 清单（必需，用于写 profile）**
   - 拿到模型后导出 morph target 列表，确认关键名：`jawOpen`（或 `mouthOpen`）、`eyeBlinkLeft/Right`、`eyeWide*`、`browInnerUp`、`browDown*`、`mouthSmile*`、`mouthFrown*`。
   - ReadyPlayerMe 标准 ARKit 52 blendshape 命名见 [TalkingHead](https://github.com/kp-forks/TalkingHead) 与 ARKit 文档。
3. **`avatar_profile.yaml`（必需，我们写）**：逻辑情绪 → blendshape 权重映射、口型 blendshape 名、缩放/朝向、idle 行为。
4. **贴图（多数 GLB 已内嵌，通常无需单独准备）**：`baseColor`/`normal`/`roughness` 等。
5. **可选**：多套服装/发型切换、角色语音（TTS ref 音频，换音色用）、背景/灯光参数。

> ⚠️ 授权注意：ReadyPlayerMe 免费额度面向个人/非商用；商用需确认其订阅条款。自建或购买授权模型可规避。

### 4.2 方案 B（LivePortrait）所需素材

1. **正面人像图（必需）**：单张正面、无遮挡、光照均匀、表情自然，≥512；或 5–10s 正面视频（用于头部动作参考）。
2. **模型权重**：`FasterLivePortrait` onnx/trt 权重（HuggingFace `warmshao/FasterLivePortrait`，数 GB）；音频驱动另需 JoyVASA + `chinese-hubert-base` 权重。
3. **硬件**：NVIDIA GPU + TensorRT（实时 30+ FPS）；CPU/onnxruntime 不可实时。
4. **肖像授权**：使用真人照片需获得本人授权。

### 4.3 方案 C（云端）所需素材

1. 授权形象：上传照片/视频生成数字分身，或选平台预置形象。
2. 云厂商账号 + API Key + 预算（按路数/时长计费）。
3. 稳定的外网访问。

---

## 5. 落地路线图（建议）

1. **Phase 1（1–2 天）**：抽公共"音频解码播放 + RMS"模块；立 `AvatarCanvas` 分发骨架；后端加 `avatar.profile`。此阶段 Live2D 回归不回归，风险最低。
2. **Phase 2（2–3 天）**：`DigitalHumanCanvas` 最小闭环 —— 加载 GLB、RMS 驱动 `jawOpen`、情绪 → 基础 blendshape（happy/surprised/sad/thinking）、打断停止。
3. **Phase 3（1–2 天）**：空闲行为（眨眼、表情循环、眼神跟随、拖拽旋转/缩放）+ 表情 lerp 平滑 + 双形象切换 UI（settings 面板）。
4. **Phase 4（可选）**：口型升级为 viseme 级；接入 LivePortrait 作为"高拟真"二级选项。

---

## 6. 风险与注意点

- **WebGL 上下文**：Three.js 与 PIXI 都占 WebGL；当前设计一次只挂载一个渲染器，天然不冲突；切形象时务必 `renderer.dispose()` 释放上下文，避免 Electron 下 GPU 泄漏。
- **blendshape 命名不统一**：不同模型命名差异大（ReadyPlayerMe/VRM/自建各一套），所以 **profile yaml 必须显式映射逻辑名 → 实际 blendshape**，不要硬编码（这是 Live2D 踩过的坑，`model_profile.yaml` 就是为此）。
- **表情过渡**：直接写 morph 权重会跳变；用逐帧 lerp 逼近目标（对应 Live2D 已知技术债"表情切换加平滑过渡"）。
- **口型幅度**：3D 模型 `jawOpen` 敏感度与 Live2D `ParamMouthOpenY` 不同，需调 RMS 增益系数（现有 `*5` 系数可复用到口型但需重标定）。
- **性能**：GLB 顶点数控制（≤ 30–50k 三角面为宜）；VRM 建议用 `three-vrm` 库而非手写。
- **电子打包**：GLB 需进 `files`/`extraResources`，注意 `frontend/public` 与 `resources` 的打包路径映射。

---

## 7. 参考链接

- [FasterLivePortrait（实时照片驱动，TensorRT 30+ FPS）](https://github.com/warmshao/FasterLivePortrait)
- [LivePortrait（原版，KwaiVGI）](https://github.com/KwaiVGI/LivePortrait)
- [TalkingHead（Ready Player Me 3D 口型，含 ARKit blendshape 清单）](https://github.com/kp-forks/TalkingHead)
- [ReadyPlayerMe（生成带 52 blendshape 的 GLB）](https://readyplayer.me)
- [three.js（渲染引擎）](https://threejs.org)
- [three-vrm（VRM 二次元模型加载）](https://github.com/pixiv/three-vrm)
- 云端数字人选型对比：[腾讯云开发者社区 - 数字人定制平台横向对比](https://cloud.tencent.cn/developer/article/2713706)
