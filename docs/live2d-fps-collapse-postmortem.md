# Live2D 帧率坍塌排障实录（Postmortem）

> 分支：`phase-voice-upgrade` → `phase-pixi-renderer`（2026-07-16 ~ 2026-07-19）
> 症状：Live2D 运行数秒后 FPS 从 60 永久坍塌到 9~13；且"要重试好几次启动才是 60"。
> 结论：**双根因叠加**，六层排查，五个"修了但不是它"的中间理论，最终换掉渲染库收场。
> 顺带揪出三个陪葬 bug：音频静默、比心四只手、表情系统被清零机制碾压。

---

## TL;DR

| # | 根因 | 证据 | 修复 |
|---|------|------|------|
| 1 | `live2d-renderer@0.6.6` 动作系统缓存键错位：存 `${group}_${groupIndex}`（同组互相覆盖），查 `${group}_${motionIndex}` → **永远 miss** → 每次起动作全量重解析 motion3.json；空闲动作自动重启循环放大成每帧重解析 | 逐调用点包裹профiler 实测 `motion 89.0ms×33`；堆 707→1022MB 锯齿（~40MB/s 分配）；坍塌起点 = 第一个 Idle 动作播完（~21s） | 打补丁未根治（ebbb23c 后依旧 93ms）→ 整体置换为 `pixi-live2d-display`（74cc68d） |
| 2 | **snap 版 VSCode 集成终端污染环境**：`GTK_PATH`/`GIO_MODULE_DIR`/`LD_LIBRARY_PATH` 泄漏 core20 旧库路径 → Electron GPU 进程加载到旧 libstdc++ 后起不来 → 全软件渲染 | 控制台 `GLIBCXX_3.4.32 not found` + gio-modules 报错；`app.getGPUFeatureStatus()` 全 `disabled_software`；同一份代码在干净终端 100% 硬件加速 | 净化启动脚本 `scripts/dev-frontend.sh`（9ccce52） |

两个根因**互相掩护**：根因 2 让启动帧率像掷骰子（有时 11 有时 60），根因 1 让侥幸拿到 60 的那些 boot 在 ~21 秒后必然坍塌。任何单一修复都会被另一个的症状"证伪"，这是本案拖长的核心原因。

---

## 症状时间线

1. 历史阶段（音素口型时代）：FPS 常年 11~13，归咎于"渲染太重"，没人深究。
2. 语音重做后（RMS 口型 + `<audio>` 播放）：开局 60，几秒~二十秒后掉到 9~13，**期间一动未动**（排除交互触发）。
3. 用户关键观察："要重试好几次才会开始时为 60，大部分时候为 11" —— 事后看，这句话直接指向根因 2 的非确定性。

## 六层排查：理论 → 证伪

每一层都"修好了一个真实存在的问题"，但 FPS 依旧坍塌 —— 直到插桩拿到实锤。

| 层 | 理论 | 动作（commit） | 结局 |
|---|------|----------------|------|
| 1 | 后端音素时间轴估算不准拖累前端对齐 | RMS 口型重做，删整条音素链路（3e309c4, 41b5e74） | 口型架构确实该换（估算时间轴在任何免费 TTS 下都对不准），但 FPS 没救回来 |
| 2 | 主线程 `AudioContext` 播放拖死 WebGL（AMD 平台） | 播放改走 `<audio>` 媒体线程，解码用 `OfflineAudioContext`（7338035, ce460e6） | 架构更干净了；FPS 依旧坍塌 |
| 3 | 麦克风 `ScriptProcessorNode` 主线程回调 | 采集改 `MediaStreamTrackProcessor`（2cd8d05） | 事后发现用户**一直用文字聊天**，麦克风从未参与 —— 理论直接出局 |
| 4 | GPU 被黑名单/软渲染 | 加 `ignore-gpu-blocklist` 等 flags | **反向翻车**：加 flags 后开局就 11 fps，回退。（讽刺的是方向没全错——见根因 2） |
| 5 | 库泄漏的 `AudioContext`（构造函数里 `new AudioContext()`，StrictMode 幽灵实例永不关闭） | 注入 OfflineAudioContext 堵漏（97365b4） | 泄漏是真的、修复经 pactl 验证生效 —— 但 FPS 依旧坍塌 |
| 6 | **不猜了，上插桩** | 渲染循环打 `FPS \| 裸 rAF \| update 耗时 \| 堆`，再对 update 内部逐调用点包裹计时 | `motion 89.0ms×33`、堆锯齿、坍塌起点=首个动作播完 —— **根因 1 现形** |

### 插桩输出（定案证据）

```
[Live2D] FPS: 60 | bare rAF: 60 | update: 1.2ms | heap: 210MB   ← 前 21 秒
[Live2D] FPS: 11 | bare rAF: 12 | update: 90.3ms | heap: 707MB  ← Idle 动作第一次播完之后
[Live2D] profile: motion 89.0ms×33  ← update 内 33 次调用全花在 motion 上
```

`bare rAF` 与 FPS 同步坍塌 + update 90ms → 不是"别人抢主线程"，就是 update 自己慢；逐调用点包裹后指名道姓是 `MotionController`。读库源码确认缓存键错位（详见 TL;DR），且 `randomMotion` 自动重启把"每次起动作重解析一次"放大成持续风暴。

### 为什么打补丁没完（ebbb23c → 74cc68d）

`patch-live2d.cjs` 修正缓存键后实测仍有 `motion 93ms` —— 该库动作系统还有第二层问题（未再深挖）。此时已在同一个库里修过：模块级 rAF id、播放头累积、Node path require、构造函数 AudioContext 泄漏、缓存键 —— **五个补丁之后还有第六个坑，就不该再考古了**。经用户拍板（"如果难以解决还是换掉live2d渲染吧"），整体置换为 amadeus 同款栈 `pixi-live2d-display@0.4.0 + pixi.js@6.5.10`，口型算法/播放队列/WS 协议/后端全部原样保留。

### 根因 2 的现形

换库后仍有 boot 全程 11 fps，且控制台出现：

```
GLIBCXX_3.4.32 not found
Failed to load module: .../gio/modules/...（core20 路径）
[GPU] {"webgl":"disabled_software","gpu_compositing":"disabled_software",...}
```

同时系统级体检（`readlink /sys/class/drm/card*`、内核日志、时钟频率）证明 6800 XT 硬件完全健康。矛头指向环境：snap 版 VSCode 的集成终端会把 core20 的 `GTK_PATH`/`GIO_MODULE_DIR`/`LD_LIBRARY_PATH` 等泄漏给子进程，Electron 的 GPU 进程加载到 5 年前的 libstdc++ 后直接躺平 → Chromium 静默降级软渲染。**从干净终端（或 `scripts/dev-frontend.sh`，内部 unset 全部污染变量）启动后，每次 boot 都是稳定 60 fps。**

---

## 置换渲染库的连环坑（供后人参考）

| 坑 | 症状 | 修复（commit） |
|---|------|----------------|
| pixi6 引用 Node `url` | `Uncaught ReferenceError: require is not defined` | alias 到 browserify shim（117f31a）仍不够 → 摘除 `vite-plugin-electron-renderer`（其依赖预打包器绕过 resolve.alias，784d02d） |
| cubism4 子包在 **import 时**即检查 `window.Live2DCubismCore` | `Could not find Cubism 4 runtime` | `index.html` 在 module bundle 之前同步加载 core（9ccce52） |
| pixi 参数语义 = 每帧 `loadParameters` 回滚 | 旧代码"清零 emoji 参数"机制成为最后写者，碾掉原生表情和动作曲线；oneShot 只写一帧根本看不见 | 废除清零机制，覆写改整体替换语义（3115a91） |

## 陪葬 bug 清单（排查途中顺手揪出）

1. **音频静默**：后端日志 11/11 次 `playback.done timeout` —— 语音重做后音频链路**从未真正通过**，只是所有人都在盯 FPS。E2E 探针洗清后端（mp3 魔数/协议字段全对）后给前端桥加了全链路分段日志（WS收包→入队→decode→play→ended，3115a91），此后恢复正常且口型同步。确切断点没抓到现行；日志永久保留作回归保险。
   **2026-07-19 补记（已定案）**：CDP 活体取证抓到两个真凶，超时其实一直都在——
   - **后端自死锁（主因）**：`handle_chat_text` 在 WS 接收循环里同步 `await respond()`，而 respond 等的 `playback.done` 只能从**被它堵死的同一个接收循环**里读出来 → 文字聊天 100% 假超时（3 条 done 一直躺在 socket 缓冲区）。语音路径因 `_process_speech` 走 `create_task` 而幸免。修复：文字路径同样 `create_task` + IDLE 门卫。
   - **前端孤儿 socket（副因）**：StrictMode 双挂载下重复 `connect()`，旧 socket 的闭包 handler 继续喂消息（**能收**），但 `this.ws` 已易主或为 null（**不能发**）——上行静默丢失。修复：connect 幂等（CONNECTING 也不重建）+ 所有回调身份守卫 + disconnect 先易主再 close。
   - 当时"恢复正常"只是音频下行本来就通（孤儿也能收），上行 done 从未到过后端。修复后日志史上第一次出现 `Playback confirmed by frontend`。
2. **比心四只手**：`随机姿势.motion3.json` 把 `Paramemoji3`（笔芯手）挂 1 整整 87 秒，却把 `Paramemoji4`（正常手开关）留在 0 —— **动作文件自己忘了藏正常手**，任何播放器下都是四只手，所以"存在很久"。资产级修复：emoji4 曲线 0→1。（对照组：`笔芯.exp3.json` 作为 VTS 快捷键写法是两个参数一起动的，是正确姿势。）
3. **害羞/哭泣表情从未显示过**：清零机制每帧把 emoji1-7 归零，pixi 更新序中我们的钩子在 expressionManager **之后** → 原生表情写完立即被抹掉。废除清零后恢复。

## 经验教训

1. **插桩先于理论。** 前五层每层都修了"真问题"，但只有逐调用点计时找到了真凶。渲染循环的 `FPS | 裸 rAF | update 耗时 | 堆` 四件套现已常驻。
2. **非确定性故障先怀疑环境。** "重试好几次才 60"这种掷骰子行为，代码 bug 很难解释，环境污染完全可以。snap 终端泄漏 core20 库路径这一坑，已固化进 `scripts/dev-frontend.sh` 与 CLAUDE.md。
3. **给第三方库打第五个补丁时，该考虑换库了。** 沉没成本不是继续考古的理由。
4. **跨渲染器移植参数写入代码前，先验证更新序与回滚语义。** "持久写"与"每帧回滚"两种世界观下，同一段代码行为完全相反（清零机制在旧库是必要的，在 pixi 是破坏性的）。
5. **沉默的失败最贵。** 音频断了好几天，被 FPS 的噪音完全掩盖——后端明明每次都在告警（`playback.done timeout`），没人看。关键链路的每一环都要有日志，错误不许静默吞掉（`el.onerror = () => resolve()` 这种写法是事故温床）。

## 相关提交（时间序）

```
e72dd47  Phase A: 修协议不匹配 tts.speech → tts.audio
45b0349  Phase B: LLM 流式增量 TTS
6171aa3  Phase C: 口型时钟统一
3e309c4  重做1+2: RMS 口型后端，删音素机器，统一 respond()
41b5e74  重做3: 前端 RMS 播放引擎
fcfc7f7  重做5: CosyVoice2 适配器
7338035  理论2: 音频出口改 <audio> 媒体线程
2cd8d05  理论3: 麦克风改 MediaStreamTrackProcessor
97365b4  理论5: 堵库的 AudioContext 泄漏
ebbb23c  根因1补丁: 动作缓存键修正（未根治）
74cc68d  置换: pixi-live2d-display + pixi6
117f31a  坑1a: url alias
784d02d  坑1b: 摘除 vite-plugin-electron-renderer
9ccce52  根因2: cubism core 前置 + snap 净化启动脚本
3115a91  陪葬bug: 表情去清零 + 藏正常手 + 音频分段日志
```
