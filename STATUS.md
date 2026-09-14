# 当前开发状态

> ⚠️ 此文件记录**动态**信息，每次切换工作内容时更新。
> 最后更新：2026-07-25（含本地 Docker + Electron 启动验证与两处环境修复）

## 当前位置

- **分支**: `phase-digital-human`
- **阶段**: 数字人形象接入已完成（运行期形象选择 + Three.js 渲染器 + 双向切换）
- **进度**: 计划 Stage 0-7 全部落地（11 个提交）；公开占位素材跑通全链路，
  **真实数字人素材到位后只改 `avatar_profile.yaml`，不改代码**
- **运行态**: Docker 后端（`flexiavatar-backend` + `flexiavatar-ollama`）与 Electron 前端
  已在本地跑通并验证（选择页可用、数字人渲染正常）
- **待办**: 用户视觉/听感验收；换真实素材（RPM/VRoid/自建）

## 本地启动（本机特有，务必注意）

```bash
# 后端（Docker，已在跑；重建才需要）
docker compose --profile gpu up -d

# 前端：必须带 ELECTRON_OVERRIDE_DIST_PATH（见下方"环境修复 ②"）
ELECTRON_OVERRIDE_DIST_PATH=~/.local/share/flexiavatar/electron-dist \
  bash scripts/dev-frontend.sh
```

副本若被清理，重建两行：

```bash
cp -r frontend/node_modules/electron/dist ~/.local/share/flexiavatar/electron-dist
chmod +x ~/.local/share/flexiavatar/electron-dist/electron
```

## 最近提交

```
a750505 fix(frontend): Electron 开发配置补 /api 反向代理
b61d890 fix(frontend): WebSocket 连接改为 App 单点持有（消除切页重连）
66da46b docs: 数字人接入记录 + 渲染器懒加载 + 回归清单
309862d docs: 收录数字人选型/调研输入文档 + 指向施工计划
ba04d2c feat(frontend): 数字人空闲行为 + 双向切换回归（owner token 验收）
6ac70b2 feat(frontend): DigitalHumanCanvas 最小闭环（Three.js + morph 驱动）
8d62b4e feat(frontend): 开始界面形象选择页 + picking 阶段
70606ae feat(backend): 形象清单发现 + avatar.select 握手 + 耦合点①校验
71c8dd6 feat(frontend): AvatarCanvas 分发壳 + 形象 profile 类型契约
4e12bae refactor(frontend): 抽出公共口型模块 + 桥 owner token
6a85652 chore: 数字人前置 — three 依赖 + 验证素材脚本 + 目录准备
```

## 本轮核心变化

### 数字人形象接入（2026-07-25，`phase-digital-human`）

计划与验收清单：`docs/digital-human-avatar-plan.md`（含实测数据回填）

**交互（startup → picking → loading → ready）**
- 开始界面新增「选择形象」页：模式页签（数字人 / Live2D）+ 卡片网格，
  点卡片即提交（后端校验 + 加载），成功才进主界面
- 预留 `persona_id` / `voice_id` 关联字段（本版只解析/透传/显示，不消费）——
  将来"选角色（形象+人设+音色）"是填语义而非改结构

**后端**
- `backend/avatar/`：`avatar_profile.py`（契约，两类 schema 通吃）、
  `catalog.py`（目录发现 + URL 换算 + 白名单）、`select.py`（选择逻辑，无 FastAPI 依赖，可单测）
- `GET /api/avatars` 清单；WS `avatar.select` 握手；`avatar.profile`（带 `type` 判别）
  与旧 `live2d.profile` 双发兼容
- **耦合点①落地**：persona 映射出的情绪若当前形象缺失 → 列清单 + 回退 neutral
  （实测：有马加奈缺 `angry`，切换时警告可见）

**前端**
- `useLipSyncAudio`：从 Live2DCanvas 抽出的公共口型模块（进程级单例，
  兼容 StrictMode 双挂载；拉取式 `getRMS()`）
- **桥 owner token**：解决"切换渲染器时旧画布 cleanup 踢掉新画布音频桥"的隐患
- `DigitalHumanCanvas`：Three.js + morph 驱动（口型/表情/眨眼分通道 + 逐帧合成 + lerp）；
  KTX2/meshopt 解码器支持；缺 morph 时整通道降级不崩
- 渲染器懒加载：主包 829KB → 213KB，两个渲染器各成独立 chunk

**验证方式（可复现）**
- 后端 61 个新测试（catalog 32 + profile 29），合并既有 92 passed
- CDP 驱动真实 Chrome + 真实后端 + 真实 GLB：口型轨迹、
  表情 lerp、整脸 morph 路径、缺 morph 降级、7 轮双向切换回归
- dev 排查口：`window.__digitalHuman`（morph 索引/权重）、`__lipSyncState`（桥归属）、
  `__lipSyncProbe`（强制 RMS，headless 无手势时验证口型通道）、`__agentStore`

### 启动验证中修掉的两处环境问题（2026-07-25）

**① npm script 在 NTFS 挂载上跑不起来**（`sh: vite: Permission denied`，exit 126）
仓库在 `/media/jason/D`（fuseblk/NTFS，`default_permissions`），`node_modules/.bin`
的 shim 没有可执行位且 `chmod +x` 存不住 → `vite`/`tsc`/`oxlint` 全部无法执行。
已把 `frontend/package.json` 的 script 改为 **node 显式调用 CLI**（对任何文件系统有效）：

```
"dev": "node node_modules/vite/bin/vite.js"
"build": "node node_modules/typescript/bin/tsc -b && node node_modules/vite/bin/vite.js build"
```

**② Electron 二进制同样缺可执行位**（`vite-plugin-electron` 用 `spawn()` 直接执行它）
用 `ELECTRON_OVERRIDE_DIST_PATH` 指向 ext4 侧的副本绕过，不改仓库配置：

```bash
cp -r frontend/node_modules/electron/dist ~/.local/share/flexiavatar/electron-dist
chmod +x ~/.local/share/flexiavatar/electron-dist/electron
```

> 想彻底解决可 `sudo mount -o remount,metadata /media/jason/D` 让该盘支持权限位（需 sudo）。

**③ Electron 侧 `/api` 代理缺失（真实缺陷，已修）**
`a750505`：Stage 4 只把 `/api` 反代加进了 `vite.config.web.ts`，漏了
`vite.config.ts` → `npm run electron:dev` 上 `/api/avatars` 被 Vite 兜底成
`index.html`，选择页报 `Unexpected token '<'`、整页不可用。
**教训：两套 vite config 的行为差异必须各自在 HTTP 层验证一次。**

### 素材现状（2026-09 复测，配代理）

- **Ready Player Me 作废**：`readyplayer.me` / `models.readyplayer.me` / `api.` / `docs.`
  在权威 DNS 中均无 A 记录（`models.` 为 NXDOMAIN）→ 官方通道彻底失效，**与代理无关**
  （同期 GitHub/VRoid/Sketchfab/Mixamo 走代理全部 200）。
- **改用 VRoid**：已接入 three-vrm 官方示例 VRM 为 `digital_human/vroid`
  （`avatar_profile.yaml` 入库，10.7MB 模型由脚本下载、已 gitignore），实测渲染通过：
  57 morph、口型 `Fcl_MTH_A` 随 RMS 驱动、眨眼生效、MToon 材质与发型正常。
  已知限制：静止 T-pose（本渲染器不驱动骨骼）、无 lookAt morph（眼神通道跳过）。
- `scripts/fetch-placeholder-avatars.sh` 新增 `--with-vrm`，并内置**系统代理探测**
  （gsettings 的 host/port），解决"系统代理已设但 shell 无 `*_proxy` 变量"的常见坑。

**已知噪声（非本轮引入）**
- Live2D 挂载时 1 次 `[Live2D] WebGL context LOST`：源自 PIXI 在 StrictMode
  双挂载下销毁旧上下文，该监听器原有代码即存在；canvas 数不增长、功能无影响

## 上一轮核心变化

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
