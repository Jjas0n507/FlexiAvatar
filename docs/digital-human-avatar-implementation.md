# 方案 A（3D 数字人）落地技术方案

> 承接 `docs/digital-human-avatar-proposal.md`，聚焦"库选型、库支持程度、素材获取"。
> 最后更新：2026-07-25

---

> ⚠️ **本文档是选型/调研阶段的输入材料**，其中的"落地步骤清单"等章节已由
> [`digital-human-avatar-plan.md`](digital-human-avatar-plan.md) 承接并**全部实施完成**
> （含实测数据回填）。以 plan 为准，本文档保留作决策依据。


## 0. 选型结论

| 素材子路线 | 形象风格 | 渲染库 | 模型加载 | 表情/口型驱动 |
|-----------|----------|--------|----------|---------------|
| **A1：ReadyPlayerMe GLB**（首选） | 半写实/写实 | `three` | `GLTFLoader` | `morphTargetInfluences`（ARKit + Oculus Visemes） |
| **A2：VRoid VRM**（二次元） | 动漫 | `three` + `@pixiv/three-vrm` | `GLTFLoader` + `VRMLoaderPlugin` | `VRMExpressionManager`（preset 表情 + 口型） |

- **先做 A1（GLB）**：更符合"数字人"的写实定位，且无需 `three-vrm` 这个额外依赖，链路最短。
- A2 是可选分支，只在需要二次元形象时再上。
- 两条路线**共用同一套前端抽象**（`DigitalHumanCanvas` + 同一对桥接口），只是内部驱动器不同。

> ⚠️ 说明：方案 A 产出的是"3D 虚拟人"（可写实卡通化），**不是真人照片级数字分身**。
> 若目标是某个真人的照片级拟真，需要走 方案 B（LivePortrait）或 3D 扫描重建。

---

## 1. 依赖库清单

| 包 | 版本（写作时） | 用途 | 是否必需 |
|----|--------------|------|----------|
| `three` | 最新 stable（r17x+；示例基准 `0.164.1`） | WebGL 渲染、场景/相机/灯光 | ✅ 必需 |
| `@pixiv/three-vrm` | `3.5.x`（v1 起支持 VRM1.0，仍兼容 VRM0.x） | 加载 `.vrm`、表情/lookAt/弹簧骨骼 | 仅 A2 |
| `@types/three` | 与 `three` 对齐 | TS 类型 | ✅ dev |
| `GLTFLoader` | three 自带（`three/examples/jsm/loaders/GLTFLoader.js`） | 加载 `.glb`/`.gltf` | ✅ 必需 |
| `DRACOLoader` / `KTX2Loader` | three 自带 | 若模型用 Draco 网格压缩 / KTX2 贴图 | 按需 |
| 口型：`TalkingHead` | GitHub（kp-forks/TalkingHead） | 直接对 RPM GLB 做"文本→viseme"口型，含音素识别 | 可选（viseme 级） |

安装（A1 最少）：

```bash
cd frontend
npm install three
npm install -D @types/three
```

安装（A2 追加）：

```bash
npm install @pixiv/three-vrm
```

> 说明：three.js 与 PIXI 都是 ESM、都占 WebGL，但一次只挂载一个渲染器，不冲突；切形象时 `renderer.dispose()` 释放上下文即可。

---

## 2. 库支持到什么程度

### 2.1 `three.js` + `GLTFLoader`（A1 全程够用）

| 能力 | 支持度 | 备注 |
|------|--------|------|
| 加载 `.glb`/`.gltf` | ✅ 完整 | 含 PBR 材质、贴图、骨骼 |
| **Morph target / blend shape** | ✅ 完整 | `mesh.morphTargetDictionary`（名字→索引）+ `morphTargetInfluences[index]`（权重），这是口型/表情的全部基础 |
| 骨骼蒙皮动画 | ✅ 完整 | `AnimationMixer` + `AnimationClip`（可接 Mixamo idle 动画） |
| Draco / KTX2 压缩 | ✅ 需加载对应 loader | RPM 默认导出一般不含 Draco，按需 |
| 音频 | 不自带（无"口型"概念） | 口型必须自己驱动 morph，见 §4 |

**口型不归 three.js 管**：three.js 只提供"设 blend shape 权重"的 API，不提供"音频→口型"。这正是复用本项目现有 RMS 泵的地方。

### 2.2 `@pixiv/three-vrm`（仅 A2）

| 能力 | 支持度 | 备注 |
|------|--------|------|
| 加载 VRM1.0 / VRM0.x | ✅（v1 起 VRM1.0，向后兼容 0.x） | 以 `GLTFLoader` 插件形式接入：`loader.register(parser => new VRMLoaderPlugin(parser))`，结果在 `gltf.userData.vrm` |
| 表情 | ✅ `vrm.expressionManager` | 标准 preset：`happy` / `angry` / `sad` / `relaxed` / `surprised`，口型 `aa` / `ih` / `ou` / `ee` / `oh`，眨眼 `blink` / `blinkLeft` / `blinkRight` |
| 视线跟随 | ✅ `vrm.lookAt.target` | 指定相机/目标点自动算眼球+头部朝向 |
| 弹簧骨骼（头发/裙摆） | ✅ 内置 | `vrm.update(delta)` 每帧调用 |
| 人形骨骼动画 | ✅ 兼容 VRM Humanoid | 可叠加 Mixamo |
| **口型音素** | ❌ 不自带 | 仍需自己 RMS 驱动 `aa` 等口型 preset |

### 2.3 口型：RMS vs viseme 两条精度档

| 档位 | 实现 | 依赖 | 效果 |
|------|------|------|------|
| **RMS 档（第一版）** | 复用现有 RMS 泵 → 单一"张嘴"权重 | 无 | 嘴随音量开合，与现有 Live2D 同级别，够用 |
| **viseme 档（进阶）** | 文本/音素 → viseme 序列 → 逐帧插值 | `TalkingHead` 或离线 `rhubarb-lip-sync` | 嘴形随发音变化（aa/ee/oh…），更真实 |

**第一版强烈建议 RMS 档**：与现有架构零差异，跑通闭环再谈 viseme。

---

## 3. 素材获取（具体步骤）

### 3.1 路线 A1：ReadyPlayerMe（GLB）

**能拿到什么**：一个带 **ARKit 52 个 blendshape + Oculus Visemes** 的 `.glb`，含 `jawOpen`、`mouthOpen`、`mouthSmileLeft/Right`、`eyeBlinkLeft/Right`、`brow*`、`viseme_*` 等，可离线自托管。

**步骤**：

1. 访问 <https://readyplayer.me>，注册/登录。
2. "Create Avatar" → 选 **Upload a photo**（上传一张正面自拍）或手动捏脸。
3. 定制外观（体型/发型/服装）。
4. **下载 .glb 到本地**：
   - 方式 a：网页下载按钮直接导出 `.glb`。
   - 方式 b：拿到模型 URL（形如 `https://models.readyplayer.me/{avatarId}.glb`），
     追加参数拉全量 morph：`...glb?morphTargets=ARKit,Oculus%20Visemes`，然后 `curl`/浏览器存到本地。
   - 放入 `frontend/public/avatar/`（离线，符合本项目本地优先定位）。
5. **验证 blendshape 清单**（关键，写 profile 前必做）：
   - 打开 <https://gltf-viewer.donmccurdy.com/>，拖入 `.glb`，右侧 **Morph Targets** 面板列出所有名称、可拖动预览。
   - 记录口型 `jawOpen`/`mouthOpen`、眨眼 `eyeBlinkLeft/Right`、表情 `mouthSmile*/mouthFrown*/brow*` 的确切拼写。
   - 或代码里加载后打印 `mesh.morphTargetDictionary`（见 §4.1）。

**授权**：免费额度面向个人/非商用；商用需确认订阅条款。自建/购买授权模型可规避。

### 3.2 路线 A2：VRoid（VRM）

**步骤**：

1. 下载 [VRoid Studio](https://vroid.com/studio)（免费）。
2. 捏人（脸型/发型/服装），保存。
3. **导出 VRM**：菜单 "Export" → VRM。VRoid 导出时自动带上标准 VRM 表情 preset：
   `happy` / `angry` / `sad` / `relaxed` / `surprised` + 口型 `aa`/`ih`/`ou`/`ee`/`oh` + 眨眼。
4. 放入 `frontend/public/avatar/`。
5. 用 `three-vrm` 加载（§2.2），表情直接 `expressionManager.setValue('happy', 1)`，无需手写 blendshape 名。

> 参考资料：[VRoid 导出 VRM 的表情转换规范](https://vroid.pixiv.help/hc/en-us/articles/41131955805977-How-facial-expressions-are-handled-when-exporting-VRChat-avatars-as-VRM)

### 3.3 素材规格建议

| 项 | 建议 |
|----|------|
| 面数 | 头部含 blendshape，总三角面 ≤ 30–50k（桌面端无压力） |
| 贴图 | 2K 以内（baseColor/normal/roughness，GLB 通常已内嵌） |
| 骨骼 | 至少含头/颈/躯干；想要 idle 动作则需 Humanoid 骨骼（可接 Mixamo） |
| 压缩 | 默认不压缩即可；确需减体积再用 Draco（需配 DRACOLoader） |

---

## 4. 关键实现要点（代码级）

### 4.1 加载并读取 morph 索引（A1）

```ts
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

const loader = new GLTFLoader();
const gltf = await loader.loadAsync("/avatar/avatar.glb");
const model = gltf.scene;

// 找到头部 skinned mesh（RPM 通常是 "Wolf3D_Head" 等；更稳妥是遍历找含口型 morph 的 mesh）
const head = model.getObjectByName("Wolf3D_Head") as THREE.SkinnedMesh;
const dict = head.morphTargetDictionary!;      // { jawOpen: 0, mouthSmileLeft: 1, ... }
const influences = head.morphTargetInfluences!;

// 之后每帧：
const jawIdx = dict["jawOpen"];
influences[jawIdx] = rms;                       // 0..1
```

**通用做法**：遍历 `gltf.scene` 所有 `SkinnedMesh`，找到 `morphTargetDictionary` 含 `jawOpen`（或 `mouthOpen`）的那个作为"头部 mesh"，避免依赖固定命名。

### 4.2 RMS → 口型映射

复用现有 `<audio>` + `OfflineAudioContext` 解码采样窗口的 RMS 计算（从 `Live2DCanvas` 抽出公共函数），
把 RMS 映射到张嘴权重：

```ts
// RMS ∈ [0, ~0.2] 原始值，先乘增益再钳制
const open = Math.min(1, rms * GAIN);   // GAIN 需标定，约 4~6
influences[jawIdx] = open;
```

> 注意：3D 模型 `jawOpen` 敏感度与 Live2D `ParamMouthOpenY` 不同，`GAIN` 要重新标定。

### 4.3 表情 → blendshape 权重映射（A1 示例，写进 `avatar_profile.yaml`）

| 情绪 | 映射（权重 0~1） |
|------|------------------|
| `happy` | `mouthSmileLeft` 0.6, `mouthSmileRight` 0.6, `cheekSquintLeft/Right` 0.4 |
| `sad` | `browInnerUp` 0.5, `mouthFrownLeft/Right` 0.4, `mouthShrugUpper` 0.3 |
| `surprised` | `browInnerUp` 0.7, `eyeWideLeft/Right` 0.6, `jawOpen` 0.25 |
| `thinking` | `browDownLeft/Right` 0.4, `mouthPressLeft/Right` 0.3 |
| `angry`（可选） | `browDownLeft/Right` 0.6, `mouthFrown*` 0.5, `noseSneer*` 0.4 |
| `neutral` | 全部回 0 |

**与现有后端完全对齐**：`motion_controller.py` 的 `detect_emotion()`（SER + 关键词）已输出
`happy/sad/surprised/thinking/neutral`，前端按上表映射即可；`interrupt → surprised` 沿用。

**过渡**：目标权重逐帧 `lerp`（`cur += (target - cur) * k`，k≈0.2/帧），避免跳变。

### 4.4 眨眼 / 眼神跟随 / 空闲

- **眨眼**：定时器随机触发，`eyeBlinkLeft/Right` 用"快速闭合-缓慢张开"包络（或复用 profile 的 `blink_interval`）。
- **眼神跟随**：`head.lookAt(pointerWorldPoint)` 或手动算角度写头/眼球 rotation；A2 用 `vrm.lookAt.target`。
- **拖拽/缩放**：拖拽 = 绕 Y 轴旋转 `model.rotation.y`；滚轮 = `model.scale` 或相机距离（对应现有 Live2D 交互语义）。
- **idle 动画**（可选）：Mixamo 下载 "Idle"（勾选 In Place）→ `AnimationMixer` 循环播放，说话时切到轻微 "Talking" 动画。

### 4.5 与现有桥对接（零改后端的关键）

```ts
// DigitalHumanCanvas.tsx 内部，加载完成后：
registerSpeaker({
  speak: async (buf, mime) => { /* 解码 + <audio> 播放 + 每帧 rms→jawOpen */ },
  stop: () => { /* 停音频、jawOpen 归零 */ },
});
registerExpressionSetter((name) => { /* name → 上表权重 lerp 目标 */ });
```

`useAudioPlayback.ts`、后端 `tts.audio` / `live2d.control` / `playback.done` **全部不动**。

---

## 5. 落地步骤清单

1. **Dependency**：`npm i three` + `@types/three`。
2. **素材**：按 §3.1 生成并下载 RPM `.glb`，glTF Viewer 确认 blendshape 名，写 `avatar_profile.yaml`。
3. **抽公共模块**：把 `Live2DCanvas` 的"解码 + RMS"抽成 `useLipSyncAudio()`，两处复用。
4. **`DigitalHumanCanvas.tsx`**：加载 GLB → 读 morph 索引 → 实现 speak/stop/expression/眨眼/眼神/拖拽缩放。
5. **`AvatarCanvas.tsx` 分发**：`App.tsx` 按 `avatar.type` 渲染 Live2D 或 DigitalHuman。
6. **后端**：`avatar_profile.yaml` 解析 + 连接时发 `avatar.profile`（带 `type`）。
7. **回归**：Live2D 路径跑通不受影响；切到 digital_human 验证口型/表情/打断。

---

## 6. 参考链接

- [three.js](https://threejs.org) / [GLTFLoader](https://threejs.org/docs/#examples/en/loaders/GLTFLoader)
- [@pixiv/three-vrm（VRM1.0 + VRM0.x）](https://github.com/pixiv/three-vrm) / [API 文档](https://pixiv.github.io/three-vrm/packages/three-vrm/docs)
- [ReadyPlayerMe](https://readyplayer.me)（生成带 ARKit/Visemes morph 的 GLB）
- [RPM GLB + morph 用法（Convai 文档，含 `?morphTargets=ARKit,Oculus Visemes`）](https://docs.convai.com/api-docs/plugins-and-integrations/web-plugins/glb-characters-for-convai)
- [glTF Viewer（查 morph target 名称）](https://gltf-viewer.donmccurdy.com/)
- [VRoid Studio](https://vroid.com/studio) / [VRoid 导出 VRM 表情规范](https://vroid.pixiv.help/hc/en-us/articles/41131955805977-How-facial-expressions-are-handled-when-exporting-VRChat-avatars-as-VRM)
- [TalkingHead（RPM GLB 的 viseme 级口型参考）](https://github.com/kp-forks/TalkingHead)
