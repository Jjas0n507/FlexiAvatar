# Live2D 动画系统全面升级计划

## Context

当前 `MotionController` 实现了基础口型同步和关键词情绪检测，但存在**两类根源性问题**：

### A. 模型强耦合（架构缺陷）
前后端代码直接硬编码了"有马加奈"模型的参数名、表情名、motion group 名，**换个模型就跑不起来**：
- `motion_controller.py` 引用的 `("listen", 0)`, `("think", 0)` motion group **在模型中不存在**（模型只有 `Idle` 和 `Random`）
- `"idle"` vs `"Idle"` 大小写都不匹配 → motion 指令发出去前端静默失败
- `ParamMouthA/I/U/E/O` 五个参数在模型 LipSync group 中不存在（模型只有 `ParamMouthOpenY` + `ParamMouthForm`）
- `Paramemoji1/2/6/7` 是此模型特有的 emoji 参数，换个模型参数 ID 完全不同
- 6 个内置 `.exp3.json` 是中文名（害羞/空洞眼/哭泣...），后端发英文名（happy/surprised），永远对不上

### B. 动画表现力不足（产品缺陷）
1. **纯文本关键词驱动情绪** — 无法感知反讽、疲惫等语音韵律
2. **强制闭口帧导致口型抽搐** — 每音素末尾硬塞 `mouth: "N"`，快速说话时嘴巴高频开合
3. **说话时表情全程不变** — 5 秒 TTS 从头到尾一个表情，"念稿纸片人"
4. **空闲状态缺乏生物本能** — 随机选动作，没有视线漂移、呼吸节奏、歪头

### 目标
1. **解耦模型**，实现自由切换 Live2D 角色
2. **升级动画**，解决四个表现力缺陷
3. 每个 Phase 可独立测试、独立 merge

---

## 核心架构：ModelProfile — 模型抽象层

引入 `model_profile.yaml` 作为模型和代码之间的抽象层。每个模型目录下放置一份，描述该模型支持哪些参数、表情、动作。

**目录结构**：
```
frontend/public/live2d/
├── 有马加奈/
│   ├── model_profile.yaml    ← 新增：模型抽象描述
│   ├── 有马加奈.model3.json
│   ├── 有马加奈.moc3
│   └── ...
└── 其他角色/                  ← 新模型只需放下此目录
    ├── model_profile.yaml
    ├── xxx.model3.json
    └── ...
```

**`model_profile.yaml` 完整结构**：
```yaml
# Live2D 模型抽象描述 — 前后端共同遵守的契约
# 每个模型目录下放置一份，前后端各自加载

model:
  name: "有马加奈"
  model3_path: "有马加奈.model3.json"
  scale: 1.2

# —— 参数映射：逻辑名 → 此模型实际的 Cubism Parameter ID ——
parameters:
  # 口型（模型 LipSync group 的实际参数）
  lip_sync:
    open_y: "ParamMouthOpenY"   # 纵向张开
    form: "ParamMouthForm"      # 横向宽度

  # 眼部
  eyes:
    left_open: "ParamEyeLOpen"
    right_open: "ParamEyeROpen"
    left_smile: "ParamEyeLSmile"
    right_smile: "ParamEyeRSmile"
    eyeball_x: "ParamEyeBallX"
    eyeball_y: "ParamEyeBallY"

  # 眉毛
  brows:
    left_y: "ParamBrowLY"
    right_y: "ParamBrowRY"
    left_x: "ParamBrowLX"
    right_x: "ParamBrowRX"

  # 头部/身体
  head:
    angle_z: "ParamHeadAngleZ"
  body:
    angle_x: "ParamBodyAngleX"

  # 额外参数（模型特有的 emoji 等，表情 fallback 时需要重置）
  extra: ["Paramemoji1", "Paramemoji2", "Paramemoji6", "Paramemoji7"]

# —— 口型映射：A/I/U/E/O/N → 具体参数值 ——
mouth_shapes:
  A: { open_y: 0.8, form: 0.0 }
  I: { open_y: 0.3, form: 0.8 }
  U: { open_y: 0.3, form: -0.5 }
  E: { open_y: 0.5, form: 0.0 }
  O: { open_y: 0.6, form: -0.2 }
  N: { open_y: 0.0, form: 0.0 }

# —— 表情映射：逻辑情绪 → 模型实现 ——
expressions:
  neutral:
    # type: "native" 使用 .exp3.json 内置表情
    # type: "params" 使用原始参数控制
    type: "native"
    name: null            # null = 不做任何操作

  happy:
    type: "native"
    name: "害羞"          # 模型内置 .exp3.json 的 Name

  surprised:
    type: "params"
    params:
      ParamEyeLOpen: 1.2
      ParamEyeROpen: 1.2
      ParamBrowLY: 0.5
      ParamBrowRY: 0.5

  sad:
    type: "native"
    name: "哭泣"

  thinking:
    type: "params"
    params:
      ParamBrowLX: -0.2
      ParamBrowRX: 0.2

# —— 动作映射：逻辑动作 → (Motion Group, Index) ——
motions:
  listening:
    - { group: "Idle", index: 0 }
    - { group: "Idle", index: 1 }

  processing:
    - { group: "Idle", index: 1 }

  idle:
    - { group: "Idle", index: 0 }
    - { group: "Idle", index: 1 }
    - { group: "Random", index: 0 }

# —— 空闲行为 ——
idle:
  expression_cycle: ["neutral", "happy", "thinking"]
  expression_interval: [5.0, 12.0]   # 秒
  blink_interval: [2.0, 6.0]         # 秒
  eye_drift_range: 0.15
  head_tilt_chance: 0.15
  head_tilt_angle: 0.1
```

**加载机制**：
- **后端**：`ModelProfile.load(model_dir)` 读取 YAML，构造 `ModelProfile` 对象供 `MotionController` 使用
- **前端**：后端在 WebSocket 连接建立后发送一条 `live2d.profile` 消息，携带 profile 的 JSON 序列化版本，前端存储到 ref 中

---

## Phase 0：模型解耦（BLOCKER — 必须先做）

> 这是最关键的架构改造。所有后续 Phase 都建立在解耦后的抽象层上。

### 0.1 新建 ModelProfile

**新建** `backend/live2d/model_profile.py`：

```python
@dataclass
class ParameterIds:
    """模型实际参数 ID"""
    lip_open_y: str = "ParamMouthOpenY"
    lip_form: str = "ParamMouthForm"
    eye_left_open: str = "ParamEyeLOpen"
    eye_right_open: str = "ParamEyeROpen"
    eye_left_smile: str = "ParamEyeLSmile"
    eye_right_smile: str = "ParamEyeRSmile"
    eyeball_x: str = "ParamEyeBallX"
    eyeball_y: str = "ParamEyeBallY"
    brow_left_y: str = "ParamBrowLY"
    brow_right_y: str = "ParamBrowRY"
    brow_left_x: str = "ParamBrowLX"
    brow_right_x: str = "ParamBrowRX"
    head_angle_z: str = "ParamHeadAngleZ"
    body_angle_x: str = "ParamBodyAngleX"
    extra: list[str] = field(default_factory=list)  # 表情 fallback 需要重置的额外参数

@dataclass
class MouthShapeParams:
    open_y: float
    form: float

@dataclass
class ExpressionDef:
    type: str  # "native" | "params"
    name: str | None = None       # native 模式下的 .exp3.json Name
    params: dict[str, float] | None = None  # params 模式下的参数映射

@dataclass
class MotionDef:
    group: str
    index: int

@dataclass
class IdleConfig:
    expression_cycle: list[str]
    expression_interval: tuple[float, float]
    blink_interval: tuple[float, float]
    eye_drift_range: float
    head_tilt_chance: float
    head_tilt_angle: float

@dataclass
class ModelProfile:
    name: str
    model3_path: str
    scale: float
    parameters: ParameterIds
    mouth_shapes: dict[str, MouthShapeParams]
    expressions: dict[str, ExpressionDef]
    motions: dict[str, list[MotionDef]]
    idle: IdleConfig

    @classmethod
    def load(cls, model_dir: str | Path) -> "ModelProfile":
        """从 model_profile.yaml 加载"""

    def to_frontend_dict(self) -> dict:
        """序列化为前端可用的 JSON"""
```

### 0.2 消除重复代码 + 拼音表统一

**新建** `backend/live2d/mouth_shapes.py` — 拼音→口型映射（无模型依赖，纯语言学规则）：
- 移入两份重复的 pinyin→mouth 表，合为一份 `PINYIN_TO_MOUTH`
- 导出 `pinyin_final_to_mouth(final: str) -> str`
- 不依赖 ModelProfile（拼音到 A/I/U/E/O 的映射是语言规则，不是模型配置）

**修改** `backend/tts/edge_tts_adapter.py`：
- 删除 `_PINYIN_TO_MOUTH` 表
- `_char_to_mouth()` 改为 import from `mouth_shapes`

**修改** `backend/live2d/motion_controller.py`：
- 删除 `_PHONEME_TO_MOUTH` 表

### 0.3 MotionController 重构为接受 ModelProfile

**修改** `backend/live2d/motion_controller.py`：

```python
class MotionController:
    def __init__(self, profile: ModelProfile):
        self.profile = profile

    def _mouth_params(self, mouth: str) -> dict[str, float]:
        """从 profile 读取口型参数，使用模型实际的参数 ID"""
        shape = self.profile.mouth_shapes.get(mouth)
        pid = self.profile.parameters
        return {
            pid.lip_open_y: shape.open_y,
            pid.lip_form: shape.form,
        }

    def get_expression_for_text(self, text: str) -> ExpressionCommand:
        # 返回逻辑表情名（如 "happy"），具体参数由前端根据 profile 解析

    def get_motion_for_state(self, state: str) -> MotionCommand | None:
        """从 profile 读取实际 motion group 名和 index"""
        motion_defs = self.profile.motions.get(state)
        if not motion_defs:
            return None
        d = random.choice(motion_defs)
        return MotionCommand(group=d.group, index=d.index, priority=1)
```

**关键变化**：
- 所有参数名从 `self.profile.parameters` 读取，不再硬编码
- Motion group 名从 `self.profile.motions` 读取
- `_mouth_params()` 只输出模型真实支持的参数

### 0.4 后端启动时加载 ModelProfile

**修改** `backend/main.py` 启动流程：
```python
profile = ModelProfile.load(config.get("live2d.model_dir"))
motion_controller = MotionController(profile)
# WebSocket 连接建立时发送 profile
```

**修改** `backend/config.default.yaml`：
```yaml
live2d:
  model_dir: "frontend/public/live2d/有马加奈"  # 指向模型目录而非具体文件
```

### 0.5 WebSocket 协议：`live2d.profile`

**新增消息类型**：`{type: "live2d.profile", payload: <ModelProfile.to_frontend_dict()>}`

**修改** `frontend/src/hooks/useWebSocket.ts`：
- 接收 `live2d.profile` 消息
- 存储到 Zustand store 或直接设置到 Live2DCanvas 的 ref

### 0.6 前端根据 Profile 驱动渲染

**修改** `frontend/src/components/Live2DCanvas.tsx`：

**`MODEL_PATH`** → 从 profile 读取：
```typescript
const MODEL_PATH = `/live2d/${profile.name}/${profile.model3_path}`;
```

**`setExpression()`** → 从 profile 读取表达式定义：
```typescript
const setExpression = (name: string, intensity: number = 1.0) => {
    const exprDef = profile.expressions[name];
    if (!exprDef) return;

    if (exprDef.type === "native" && exprDef.name) {
        model.setExpression(exprDef.name);
    } else if (exprDef.type === "params" && exprDef.params) {
        // 按 profile.parameters.extra 重置额外参数
        // 按 intensity 缩放 params 值
        for (const [paramId, baseValue] of Object.entries(exprDef.params)) {
            model.setParameter(paramId, baseValue * intensity);
        }
    }
};
```

**`setMouthParams()`** → 使用 profile 中的参数 ID：
```typescript
const setMouthParams = (openY: number, form: number) => {
    const pid = profile.parameters;
    model.setParameter(pid.lip_sync.open_y, openY);
    model.setParameter(pid.lip_sync.form, form);
};
```

**`getAvailableMotions()`** → 从 profile 读取（不再解析 motion ID 字符串）

**前端 profile 来源**：连接建立时后端发送，存储在 `profileRef`。初始渲染使用默认值（硬编码 fallback 保留，与当前"有马加奈"兼容）。

### 0.7 为现有模型创建 model_profile.yaml

**新建** `frontend/public/live2d/有马加奈/model_profile.yaml`：
- 按上述 schema 编写，数据从当前硬编码值迁移
- Motion 映射修正：`listening → Idle[0,1]`, `processing → Idle[1]`, `idle → Idle[0,1] + Random[0]`

### Phase 0 验证
1. `ModelProfile.load()` 能正确解析 model_profile.yaml
2. 启动后端，检查 WebSocket `live2d.profile` 消息内容
3. 前端加载后口型、表情、motion 与修改前行为一致（回归验证）
4. 修改 `config.default.yaml` 的 `model_dir` 为不存在的路径，应报清晰错误

---

## Phase 1：顺滑口型 + 韵律驱动

> 依赖 Phase 0 的 ModelProfile 和 mouth_shapes.py

### 1.1 去强制 N 帧 + 智能闭口

**修改** `backend/live2d/motion_controller.py` — `phonemes_to_lip_sync()`：

```
遍历 phoneme 列表，对每个 p_i：
  1. 生成 p_i 的起始口型帧（time = p_i.start_ms）
  2. 计算 gap = p_{i+1}.start_ms - p_i.end_ms
     - gap > CLOSE_GAP_THRESHOLD (200ms) → 在 gap 中间插入过渡帧：
         time = p_i.end_ms + gap*0.3  → 微张 (open_y * 0.3)
         time = p_i.end_ms + gap*0.7  → 闭嘴 (N)
     - gap ≤ 200ms → 不插入，前端自然插值
  3. 最后一个 phoneme → 在 end_ms + 100ms 处插入闭嘴帧
  4. 标点对应的 phoneme（检测 text 中的 。！？）→ end_ms 处强闭口
```

注意：当前 `Phoneme` 不携带原始字符。需要在 `edge_tts_adapter._boundaries_to_phonemes()` 中为每个 phoneme 附加原始字符（新增 `char: str = ""` 字段），用于标点检测。

### 1.2 WAV RMS 音量提取

**新建** `backend/audio/prosody.py`：
```python
def extract_volume_envelope(
    audio_bytes: bytes,
    frame_ms: float = 50.0,
) -> list[float]:
    """从 WAV 字节流提取归一化 RMS 音量包络 (0.0 ~ 1.0)
    
    使用 pydub（已有 Docker 依赖）+ numpy，不引入 librosa。
    """
```

### 1.3 Phoneme 增加 volume 字段

**修改** `backend/tts/base.py`：
```python
@dataclass
class Phoneme:
    phoneme: str       # A/I/U/E/O/N (口型符号)
    start_ms: float
    end_ms: float
    char: str = ""     # Phase 1 新增：原始字符（用于标点检测）
    volume: float = 0.5  # Phase 1 新增：该音素区间的平均音量
```

**修改** `backend/tts/edge_tts_adapter.py`：
- `_boundaries_to_phonemes()` 为每个 phoneme 附加原始字符
- `synthesize()` 在 WAV 转换后调用 `extract_volume_envelope()`，匹配 phoneme 时间区间赋值 volume

### 1.4 音量驱动口型缩放

**修改** `backend/live2d/motion_controller.py` — `phonemes_to_lip_sync()`：
```python
def _scale_mouth_params(self, base: MouthShapeParams, volume: float) -> dict:
    """音量 → 口型强度：安静时微张，大声时充分张开"""
    pid = self.profile.parameters
    return {
        pid.lip_open_y: base.open_y * (0.3 + 0.7 * volume),
        pid.lip_form: base.form * volume,
    }
```

### 1.5 前端使用后端发送的实际参数值

**修改** `frontend/src/components/Live2DCanvas.tsx` — `applyLipSync()`：
- 优先读取 `frame.params[profile.parameters.lip_sync.open_y]` / `form`
- Fallback 到本地计算（从 frame.mouth → profile.mouth_shapes 查表）

### Phase 1 验证
1. 说"大家好我是AI助手"，嘴巴不应抽搐，闭口仅出现在标点/长停顿处
2. 大音量 vs 小音量说话，嘴巴张开幅度有明显差异
3. `extract_volume_envelope` 输出包络图合理（0~1 范围，跟随语音起伏）

---

## Phase 2：分段表情时间线

> 依赖 Phase 0-1

### 2.1 混合时间线消息格式

**修改** WebSocket 协议 — `live2d.control` payload 新增 `timeline` 字段：
```json
{
  "command": "lip_sync",
  "audio_start_time": 1720000000.123,
  "timeline": [
    {"timeMs": 0,    "type": "expression", "name": "neutral", "intensity": 0.0},
    {"timeMs": 0,    "type": "mouth", "mouth": "N", "params": {"ParamMouthOpenY": 0.0, "ParamMouthForm": 0.0}},
    {"timeMs": 150,  "type": "mouth", "mouth": "A", "params": {...}, "volume": 0.8},
    {"timeMs": 500,  "type": "expression", "name": "surprised", "intensity": 0.9},
    {"timeMs": 1200, "type": "expression", "name": "neutral", "intensity": 0.0},
    {"timeMs": 2500, "type": "mouth", "mouth": "N", "params": {...}}
  ]
}
```

### 2.2 后端：分段情绪检测 + 混合时间线生成

**修改** `backend/live2d/motion_controller.py`：

**新增** `build_timeline_message(text, phonemes, audio_start_time) -> dict`：
```
1. 生成口型帧（平滑过渡）
2. 文本按标点切段 → 每段独立 detect_emotion()
3. 匹配每段文本对应的 phoneme 时间区间
4. 在每个 segment 起始 time_ms 插入 expression 事件
5. 合并口型帧 + 表达式事件 → 统一 timeline，按 timeMs 排序
```

### 2.3 audio_pipeline.py：发送混合时间线

**修改** `backend/audio_pipeline.py` — TTS 循环：

**修改前**：先逐句发 lip-sync，循环结束后发一次全文本表情
**修改后**：逐句发混合 timeline（内嵌分段表情），循环结束后不再单独发送表情

### 2.4 前端：统一 timeline 调度器

**修改** `frontend/src/components/Live2DCanvas.tsx`：

**新方法** `applyTimeline(timeline: TimelineEntry[])`：
```
按 timeMs 排序 timeline
遍历：
  - type: "mouth" → setTimeout(fn, timeMs) 设置口型
  - type: "expression" → setTimeout(fn, timeMs) 调用 setExpression(name, intensity)
唯一 requestAnimationFrame 消费 setTimeout 队列
```

**移除** 前端 `sessionState → "thinking"` 独立监听（后端现在是唯一表情权威）

### Phase 2 验证
1. 发送"哇！这也太棒了吧！不过让我想想...好像有点问题。"
2. 确认表情在 surprised → neutral → thinking 之间随时间流动
3. 表情切换时间点与对应词的发声时间吻合

---

## Phase 3：空闲行为调度器

> 依赖 Phase 0，可与 Phase 1-2 并行

### 3.1 后端 IdleBehaviorScheduler

**新建** `backend/live2d/idle_scheduler.py`：

```python
class IdleBehaviorScheduler:
    """基于 profile.idle 配置驱动空闲行为"""
    def __init__(self, idle_config: IdleConfig)
    def tick(self, dt: float) -> list[IdleCommand]
    def reset(self)  # 状态切换时重置计时器
```

**行为循环**（`tick()` 中）：
1. **眨眼**：间隔随机 idle.blink_interval 秒，触发关闭 100ms 再打开
2. **视线漂移**：sin 波形驱动 eye_ball_x/y 缓慢偏移（±idle.eye_drift_range）
3. **表情循环**：idle.expression_interval 秒随机切换 expression_cycle 中的表情
4. **歪头**：概率 idle.head_tilt_chance 触发 head_angle_z 偏移 1-2s

### 3.2 WebSocket：idle 指令

后端在状态变为 `idle` 时发送 `{command: "idle_start"}`（附带 idle config），状态离开 idle 时发送 `{command: "idle_stop"}`。

### 3.3 前端：rAF 驱动的 Idle Engine

**修改** `frontend/src/components/Live2DCanvas.tsx`：

**替换** 现有 `setTimeout` 随机表情循环为 rAF idle engine：
- 从 profile.idle 读取参数
- 在已有 rAF 循环中累积 dt，调用与后端相同的调度逻辑（前端移植版）
- 接收 `live2d.control` 的 `idle_start`/`idle_stop` 命令启动/停止
- Cubism SDK 内置的 `enableEyeblink: true` + `enableBreath: true` 保留，idle engine 叠加视线漂移和歪头

### Phase 3 验证
1. 静置 15 秒，观察自然眨眼、视线漂移、偶发歪头
2. idle 行为不与 lip_sync 冲突（收到 lip_sync 时自动暂停 idle）
3. 不同 profile 的 idle 配置产生不同行为（如切换模型后眨眼频率变化）

---

## Phase 4：集成与收尾

### 4.1 统一 `handle_chat_text` 路径

**修改** `backend/main.py`：文本输入走与语音相同的 timeline 消息路径。

### 4.2 清理前端残留硬编码

- 删除 `sessionState` 独立监听（lines 389-407）
- 所有表达式/参数/路径从 profile 读取

### 4.3 配置文件更新

**修改** `backend/config.default.yaml`：
```yaml
live2d:
  model_dir: "frontend/public/live2d/有马加奈"
  mouth:
    close_gap_threshold_ms: 200
    volume_enabled: true
  expression:
    segment_enabled: true
```

### 4.4 补充依赖声明

**修改** `backend/requirements.txt`：取消注释/补全 `edge-tts`, `pydub`, `pypinyin`, `faster-whisper`, `silero-vad`, `pyyaml`

### 4.5 添加新模型验证

准备一个不同的 Live2D 模型（如免费测试模型），放到 `frontend/public/live2d/测试角色/`，编写其 `model_profile.yaml`，修改 config 指向新目录，验证行为正常。

### 4.6 测试
```bash
python -m pytest tests/ -v -k "motion or mouth or expression or idle or model_profile"
python tests/test_integration.py
```

---

## 文件变更总览

| 文件 | Phase | 变更 | 说明 |
|------|-------|------|------|
| `frontend/public/live2d/有马加奈/model_profile.yaml` | 0 | **新建** | 模型抽象描述 |
| `backend/live2d/model_profile.py` | 0 | **新建** | ModelProfile 加载 + 数据类 |
| `backend/live2d/mouth_shapes.py` | 0 | **新建** | 拼音→口型映射（去重） |
| `backend/live2d/motion_controller.py` | 0-2 | 重构 | 接受 Profile、去N帧、分段表情、音量缩放 |
| `backend/live2d/idle_scheduler.py` | 3 | **新建** | 空闲行为调度 |
| `backend/audio/prosody.py` | 1 | **新建** | WAV RMS 音量提取 |
| `backend/tts/edge_tts_adapter.py` | 0-1 | 修改 | 去重、Phoneme.char、volume 注入 |
| `backend/tts/base.py` | 1 | 修改 | Phoneme 加 char + volume 字段 |
| `backend/audio_pipeline.py` | 2 | 修改 | 混合时间线替代分离发送 |
| `backend/main.py` | 0,4 | 修改 | Profile 加载、WebSocket profile 消息、handle_chat_text 对齐 |
| `backend/config.default.yaml` | 0,4 | 修改 | model_dir 替代 model_path、新增配置项 |
| `backend/requirements.txt` | 4 | 修改 | 补全遗漏依赖 |
| `frontend/src/types/index.ts` | 0,2 | 修改 | ModelProfile 前端类型、TimelineEntry 类型 |
| `frontend/src/components/Live2DCanvas.tsx` | 0-4 | 重构 | Profile 驱动渲染、时间线调度、idle engine |
| `frontend/src/hooks/useWebSocket.ts` | 0 | 修改 | 接收 live2d.profile 消息 |
| `Dockerfile` | — | 无需改 | 已有所有依赖 |

---

## 实施顺序

```
Phase 0: 模型解耦 (2天) ←── 最高优先级，阻塞所有后续
  │
  ├── 0.1-0.3: ModelProfile + MotionController 重构
  ├── 0.4-0.6: 前后端对接 Profile
  └── 0.7: 为现有模型写 model_profile.yaml
       │
       │  验证：行为与修改前完全一致（回归）
       │
  ┌────┴──────────────────────┐
  │                           │
Phase 1: 口型+音量 (1.5天)   Phase 3: 空闲调度 (1天)
  │                           │
  └────┬──────────────────────┘
       │
Phase 2: 分段表情 (1.5天)
       │
Phase 4: 收尾 (0.5天)
```

**总估计**：6.5 个工作日。Phase 1 和 Phase 3 可以并行（互不依赖）。

---

## 切换模型操作（解耦后的目标体验）

```bash
# 1. 下载新模型放到 live2d 目录
cp -r ~/Downloads/初音未来 frontend/public/live2d/

# 2. 编写 model_profile.yaml（一次性工作）
vim frontend/public/live2d/初音未来/model_profile.yaml

# 3. 修改配置
# config.user.yaml:
#   live2d:
#     model_dir: "frontend/public/live2d/初音未来"

# 4. 重启后端
docker compose restart backend

# 完成。不需要改任何代码。
```
