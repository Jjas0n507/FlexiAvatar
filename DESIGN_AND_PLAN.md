# 智能体 (AI Agent with Live2D) — 架构设计与施工计划

> 版本: v1.0  
> 日期: 2026-06-29  
> 目标平台: Windows 10 / 11  
> 主体语言: Python 3.11+ (后端) + TypeScript 5.x (前端)

---

## 目录

1. [项目概述](#1-项目概述)
2. [整体架构设计](#2-整体架构设计)
3. [技术选型与理由](#3-技术选型与理由)
4. [核心模块详细设计](#4-核心模块详细设计)
   - [4.1 会话状态机](#41-会话状态机-session-manager)
   - [4.2 语音活动检测 VAD](#42-语音活动检测-vad)
   - [4.3 语音识别 ASR](#43-语音识别-asr)
   - [4.4 大语言模型 LLM](#44-大语言模型-llm)
   - [4.5 语音合成 TTS](#45-语音合成-tts)
   - [4.6 Live2D 动画控制](#46-live2d-动画控制)
   - [4.7 工具扩展系统](#47-工具扩展系统)
   - [4.8 WebSocket 通信协议](#48-websocket-通信协议)
   - [4.9 Electron 主进程](#49-electron-主进程)
5. [分阶段施工计划](#5-分阶段施工计划)
6. [配置系统设计](#6-配置系统设计)
7. [项目目录结构](#7-项目目录结构)
8. [风险与对策](#8-风险与对策)
9. [验收标准](#9-验收标准)

---

## 1. 项目概述

### 1.1 项目目标

构建一个运行在 Windows 桌面上的 AI 智能体应用，具备以下核心能力：

| 编号 | 能力 | 描述 |
|------|------|------|
| F1 | 语音输入 | 通过麦克风捕获语音，使用 ASR 模型转写为中文文本 |
| F2 | 语音输出 | 使用 TTS 模型将 AI 回复合成为自然语音 |
| F3 | 打断机制 | 实时检测用户是否在说话，用户可打断 AI 的发言 |
| F4 | Live2D 形象 | 显示可动 Live2D 角色，说话时同步嘴型和表情 |
| F5 | 工具扩展 | 可自由添加新的工具，LLM 能够理解并正确调用 |

### 1.2 非功能需求

- **低延迟**：语音输入到首字输出的端到端延迟 < 2 秒
- **打断响应**：从用户开始说话到 AI 停止播放的延迟 < 300ms
- **稳定性**：连续对话 30 分钟不崩溃
- **可扩展性**：添加一个新工具仅需创建一个 Python 文件 + 配置
- **资源占用**：CPU 占用 < 40%，内存占用 < 2GB

---

## 2. 整体架构设计

### 2.1 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                       Electron Application                        │
│                                                                    │
│  ┌──────────────────────────┐   ┌─────────────────────────────┐  │
│  │    Main Process (Node)   │   │    Renderer Process (Web)    │  │
│  │                          │   │                              │  │
│  │  • 窗口管理              │   │  ┌────────────────────────┐  │  │
│  │  • Python 子进程生命周期 │   │  │   Live2D Cubism SDK    │  │  │
│  │  • 系统托盘              │   │  │   (WebGL 渲染)         │  │  │
│  │  • 麦克风权限            │   │  └────────────────────────┘  │  │
│  │  • 自动更新              │   │                              │  │
│  └──────────┬───────────────┘   │  ┌────────────────────────┐  │  │
│             │                    │  │   React UI              │  │  │
│             │ IPC                │  │   • 设置面板            │  │  │
│             │                    │  │   • 工具管理            │  │  │
│             ▼                    │  │   • 对话日志            │  │  │
│  ┌──────────────────────────┐   │  └────────────────────────┘  │  │
│  │    Python Backend         │   │                              │  │
│  │    (子进程 :8765)         │◄──┤  WebSocket (ws://127.0.0.1)  │  │
│  │                           │   │                              │  │
│  │  FastAPI + uvicorn        │   │                              │  │
│  └──────────────────────────┘   └─────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 数据流图

```
                        ┌─────────────┐
                        │   麦克风     │
                        └──────┬──────┘
                               │ PCM 16kHz mono
                               ▼
                    ┌──────────────────┐
                    │   VAD (Silero)    │
                    │                   │
                    │  实时检测: 说话中  │
                    │   / 静音 / 打断   │
                    └───┬──────────┬────┘
                        │ 语音段    │ 打断信号
                        ▼           ▼
              ┌─────────────────┐  ┌──────────────┐
              │ ASR (FunASR)    │  │ State Manager │
              │ 语音 → 文本     │  │               │
              └────────┬────────┘  │ Idle/Listen/  │
                       │ 文本       │ Think/Speak/  │
                       ▼           │ Interrupted   │
              ┌─────────────────┐  └───┬──────┬────┘
              │ Conversation    │      │      │
              │ Context (历史)   │      │      │
              └────────┬────────┘      │      │
                       │ 带历史的提示词  │      │
                       ▼               │      │
              ┌─────────────────┐      │      │
              │  LLM Adapter    │      │      │
              │  (流式生成)      │      │      │
              │  + Tool Calling │      │      │
              └───┬─────────┬───┘      │      │
                  │ 文本块   │ 工具调用  │      │
                  ▼          ▼          │      │
        ┌──────────┐  ┌──────────┐     │      │
        │TTS引擎   │  │Tool Exec │     │      │
        │文本→音频 │  │执行工具   │     │      │
        │+音素时间 │  │返回结果   │     │      │
        └────┬─────┘  └────┬─────┘     │      │
             │ 音频+音素    │ 结果文本   │      │
             ▼              │           │      │
        ┌──────────┐       │           │      │
        │音频播放   │       ▼           │      │
        │+Live2D   │  ┌──────────┐     │      │
        │嘴型同步   │  │返回 LLM  │     │      │
        └──────────┘  │继续生成   │     │      │
                      └──────────┘     │      │
                                       │      │
                  ┌────────────────────┘      │
                  │ 状态变更通知               │
                  ▼                           │
        ┌──────────────────┐                  │
        │ Live2D Controller │◄─────────────────┘
        │ 表情/动作生成     │
        └──────────────────┘
```

### 2.3 进程通信模型

```
┌─────────────┐                    ┌─────────────────┐
│ Electron     │   stdio (JSON-RPC) │  Python          │
│ Main Process │◄──────────────────►│  Backend         │
│              │                    │                  │
│ 职责:        │   WebSocket        │  职责:           │
│ • 启动/重启  │◄──────────────────►│  • ASR/VAD/TTS  │
│   后端       │   (端口 8765)       │  • LLM 推理     │
│ • 系统集成   │                    │  • 工具执行      │
│ • 自动更新   │   Renderer Process  │  • 状态管理     │
└─────────────┘                    └─────────────────┘
```

两层通信：
1. **stdio JSON-RPC**：Electron 主进程 ↔ Python 后端。用途：启动健康检查、关闭指令、配置下发
2. **WebSocket**：前端渲染进程 ↔ Python 后端。用途：所有实时数据流（音频、ASR 结果、LLM 流、TTS 音频、Live2D 控制信号）

---

## 3. 技术选型与理由

### 3.1 选型总表

| 层次 | 技术 | 版本 | 选型理由 |
|------|------|------|----------|
| **桌面壳** | Electron | 31+ | 跨平台、Web 技术栈、成熟生态 |
| **前端框架** | React | 19+ | 生态最大、社区资源丰富 |
| **构建工具** | Vite | 6+ | 极快的 HMR、Electron 插件完善 |
| **状态管理** | Zustand | 5+ | 轻量、TS 友好、无模板代码 |
| **后端框架** | FastAPI | 0.115+ | 原生 async、WebSocket 支持好、自动文档 |
| **ASGI 服务器** | uvicorn | 0.34+ | FastAPI 官方推荐、高性能 |
| **VAD** | Silero VAD | latest | 准确率最高 (>95%)、轻量 (onnx)、支持 8000/16000 Hz |
| **ASR** | FunASR SenseVoiceSmall | latest | 中文识别 SOTA、流式支持、本地运行 |
| **TTS (默认)** | Edge-TTS | latest | 免费、中文自然度高、无需 GPU |
| **TTS (高级)** | GPT-SoVITS | v2 | 可训练自定义声音、音素时间戳原生支持 |
| **LLM 云端** | OpenAI / Anthropic | — | 能力最强、API 标准化 |
| **LLM 本地** | Ollama | latest | 一键部署、模型丰富、兼容 OpenAI API |
| **Live2D** | Cubism SDK for Web | 5+ | 官方 SDK、WebGL 渲染、完整的参数控制 |
| **音频处理** | PyAudio + numpy | — | Windows 兼容好、实时音频流 |
| **配置管理** | python-dotenv + YAML | — | 环境变量分离敏感信息 |

### 3.2 为什么是 Python + Electron 混合架构？

| 对比维度 | 纯 Python | 纯 Electron/TS | 混合架构 (本项目) |
|----------|-----------|----------------|-------------------|
| ASR/VAD/TTS 库 | ★★★★★ | ★★☆☆☆ | ★★★★★ (Python 侧) |
| Live2D 渲染 | ★☆☆☆☆ | ★★★★★ | ★★★★★ (Web 侧) |
| UI 开发 | ★★☆☆☆ | ★★★★★ | ★★★★★ (Web 侧) |
| ML GPU 推理 | ★★★★★ | ★★☆☆☆ | ★★★★★ (Python 侧) |
| 系统托盘/快捷键 | ★★☆☆☆ | ★★★★★ | ★★★★★ (Electron 侧) |
| 跨平台打包 | ★★★☆☆ | ★★★★★ | ★★★★☆ |

---

## 4. 核心模块详细设计

### 4.1 会话状态机 (Session Manager)

#### 4.1.1 状态定义

```
                    ┌──────────────────────────────────┐
                    │                                  │
                    ▼                                  │
              ┌──────────┐    语音检测     ┌──────────┐│
    启动 ────►│   IDLE   │───────────────►│LISTENING ││
              │  空闲    │                 │  监听中   ││
              └──────────┘                └─────┬────┘│
                    ▲                           │     │
                    │ 播放完毕                   │ 语音结束
                    │                           ▼     │
              ┌─────┴─────┐              ┌──────────┐│
              │ SPEAKING  │◄─────────────│PROCESSING││
              │  说话中    │  生成完成     │  思考中   ││
              └─────┬─────┘              └────┬─────┘│
                    │                         │      │
                    │ 用户打断                 │ 用户打断
                    ▼                         ▼      │
              ┌──────────┐              ┌──────────┐ │
              │INTERRUPTED│◄─────────────│INTERRUPTED│ │
              │  已打断   │              │  已打断   │ │
              └─────┬─────┘              └─────┬─────┘ │
                    │                         │       │
                    └─────────────────────────┘       │
                              清理完成                │
                              切换到 LISTENING ──────┘
```

#### 4.1.2 状态职责表

| 状态 | 允许的操作 | 禁止的操作 | 进入时触发 |
|------|-----------|-----------|-----------|
| **IDLE** | 启动 VAD 监听、接受配置变更 | ASR、LLM、TTS | 应用启动、一轮对话结束 |
| **LISTENING** | VAD 实时检测、语音段缓冲 | LLM、TTS | VAD 检测到语音开始 |
| **PROCESSING** | LLM 推理、工具调用 | 新对话输入 | 语音段结束、ASR 完成 |
| **SPEAKING** | TTS 播放、Live2D 动画、VAD 打断检测 | 新对话输入 | LLM 开始产出、TTS 开始合成 |
| **INTERRUPTED** | 资源清理、动画过渡 | 所有推理任务 | VAD 在 SPEAKING/PROCESSING 时检测到人声 |

#### 4.1.3 接口设计

```python
# backend/session/manager.py

from enum import Enum
from dataclasses import dataclass
from typing import Callable, Awaitable

class SessionState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"

@dataclass
class StateTransition:
    from_state: SessionState
    to_state: SessionState
    event: str
    timestamp: float

class SessionManager:
    """会话状态机"""
    
    # 合法的状态转换
    ALLOWED_TRANSITIONS: dict[SessionState, set[SessionState]] = {
        SessionState.IDLE:        {SessionState.LISTENING},
        SessionState.LISTENING:   {SessionState.IDLE, SessionState.PROCESSING},
        SessionState.PROCESSING:  {SessionState.SPEAKING, SessionState.INTERRUPTED},
        SessionState.SPEAKING:    {SessionState.IDLE, SessionState.INTERRUPTED},
        SessionState.INTERRUPTED: {SessionState.LISTENING},
    }
    
    def __init__(self):
        self._state: SessionState = SessionState.IDLE
        self._listeners: list[Callable[[StateTransition], Awaitable[None]]] = []
        self._transition_history: list[StateTransition] = []
        # 当前对话的取消令牌
        self._current_cancel_token: asyncio.Event | None = None
    
    @property
    def state(self) -> SessionState: ...
    
    async def transition(self, event: str) -> bool:
        """尝试状态转换，返回是否成功"""
        ...
    
    def on_transition(self, callback) -> None:
        """注册状态转换回调"""
        ...
    
    def get_cancel_token(self) -> asyncio.Event:
        """获取当前取消令牌，用于打断时取消正在进行的任务"""
        ...
    
    async def interrupt(self) -> None:
        """外部打断入口"""
        ...
```

### 4.2 语音活动检测 (VAD)

#### 4.2.1 工作模式

VAD 模块运行一个独立的音频采集循环，持续从麦克风读取 PCM 数据。根据当前状态机状态，VAD 行为不同：

- **IDLE 状态**：低频率检测（每 100ms 检测一次），节省 CPU
- **LISTENING 状态**：高频率检测（每 30ms 检测一次），精确切分语音段
- **SPEAKING 状态**：高频率检测（每 30ms 检测一次），随时准备触发打断
- **PROCESSING 状态**：监听中，如果用户说话则触发打断

#### 4.2.2 打断检测逻辑

```python
# backend/vad/silero_adapter.py 核心逻辑

class SileroVAD:
    def __init__(self, config: VADConfig):
        self.model = load_silero_vad(onnx=True)
        self.threshold: float = config.threshold           # 默认 0.5
        self.speech_start_frames: int = config.start_frames # 连续 N 帧有声 → 认为开始说话
        self.silence_frames: int = config.silence_frames    # 连续 N 帧静音 → 认为说话结束
        self.interrupt_frames: int = config.interrupt_frames # 打断阈值（更低，更快响应）
    
    def process_frame(self, audio_frame: np.ndarray) -> VADEvent:
        """
        处理一帧音频，返回 VAD 事件
        
        audio_frame: 30ms 的 16kHz 单声道 PCM 数据 (480 samples)
        返回: VADEvent.SPEECH_START / VADEvent.SPEECH_CONTINUE / 
               VADEvent.SPEECH_END / VADEvent.SILENCE
        """
        prob = self.model(audio_frame, 16000).item()
        ...
```

#### 4.2.3 打断时序

```
时间轴 →
用户:  [═══════正在说话═══════════]
AI:        [══════TTS 播放中══════╣×]  ← 被打断
VAD:                    [检测到人声]
状态: SPEAKING ────────────────→ INTERRUPTED → LISTENING
延迟:                          ← 打断检测延迟 < 200ms →
        
打断发生后执行:
1. VAD 发送 interrupt 信号
2. SessionManager.transition("user_interrupt")
3. 设置 cancel_token，取消 TTS 音频播放
4. 如果可以，取消 LLM 请求 (asyncio.Task.cancel)
5. 清空 TTS 播放队列
6. 发送 Live2D 控制信号 "interrupted" 表情
7. 短暂冷却 300ms
8. 切换到 LISTENING，开始新的语音收集
```

### 4.3 语音识别 (ASR)

#### 4.3.1 非流式 vs 流式

为降低延迟，优先实现**非流式（整段识别）**，后续升级到流式。

- **非流式**：等用户说完一整句话 → 整段送给 ASR → 返回完整文本。简单可靠，延迟增加约语音段长度
- **流式**：边说边识别 → 实时返回中间结果。延迟更低但实现复杂

#### 4.3.2 FunASR 适配器设计

```python
# backend/asr/funasr_adapter.py

class FunASRAdapter(BaseASR):
    def __init__(self, config: ASRConfig):
        from funasr import AutoModel
        self.model = AutoModel(
            model=config.model,          # "iic/SenseVoiceSmall"
            vad_model="fsmn-vad",        # 可选的内部 VAD
            punc_model="ct-punc",        # 标点恢复
            device="cpu",                # Windows 上用 CPU 最稳定
            disable_update=True,         # 禁止自动更新
        )
    
    async def transcribe(self, audio: np.ndarray) -> ASRResult:
        """
        识别一段语音
        
        audio: 16kHz 单声道 PCM numpy array
        返回: ASRResult(text="识别文本", confidence=0.95, is_final=True)
        """
        result = self.model.generate(
            input=audio,
            language="zh",
            use_itn=True,      # 逆文本归一化
        )
        text = result[0]["text"]
        return ASRResult(text=text, confidence=0.95, is_final=True)
```

#### 4.3.3 备选方案

| 方案 | 优点 | 缺点 |
|------|------|------|
| **FunASR SenseVoiceSmall** (首选) | 中文 SOTA、轻量、社区活跃 | Windows pip 安装可能需解决依赖 |
| **Sherpa-ONNX** | 真正跨平台、exe 免安装 | 模型需单独下载 |
| **Whisper (faster-whisper)** | 多语言、社区最大 | 中文不如 SenseVoice、需要 CTranslate2 |

### 4.4 大语言模型 (LLM)

#### 4.4.1 适配器抽象

```python
# backend/llm/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Literal

@dataclass
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None
    tool_calls: list[dict] | None = None

@dataclass 
class ToolDefinition:
    """LLM function-calling 用的工具定义"""
    name: str
    description: str
    parameters: dict  # JSON Schema

@dataclass
class LLMChunk:
    """流式输出的单个块"""
    type: Literal["text", "tool_call"]
    content: str           # text 类型时是增量文本
    tool_call: dict | None # tool_call 类型时的调用信息

class BaseLLM(ABC):
    """LLM 适配器抽象基类"""
    
    @abstractmethod
    async def stream_chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[LLMChunk]:
        """
        流式对话
        
        参数:
          messages: 对话历史
          tools: 可用工具列表（自动转换为 function-calling schema）
          cancel_event: 外部取消信号（打断用）
        
        产出:
          LLMChunk 流，直到完整响应结束
        """
        ...
    
    @abstractmethod
    async def chat(
        self, messages: list[Message], tools: list[ToolDefinition] | None = None
    ) -> Message:
        """
        非流式对话（用于需要完整结果的场景）
        """
        ...
```

#### 4.4.2 工具调用循环

```python
# backend/llm/base.py (继续)

async def chat_with_tools(
    self,
    messages: list[Message],
    tools: list[ToolDefinition],
    tool_registry: "ToolRegistry",
    cancel_event: asyncio.Event | None = None,
    max_tool_rounds: int = 5,
) -> AsyncIterator[LLMChunk]:
    """
    带自动工具调用循环的流式对话
    
    流程:
    1. 发送 messages + tools 给 LLM
    2. 如果 LLM 返回 tool_call:
       a. 执行工具
       b. 将工具结果追加到 messages
       c. 回到步骤 1（最多 max_tool_rounds 轮）
    3. 如果 LLM 返回 text:
       a. 流式产出文本
    """
```

#### 4.4.3 具体适配器实现要点

**OpenAI 适配器：**
```python
class OpenAIAdapter(BaseLLM):
    async def stream_chat(self, messages, tools=None, cancel_event=None):
        client = openai.AsyncOpenAI(api_key=..., base_url=...)
        stream = await client.chat.completions.create(
            model=self.model,
            messages=[m.__dict__ for m in messages],
            tools=self._format_tools(tools) if tools else None,
            stream=True,
        )
        async for chunk in stream:
            if cancel_event and cancel_event.is_set():
                await stream.close()
                break
            yield self._parse_chunk(chunk)
```

**Ollama 适配器：**
```python
class OllamaAdapter(BaseLLM):
    async def stream_chat(self, messages, tools=None, cancel_event=None):
        import httpx
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST", f"{self.base_url}/api/chat",
                json={"model": self.model, "messages": ..., "tools": ..., "stream": True},
                timeout=httpx.Timeout(None),  # 流式不超时
            ) as response:
                async for line in response.aiter_lines():
                    if cancel_event and cancel_event.is_set():
                        break
                    yield self._parse_line(line)
```

### 4.5 语音合成 (TTS)

#### 4.5.1 需求分析

TTS 模块除了生成音频，**还必须提供音素时间戳**，这是驱动 Live2D 嘴型同步的关键数据。

```
输入文本: "你好，我是小助手"
  ↓
TTS 合成
  ↓
输出:
  audio: [PCM/WAV 音频数据]
  phonemes: [
    {phoneme: "n", start: 0.00, end: 0.08},
    {phoneme: "i", start: 0.08, end: 0.22},
    {phoneme: "h", start: 0.22, end: 0.30},
    {phoneme: "ao", start: 0.30, end: 0.52},
    {phoneme: "<sil>", start: 0.52, end: 0.60},  # 停顿
    ...
  ]
```

#### 4.5.2 Edge-TTS 适配器（默认方案）

Edge-TTS 原生支持返回**字词边界 (word boundaries)**，可以用作音素时间戳的近似。

```python
# backend/tts/edge_tts_adapter.py

import edge_tts
import asyncio

class EdgeTTSAdapter(BaseTTS):
    async def synthesize(self, text: str) -> TTSResult:
        communicate = edge_tts.Communicate(
            text=text,
            voice=self.voice,  # "zh-CN-XiaoxiaoNeural"
            rate=self._speed_to_rate(),  # "+0%" ~ "+100%"
        )
        
        audio_chunks = []
        word_boundaries = []
        
        # 并行收集音频和边界信息
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                word_boundaries.append({
                    "text": chunk["text"],           # 字本身
                    "offset": chunk["offset"],       # 起始时间 (100ns 单位)
                    "duration": chunk["duration"],   # 持续时长 (100ns 单位)
                })
        
        audio_bytes = b"".join(audio_chunks)
        phonemes = self._word_boundaries_to_phonemes(word_boundaries)
        
        return TTSResult(audio_bytes=audio_bytes, phonemes=phonemes)
    
    def _word_boundaries_to_phonemes(self, boundaries) -> list[Phoneme]:
        """
        Edge-TTS 返回字级边界，需映射为 Live2D 口型
        
        中文拼音到五口型的映射表:
        a, ai, an, ang, ao       → A (开口)
        e, ei, en, eng, er, o, ou, ong → E (半开)
        i, ia, ian, iang, iao, ie, in, ing, io, iu → I (咧嘴)
        u, ua, uai, uan, uang, ui, uo, un → U (嘟嘴)
        ü, üe, üan, ün           → U (嘟嘴) [或映射到组合]
        辅音 → 根据上下文归类
        """
        ...
```

#### 4.5.3 流式 TTS 策略

为支持“边说边生成”，需要将 LLM 流式输出的文本按标点切分，逐句送 TTS：

```python
class StreamingTTSOrchestrator:
    """
    协调 LLM 流式输出和 TTS 合成
    
    策略:
    1. 从 LLM 流中累积文本
    2. 遇到标点符号 (。！？；\n) 时，将已累积的句子送入 TTS
    3. TTS 在后台合成，合成完成后加入播放队列
    4. 音频播放器按顺序播放队列中的音频
    """
    
    def __init__(self, tts: BaseTTS, live2d_ctrl: Live2DController):
        self.tts = tts
        self.live2d = live2d_ctrl
        self.play_queue: asyncio.Queue[PhonemeSyncAudio] = asyncio.Queue()
    
    async def feed_text_chunk(self, text: str, cancel_event: asyncio.Event):
        """接收 LLM 流式文本块，自动切句并合成"""
        self.accumulator += text
        while self._has_complete_sentence():
            sentence = self._pop_sentence()
            result = await self.tts.synthesize(sentence)
            await self.play_queue.put(PhonemeSyncAudio(
                audio=result.audio_bytes,
                phonemes=result.phonemes,
            ))
    
    async def play_loop(self, cancel_event: asyncio.Event):
        """播放循环：从队列取音频，播放并驱动 Live2D 嘴型同步"""
        while not cancel_event.is_set():
            try:
                item = await asyncio.wait_for(
                    self.play_queue.get(), timeout=0.1
                )
                await self._play_with_lip_sync(item, cancel_event)
            except asyncio.TimeoutError:
                continue
```

### 4.6 Live2D 动画控制

#### 4.6.1 架构分层

```
┌────────────────────────────────────────────┐
│         Live2DController (Python)           │
│  • 接收音素时间线 → 生成口型参数序列       │
│  • 接收状态变化 → 生成表情/动作指令        │
│  • 通过 WebSocket 发送控制指令到前端        │
└──────────────────┬─────────────────────────┘
                   │ WebSocket
                   ▼
┌────────────────────────────────────────────┐
│      Live2D Renderer (TypeScript/Web)       │
│  • Live2D Cubism SDK for Web               │
│  • 接收控制指令 → 应用到模型参数           │
│  • WebGL 实际渲染                          │
│  • 空闲动画 (呼吸、眨眼、微动)             │
└────────────────────────────────────────────┘
```

#### 4.6.2 控制指令协议

```typescript
// frontend/src/types/index.ts

/** 口型参数 */
interface LipSyncFrame {
  phoneme: "A" | "I" | "U" | "E" | "O" | "N";  // N = 闭嘴
  value: number;    // 0.0 ~ 1.0 参数值
  timeMs: number;   // 在此时间点达到该值
}

/** 表情指令 */
interface ExpressionCommand {
  name: string;       // 表情名称，对应 Live2D 模型中的 expression
  intensity: number;  // 0.0 ~ 1.0
  fadeInMs: number;   // 淡入时长
  durationMs: number; // 持续时长，0 = 保持
  fadeOutMs: number;  // 淡出时长
}

/** 身体动作指令 */
interface MotionCommand {
  group: string;    // 动作组名称，对应 Live2D 模型中的 motion group
  index: number;    // 动作编号
  priority: number; // 优先级，高优先级的动作会打断低优先级的
}

/** 复合控制消息 */
interface Live2DControlMessage {
  type: "live2d.control";
  payload: {
    lipSync?: {
      frames: LipSyncFrame[];
      startTime: number;  // 音频开始播放时的 performance.now()
    };
    expression?: ExpressionCommand;
    motion?: MotionCommand;
    idle?: {
      enabled: boolean;        // 是否启用空闲动画
      breathingRate: number;   // 呼吸频率
      blinkInterval: number;   // 眨眼间隔 (ms)
    };
    reset?: boolean;           // 重置所有参数到默认值
  };
}
```

#### 4.6.3 口型到 Live2D 参数的映射

Live2D Cubism 标准口型参数：

| Live2D 参数 ID | 含义 | 对应口型 |
|----------------|------|----------|
| `ParamMouthOpenY` | 嘴巴纵向张开 | 所有口型的基础 |
| `ParamMouthForm` | 嘴巴横向宽度 | I (咧嘴宽), U (嘟嘴窄) |
| `ParamMouthA` | A 口型贡献 | A (啊) |
| `ParamMouthI` | I 口型贡献 | I (衣) |
| `ParamMouthU` | U 口型贡献 | U (乌) |
| `ParamMouthE` | E 口型贡献 | E (诶) |
| `ParamMouthO` | O 口型贡献 | O (哦) |

```python
# backend/live2d/motion_controller.py

PHONEME_TO_CUBISM = {
    "A": {"ParamMouthA": 1.0, "ParamMouthOpenY": 0.8},
    "I": {"ParamMouthI": 1.0, "ParamMouthForm": 0.8, "ParamMouthOpenY": 0.3},
    "U": {"ParamMouthU": 1.0, "ParamMouthForm": -0.5, "ParamMouthOpenY": 0.3},
    "E": {"ParamMouthE": 1.0, "ParamMouthOpenY": 0.5},
    "O": {"ParamMouthO": 1.0, "ParamMouthOpenY": 0.6},
    "N": {"ParamMouthOpenY": 0.0},  # 闭嘴 (鼻音等)
}
```

#### 4.6.4 TypeScript 端 Live2D 渲染器

```typescript
// frontend/src/components/Live2DCanvas.tsx (概要)

import * as PIXI from "pixi.js";
import { Live2DModel } from "pixi-live2d-display"; // 社区封装的 PixiJS Live2D

// 或者直接使用 Cubism SDK for Web 原生 API (更稳定)

class Live2DManager {
  private model: Live2DModel;
  private lipSyncFrames: LipSyncFrame[] = [];
  private audioStartTime: number = 0;
  private currentExpression: string = "neutral";
  
  async loadModel(modelPath: string): Promise<void> {
    // 加载 .model3.json
    this.model = await Live2DModel.from(modelPath);
    
    // 注册空闲动画
    app.ticker.add((delta) => this.onTick(delta));
  }
  
  private onTick(delta: number): void {
    const now = performance.now();
    
    // 1. 处理口型同步
    if (this.lipSyncFrames.length > 0) {
      const elapsed = now - this.audioStartTime;
      this.applyLipSyncAt(elapsed);
    }
    
    // 2. 自动眨眼
    this.updateAutoBlink(now);
    
    // 3. 空闲呼吸
    if (this.idleEnabled) {
      this.applyBreathing(now);
    }
    
    // 4. 更新模型渲染
    this.model.update(delta);
  }
  
  applyLipSyncAt(elapsedMs: number): void {
    // 找到当前时间点对应的口型帧
    // 在帧之间做线性插值
    // 设置 Live2D 参数
  }
  
  setExpression(cmd: ExpressionCommand): void { ... }
  playMotion(cmd: MotionCommand): void { ... }
  onInterrupt(): void {
    // 播放"受惊"表情 + 停止当前动作
    this.setExpression({ name: "surprised", intensity: 0.8, ... });
    this.model.internalModel.motionManager.stopAllMotions();
  }
}
```

### 4.7 工具扩展系统

#### 4.7.1 设计目标

1. **声明式**：写一个工具 = 一个 Pydantic Model (参数) + 一个函数 (执行逻辑)，其余自动生成
2. **自描述**：从代码中自动提取 name、description、参数 schema 供 LLM 理解
3. **热加载**：放入 `user_tools/` 目录的 `.py` 文件会在启动时自动发现并注册
4. **类型安全**：Pydantic 保证参数校验，运行时错误不会传播到 LLM

#### 4.7.2 核心类设计

```python
# backend/tools/base.py

from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Any

class Tool(ABC):
    """工具抽象基类"""
    
    # === 子类必须定义 ===
    name: str                    # 工具唯一名称，如 "get_weather"
    description: str             # 自然语言描述，告诉 LLM 这个工具做什么
    
    @abstractmethod
    def parameters_model(self) -> type[BaseModel]:
        """返回 Pydantic 参数模型类"""
        ...
    
    @abstractmethod
    async def execute(self, **params) -> str:
        """实际执行逻辑，返回文本结果"""
        ...
    
    # === 自动生成的 ===
    
    @property
    def parameters_schema(self) -> dict:
        """从 Pydantic 模型自动生成 JSON Schema (OpenAI function-calling 格式)"""
        model = self.parameters_model()
        schema = model.model_json_schema()
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": schema.get("properties", {}),
                    "required": schema.get("required", []),
                },
            },
        }
    
    @property
    def is_async(self) -> bool:
        """自动检测 execute 是否是 async 方法"""
        import inspect
        return inspect.iscoroutinefunction(self.execute)
```

#### 4.7.3 工具注册中心

```python
# backend/tools/registry.py

import importlib
import pkgutil
from pathlib import Path

class ToolRegistry:
    """全局工具注册中心（单例）"""
    
    _instance: "ToolRegistry | None" = None
    
    def __new__(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, "_tools"):
            self._tools: dict[str, Tool] = {}
            self._loaded = False
    
    def register(self, tool: Tool) -> None:
        """注册一个工具"""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool
    
    def get(self, name: str) -> Tool:
        """获取指定工具"""
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' not found")
        return self._tools[name]
    
    def get_all_schemas(self) -> list[dict]:
        """获取所有工具的 LLM function-calling schema"""
        return [tool.parameters_schema for tool in self._tools.values()]
    
    def get_all_for_llm(self) -> list[dict]:
        """获取所有工具的 LLM 格式定义"""
        return [{
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters_schema["function"]["parameters"],
        } for tool in self._tools.values()]
    
    def discover_builtin_tools(self) -> None:
        """自动发现并注册内置工具"""
        import backend.tools.builtin as builtin_pkg
        for _, name, _ in pkgutil.iter_modules(builtin_pkg.__path__):
            module = importlib.import_module(f"backend.tools.builtin.{name}")
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and issubclass(attr, Tool) and attr is not Tool:
                    self.register(attr())
    
    def discover_user_tools(self, user_dir: str | Path) -> None:
        """自动发现并注册用户自定义工具"""
        user_dir = Path(user_dir)
        if not user_dir.exists():
            return
        for py_file in user_dir.glob("*.py"):
            spec = importlib.util.spec_from_file_location(
                f"user_tool_{py_file.stem}", py_file
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and issubclass(attr, Tool) and attr is not Tool:
                    self.register(attr())
    
    async def execute_tool(self, name: str, **params) -> str:
        """执行指定工具"""
        tool = self.get(name)
        try:
            # Pydantic 参数校验
            param_model = tool.parameters_model()
            validated = param_model(**params)
            
            # 执行
            if tool.is_async:
                result = await tool.execute(**validated.model_dump())
            else:
                result = tool.execute(**validated.model_dump())
            
            return str(result)
        except Exception as e:
            return f"工具执行失败: {e}"
```

#### 4.7.4 内置工具示例

```python
# backend/tools/builtin/time_tool.py

from datetime import datetime
from pydantic import BaseModel, Field
from backend.tools.base import Tool

class TimeParams(BaseModel):
    timezone: str = Field(
        default="Asia/Shanghai",
        description="时区，例如 Asia/Shanghai, America/New_York, Europe/London"
    )

class TimeTool(Tool):
    name = "get_current_time"
    description = (
        "获取当前的日期和时间。当用户询问现在几点、今天几号、当前时间等问题时使用此工具。"
        "支持指定不同时区。"
    )
    
    def parameters_model(self):
        return TimeParams
    
    async def execute(self, timezone: str = "Asia/Shanghai") -> str:
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(timezone)
        except Exception:
            tz = None  # fallback to local
        now = datetime.now(tz)
        weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        weekday = weekday_names[now.weekday()]
        return f"现在是{now.year}年{now.month}月{now.day}日 {weekday} {now.hour:02d}:{now.minute:02d}:{now.second:02d}"
```

#### 4.7.5 用户自定义工具示例

用户只需在 `user_tools/` 目录下创建一个 Python 文件：

```python
# backend/tools/user_tools/my_custom_tool.py

from pydantic import BaseModel, Field
from backend.tools.base import Tool

class ReminderParams(BaseModel):
    message: str = Field(description="提醒的内容")
    minutes: int = Field(description="多少分钟后提醒", ge=1, le=1440)

class ReminderTool(Tool):
    name = "set_reminder"
    description = "设置一个定时提醒。用户说'X分钟后提醒我Y'时使用此工具。"
    
    def parameters_model(self):
        return ReminderParams
    
    async def execute(self, message: str, minutes: int) -> str:
        # 实际实现：调用系统通知 API 等
        import asyncio
        asyncio.create_task(self._notify_after(message, minutes))
        return f"已设置{minutes}分钟后的提醒：{message}"
    
    async def _notify_after(self, message: str, minutes: int):
        await asyncio.sleep(minutes * 60)
        # 发送通知...
```

### 4.8 WebSocket 通信协议

#### 4.8.1 连接管理

```
Python 后端: ws://127.0.0.1:8765/ws
                          │
         ┌────────────────┼────────────────┐
         ▼                ▼                ▼
    audio 通道       control 通道       event 通道
    (二进制为主)      (JSON 指令)       (状态通知)
```

实际上使用**单一 WebSocket 连接**，通过消息 type 字段区分——简化实现，避免多连接同步问题。

#### 4.8.2 消息格式

所有消息使用 JSON 格式，二进制数据使用 Base64 编码（小数据时）或通过消息头指定后续二进制帧。

```typescript
// 基础消息结构
interface WSMessage {
  type: string;
  id: string;          // 消息唯一 ID (UUIDv4)
  timestamp: number;   // 发送时的 Unix 毫秒时间戳
  payload: any;
}

// === 前端 → 后端 ===

// 1. 音频数据 (二进制，通过 ArrayBuffer 发送)
//    发送方式: 先发 JSON 头，再发二进制帧
//    JSON 头: {"type": "audio.chunk", "id": "xxx", "timestamp": 123, "payload": {"format": "pcm", "sampleRate": 16000, "channels": 1, "frameCount": 480}}
//    二进制帧: Int16Array

// 2. 打断
interface InterruptMessage {
  type: "user.interrupt";
  id: string;
  timestamp: number;
  payload: {};
}

// 3. 更新配置
interface ConfigUpdateMessage {
  type: "config.update";
  id: string;
  timestamp: number;
  payload: Partial<AppConfig>;
}

// 4. 文字聊天 (备选，用于调试和文字输入)
interface TextChatMessage {
  type: "chat.text";
  id: string;
  timestamp: number;
  payload: { text: string };
}

// === 后端 → 前端 ===

// 1. 状态变化
interface StateChangeMessage {
  type: "state.change";
  id: string;
  timestamp: number;
  payload: {
    state: "idle" | "listening" | "processing" | "speaking" | "interrupted";
    previous: string;
    reason: string;  // 转换原因
  };
}

// 2. ASR 结果
interface ASRResultMessage {
  type: "asr.result";
  id: string;
  timestamp: number;
  payload: {
    text: string;
    isFinal: boolean;   // 是否是最终结果
    confidence: number;
  };
}

// 3. LLM 流式输出
interface LLMStreamMessage {
  type: "llm.stream";
  id: string;
  timestamp: number;
  payload: {
    text: string;         // 增量文本
    isFirstChunk: boolean;
    isLastChunk: boolean;
  };
}

// 4. TTS 音频 (二进制)
//    JSON 头: {"type": "tts.audio", ..., "payload": {"sentence": "你好", "phonemes": [...]}}
//    二进制帧: WAV/MP3 数据

// 5. Live2D 控制
interface Live2DControlMessage {
  type: "live2d.control";
  id: string;
  timestamp: number;
  payload: {
    command: "lipSync" | "expression" | "motion" | "idle" | "reset" | "interrupt";
    params: any;  // 见 4.6.2 节
  };
}

// 6. 工具调用进度
interface ToolProgressMessage {
  type: "tool.progress";
  id: string;
  timestamp: number;
  payload: {
    name: string;       // 工具名称
    status: "calling" | "running" | "done" | "error";
    params?: any;
    result?: string;
    error?: string;
  };
}

// 7. 错误
interface ErrorMessage {
  type: "error";
  id: string;
  timestamp: number;
  payload: {
    code: string;       // 错误码
    message: string;    // 人类可读的信息
    recoverable: boolean; // 是否可恢复
  };
}
```

#### 4.8.3 心跳机制

```
每 10 秒:
  后端 → 前端: { "type": "ping", ... }
  前端 → 后端: { "type": "pong", ... }

超过 30 秒未收到 pong → 后端视为连接断开 → 清理资源 → 回到 IDLE
```

---

### 4.9 Electron 主进程

#### 4.9.1 职责清单

```typescript
// electron/main.ts

/**
 * Electron 主进程职责:
 * 1. 创建 BrowserWindow 并加载 React 前端
 * 2. 启动 Python 后端子进程 (spawn)
 * 3. 健康检查：轮询后端 /health，挂了自动重启
 * 4. 管理系统托盘图标
 * 5. 全局快捷键 (可选)
 * 6. 处理应用退出：先关 Python，再关窗口
 */
```

#### 4.9.2 Python 子进程管理

```typescript
// electron/python-bridge.ts

import { spawn, ChildProcess } from "child_process";
import path from "path";

class PythonBridge {
  private process: ChildProcess | null = null;
  private restartCount = 0;
  private maxRestarts = 5;
  
  async start(): Promise<void> {
    const pythonPath = this.findPython(); // 优先使用虚拟环境中的 python
    const backendDir = path.join(__dirname, "..", "..", "backend");
    
    this.process = spawn(pythonPath, ["-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8765"], {
      cwd: backendDir,
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
      stdio: ["pipe", "pipe", "pipe"],
    });
    
    // 监控 stdout/stderr
    this.process.stdout?.on("data", (data) => {
      console.log(`[Python] ${data}`);
      if (data.toString().includes("Uvicorn running")) {
        this.onReady();
      }
    });
    
    this.process.stderr?.on("data", (data) => {
      console.error(`[Python Error] ${data}`);
    });
    
    this.process.on("exit", (code) => {
      console.log(`Python exited with code ${code}`);
      if (code !== 0 && this.restartCount < this.maxRestarts) {
        this.restartCount++;
        setTimeout(() => this.start(), 3000); // 3 秒后重启
      }
    });
  }
  
  async stop(): Promise<void> {
    if (this.process) {
      // 发送 SIGTERM，给后端 5 秒清理时间
      this.process.kill("SIGTERM");
      await new Promise(resolve => setTimeout(resolve, 5000));
      if (this.process.exitCode === null) {
        this.process.kill("SIGKILL");
      }
    }
  }
  
  async healthCheck(): Promise<boolean> {
    try {
      const res = await fetch("http://127.0.0.1:8765/health");
      return res.ok;
    } catch {
      return false;
    }
  }
}
```

#### 4.9.3 麦克风权限处理

```typescript
// 在 Electron 主进程中
const { session } = require("electron");

// 自动授予麦克风权限
session.defaultSession.setPermissionRequestHandler(
  (webContents, permission, callback) => {
    if (permission === "media") {
      callback(true); // 自动允许麦克风
    } else {
      callback(false);
    }
  }
);
```

---

## 5. 分阶段施工计划

### 阶段总览

```
阶段 1        阶段 2         阶段 3        阶段 4        阶段 5        阶段 6
[基础骨架] → [语音链路] → [LLM对接] → [Live2D] → [工具系统] → [优化完善]
   3-5天        4-6天         2-3天        3-4天         2-3天        2-3天

验收:         验收:          验收:         验收:         验收:         验收:
窗口+WS+      ASR→TTS+      LLM对话+      Live2D嘴型+  工具自动+    全功能+
状态机        打断          流式输出       表情动作      调用          稳定性
```

---

### 阶段 1: 基础骨架 (3-5 天)

#### 目标
Electron 窗口能打开，Python 后端能启动，前后端 WebSocket 连通，状态机工作正常。

#### 施工任务清单

**任务 1.1: 项目初始化**
- [ ] 创建项目根目录结构
- [ ] 初始化 Python 后端
  ```bash
  cd backend
  python -m venv venv
  pip install fastapi uvicorn websockets pyyaml python-dotenv
  ```
- [ ] 初始化 Electron + React 前端
  ```bash
  cd frontend
  npm create vite@latest . -- --template react-ts
  npm install electron electron-builder
  npm install zustand
  ```
- [ ] 配置 TypeScript、ESLint、Prettier

**任务 1.2: Python 后端骨架**
- [ ] 创建 `backend/main.py`: FastAPI 应用入口 + `/health` 端点
- [ ] 创建 `backend/config.py`: 配置加载器 (YAML + 环境变量)
- [ ] 创建 `backend/session/manager.py`: 状态机实现
- [ ] 创建 WebSocket 端点 `/ws`
- [ ] 创建 `backend/requirements.txt`

**任务 1.3: Electron + React 前端骨架**
- [ ] 创建 `electron/main.ts`: 创建窗口 + 启动 Python 子进程
- [ ] 创建 `electron/python-bridge.ts`: Python 进程管理
- [ ] 创建 `electron/preload.ts`: 安全暴露 API 给渲染进程
- [ ] 创建 `frontend/src/App.tsx`: 基础 UI
  - 状态指示器 (显示当前状态)
  - 连接状态
  - 调试控制台
- [ ] 创建 `frontend/src/hooks/useWebSocket.ts`: WebSocket hook
- [ ] 创建 `frontend/src/stores/agent-store.ts`: Zustand store

**任务 1.4: 通信协议验证**
- [ ] 实现消息 ping/pong
- [ ] 实现状态变更通知
- [ ] 前端发送文字消息 → 后端回显 (echo)
- [ ] 验证 Python 子进程健康检查和自动重启

#### 阶段 1 验收标准
- ✅ 执行 `npm run dev` 能打开 Electron 窗口
- ✅ 控制台显示 Python 后端启动成功
- ✅ 前端显示 WebSocket 已连接
- ✅ 状态机可以从 IDLE → LISTENING → PROCESSING → SPEAKING → IDLE 走通
- ✅ 杀死 Python 进程后 3 秒内自动重启
- ✅ 关闭 Electron 窗口后 Python 进程也被终止

#### 阶段 1 产出文件
```
backend/
  main.py                # FastAPI 入口
  config.py              # 配置管理
  session/
    __init__.py
    manager.py           # 会话状态机
  requirements.txt

electron/
  main.ts                # Electron 主进程
  preload.ts             # 预加载脚本
  python-bridge.ts       # Python 子进程管理

frontend/src/
  App.tsx                # 主界面
  App.css
  hooks/
    useWebSocket.ts      # WebSocket 连接管理
  stores/
    agent-store.ts       # 全局状态
  services/
    ws-client.ts         # WS 客户端封装
  types/
    index.ts             # 类型定义

package.json             # 前端依赖
tsconfig.json
vite.config.ts
```

---

### 阶段 2: 语音链路 (4-6 天)

#### 目标
能够对着麦克风说话 → ASR 识别为文字 → 文字通过 TTS 转语音播放出来。支持打断。

#### 施工任务清单

**任务 2.1: 音频采集**
- [ ] 前端：编写 `useAudioCapture` hook (使用 Web Audio API / MediaStream)
- [ ] 前端：PCM 格式转换 (16kHz, 16bit, mono)
- [ ] 前端：音频数据分帧 (每 30ms/480 samples 一帧)，通过 WebSocket 发送
- [ ] 后端：接收音频帧，存入 ring buffer

**任务 2.2: VAD 模块**
- [ ] 安装 Silero VAD
- [ ] 创建 `backend/vad/base.py`: VAD 抽象接口
- [ ] 创建 `backend/vad/silero_adapter.py`: Silero VAD 实现
  - [ ] 实现语音开始检测
  - [ ] 实现语音结束检测（静音超时）
  - [ ] 实现打断检测（IDLE/SPEAKING 状态下的检测）
- [ ] 单元测试：喂入一段 wav → 验证 VAD 开始/结束时间准确

**任务 2.3: ASR 模块**
- [ ] 安装 FunASR + SenseVoiceSmall 模型
- [ ] 创建 `backend/asr/base.py`: ASR 抽象接口
- [ ] 创建 `backend/asr/funasr_adapter.py`: FunASR 实现
- [ ] 语音段完整收集后送 ASR → 返回文本
- [ ] 集成测试：录音 → VAD 切分 → ASR 识别 → 输出文本

**任务 2.4: TTS 模块 + 打断**
- [ ] 安装 Edge-TTS
- [ ] 创建 `backend/tts/base.py`: TTS 抽象接口
- [ ] 创建 `backend/tts/edge_tts_adapter.py`: Edge-TTS 实现
- [ ] 实现音频播放流程：接收文本 → 合成 → 通过 WebSocket 发送音频到前端 → 前端播放
- [ ] 实现打断流程：
  - [ ] SPEAKING 状态下，VAD 检测到人声 → interrupt
  - [ ] 停止当前 TTS 合成
  - [ ] 停止音频播放
  - [ ] 切换到 LISTENING
- [ ] 前后端音频同步方案（播放时间戳、缓冲控制）

**任务 2.5: 端到端联通**
- [ ] 创建 `backend/main.py` 中的语音对话流水线编排
- [ ] 调试完整链路：说话 → ASR → (echo回文) → TTS → 播放
- [ ] 重复对话测试（5轮+）
- [ ] 打断测试：AI 播放时说话 → AI 静音 → 开始新对话

#### 阶段 2 验收标准
- ✅ 对着麦克风说"你好" → 1 秒内识别出文字 → 播放"你好"语音
- ✅ 说话停顿 800ms 后自动认为说完，开始处理
- ✅ AI 播放语音时，用户开始说话 → AI 在 300ms 内停止播放
- ✅ 打断后可以继续正常对话，状态不混乱
- ✅ 环境噪音不会被误识别为语音

#### 阶段 2 产出文件
```
backend/
  vad/
    __init__.py
    base.py                 # VAD 抽象接口
    silero_adapter.py       # Silero VAD 实现
  asr/
    __init__.py
    base.py                 # ASR 抽象接口
    funasr_adapter.py       # FunASR 实现
  tts/
    __init__.py
    base.py                 # TTS 抽象接口
    edge_tts_adapter.py     # Edge-TTS 实现

frontend/src/
  hooks/
    useAudioCapture.ts      # 麦克风捕获 hook
    useAudioPlayback.ts     # 音频播放 hook
```

---

### 阶段 3: LLM 对接 (2-3 天)

#### 目标
LLM 能够接收用户语音转的文本，流式生成回复，TTS 按句子合成并播放。

#### 施工任务清单

**任务 3.1: LLM 适配器**
- [ ] 创建 `backend/llm/base.py`: LLM 抽象基类 + `chat_with_tools` 循环
- [ ] 创建 `backend/llm/openai_adapter.py`:
  - [ ] 流式 chat completions
  - [ ] 支持 cancel_event 取消
  - [ ] 从环境变量读取 API key
- [ ] 创建 `backend/llm/ollama_adapter.py`:
  - [ ] 流式 chat (SSE streaming)
  - [ ] 支持取消
  - [ ] 本地模型健康检查
- [ ] 创建 `backend/llm/claude_adapter.py` (可选):
  - [ ] Anthropic Messages API 流式
  - [ ] 支持取消

**任务 3.2: 对话上下文管理**
- [ ] 创建 `backend/session/context.py`:
  - [ ] 维护对话历史 (Message 列表)
  - [ ] 历史长度控制 (token 预算)
  - [ ] 系统提示词模板
  - [ ] 上下文压缩 (超长对话自动摘要)

**任务 3.3: 流式 TTS 编排**
- [ ] 实现 LLM 流式输出 → 按标点切句 → 逐句送 TTS 的 Pipeline
- [ ] 实现首句优先策略：超过 15 个字或遇到句号就立即合成
- [ ] 实现播放队列管理

**任务 3.4: 端到端联通**
- [ ] 更新 `backend/main.py` 中的对话流水线
- [ ] 测试完整链路：说话 → ASR → LLM → 流式 TTS → 播放
- [ ] 测试打断：LLM 生成中被打断 → 取消 LLM 请求 → 清理 → 开始新对话
- [ ] 测试工具调用（先用 mock 工具）

#### 阶段 3 验收标准
- ✅ 问"你好，介绍一下你自己" → LLM 流式生成 → TTS 流式播放回复
- ✅ 首字播放延迟 < 2 秒（从 ASR 完成算起）
- ✅ 对话历史能正确维护（多轮对话上下文不丢失）
- ✅ 打断 LLM 生成 → 状态正确恢复 → 可以开启新对话
- ✅ 切换 LLM 后端 (OpenAI → Ollama) 只需改配置，无需改代码

#### 阶段 3 产出文件
```
backend/
  llm/
    __init__.py
    base.py                 # LLM 抽象 + 工具调用循环
    openai_adapter.py       # OpenAI 适配器
    ollama_adapter.py       # Ollama 适配器
    claude_adapter.py       # Claude 适配器 (可选)
  session/
    context.py              # 对话上下文管理
```

---

### 阶段 4: Live2D 集成 (3-4 天)

#### 目标
Live2D 角色显示在界面上，说话时嘴型同步，有基础表情和空闲动画。

#### 施工任务清单

**任务 4.1: Live2D SDK 集成**
- [ ] 下载 Live2D Cubism SDK for Web (试用版)
- [ ] 准备测试用 Live2D 模型 (如免费模型 Haru/Hiyori)
- [ ] 在前端项目中集成 SDK
- [ ] 创建 `frontend/src/components/Live2DCanvas.tsx`:
  - [ ] 初始化 Cubism Framework
  - [ ] 加载模型 (`.model3.json`)
  - [ ] WebGL 渲染循环
  - [ ] 基础缩放和位置配置

**任务 4.2: 口型同步**
- [ ] 创建 `backend/live2d/motion_controller.py`:
  - [ ] 接收 TTS 音素时间线
  - [ ] 音素 → Live2D 嘴型参数映射 (A/I/U/E/O)
  - [ ] 生成带时间戳的口型帧序列
  - [ ] 通过 WebSocket 发送到前端
- [ ] 前端接收口型帧序列 → 在播放音频时按时间戳应用参数
- [ ] 线性插值处理 (在两个口型帧之间平滑过渡)
- [ ] 测试：播放任意音频 → Live2D 嘴型同步

**任务 4.3: 表情系统**
- [ ] 定义表情映射：
  - `neutral`: 中性的 — IDLE/LISTENING 时
  - `happy`: 开心的 — 对话结束时、正面内容
  - `thinking`: 思考的 — PROCESSING 时
  - `surprised`: 吃惊的 — 被打断时
  - `sad`: 难过 — 负面内容
- [ ] 后端分析 LLM 回复的情绪关键词 → 选择表情
- [ ] 前端实现表情切换动画 (淡入淡出)

**任务 4.4: 身体动作**
- [ ] 空闲动画：呼吸 (Breathing)、眨眼 (Auto Blink)
- [ ] 状态触发动作：
  - LISTENING → 歪头/倾听动作
  - PROCESSING → 思考动作 (手指点下巴等)
  - SPEAKING → 轻微身体晃动
  - INTERRUPTED → 震惊后仰动作

**任务 4.5: 交互优化**
- [ ] 点击 Live2D 角色触发互动（随机动作/语音）
- [ ] 鼠标靠近时角色视线跟随 (Live2D 视线追踪)
- [ ] 动画过渡平滑处理

#### 阶段 4 验收标准
- ✅ Live2D 角色正确显示在窗口中央
- ✅ 说话时嘴型与音频同步（目测无明显错位）
- ✅ 不同状态下表情和动作有明显区别
- ✅ 被打断时角色表情有明显变化
- ✅ 空闲时角色有自然的呼吸和眨眼动画
- ✅ 帧率稳定在 30fps 以上

#### 阶段 4 产出文件
```
backend/
  live2d/
    __init__.py
    motion_controller.py    # 动作/表情/口型控制

frontend/src/
  components/
    Live2DCanvas.tsx         # Live2D 渲染画布
    Live2DModel.ts           # 模型封装类
    LipSyncEngine.ts         # 口型同步引擎
    ExpressionController.ts  # 表情控制器
  hooks/
    useLive2D.ts             # Live2D 控制 hook
  public/
    live2d/
      <model_name>/          # Live2D 模型文件
        <name>.model3.json
        <name>.moc3
        textures/
        motions/
        expressions/
```

---

### 阶段 5: 工具系统 (2-3 天)

#### 目标
工具系统完整可用，LLM 能根据用户问题自动选择合适的工具并调用。

#### 施工任务清单

**任务 5.1: 工具基础设施**
- [ ] 创建 `backend/tools/base.py`: Tool 基类 + Pydantic 集成
- [ ] 创建 `backend/tools/registry.py`: ToolRegistry 注册中心
- [ ] 实现自动发现机制 (内置工具 + 用户工具)
- [ ] 实现 JSON Schema 自动生成

**任务 5.2: 内置工具实现**
- [ ] `time_tool.py`: 获取当前时间
- [ ] `weather_tool.py`: 获取指定城市天气 (调用公开 API)
- [ ] `calculator.py`: 简单数学计算
- [ ] `web_search.py`: 网页搜索 (调用搜索引擎 API)

**任务 5.3: LLM 工具调用集成**
- [ ] 将工具 schema 注入 LLM system prompt / function calling
- [ ] 实现完整的 tool-use 循环：
  ```
  user_input → LLM decides to call tool → execute tool → 
  tool result → LLM generates final response → output
  ```
- [ ] 多轮工具调用支持 (LLM 可能连续调用多个工具)

**任务 5.4: 工具 UX**
- [ ] 前端工具调用进度显示 (ToolProgressMessage 渲染)
- [ ] 前端对话日志中显示工具调用详情
- [ ] 创建 `frontend/src/components/ToolPanel.tsx`: 工具列表和管理
- [ ] 创建 `docs/tool-development.md`: 工具开发指南文档

#### 阶段 5 验收标准
- ✅ 问"现在几点了" → LLM 自动调用 time 工具 → 正确播报时间
- ✅ 问"北京今天天气怎么样" → LLM 调用 weather 工具 → 返回天气信息
- ✅ 问"帮我算一下 123 * 456" → LLM 调用 calculator → 返回正确结果
- ✅ 工具调用过程在前端可见（状态指示）
- ✅ 添加一个自定义工具只需：创建 Python 文件 → 放入 user_tools/ → 重启后端
- ✅ 新工具的描述和参数被 LLM 正确理解和使用

#### 阶段 5 产出文件
```
backend/
  tools/
    __init__.py
    base.py                 # 工具基类
    registry.py             # 注册中心
    builtin/
      __init__.py
      time_tool.py
      weather_tool.py
      calculator.py
      web_search.py
    user_tools/
      .gitkeep

frontend/src/
  components/
    ToolPanel.tsx           # 工具面板

docs/
  tool-development.md       # 工具开发指南
```

---

### 阶段 6: 优化与完善 (2-3 天)

#### 目标
打磨体验细节、提高稳定性、完善配置界面。

#### 施工任务清单

**任务 6.1: 性能优化**
- [ ] 首字延迟优化 (ASR 预热、LLM 连接复用、TTS 预热)
- [ ] 打断延迟优化 (VAD 帧间隔调优)
- [ ] 内存泄漏检查 (长时间对话测试)
- [ ] CPU 占用优化 (VAD 空闲态降频)

**任务 6.2: 用户体验优化**
- [ ] 对话气泡动画
- [ ] 打断后的自然语言过渡 ("好的，你想说什么？")
- [ ] 无输入超时进入空闲动画
- [ ] 启动画面 + 模型加载进度
- [ ] 错误提示友好化

**任务 6.3: 设置面板**
- [ ] 创建 `frontend/src/components/SettingsPanel.tsx`:
  - [ ] ASR 引擎选择
  - [ ] TTS 声音选择 + 试听
  - [ ] LLM 后端切换 + API Key 配置
  - [ ] Live2D 模型选择
  - [ ] VAD 灵敏度调整
  - [ ] 音量调节
- [ ] 配置热更新 (部分配置可运行时生效)

**任务 6.4: 健壮性**
- [ ] 所有外部 API 调用加超时 + 重试
- [ ] 模型加载失败 → fallback 到更轻量的方案
- [ ] 异常状态自动恢复 (any → IDLE)
- [ ] 日志系统 (分级日志 + 文件输出)

**任务 6.5: 打包发布**
- [ ] electron-builder 配置
- [ ] Python 环境打包 (嵌入式 Python 或 PyInstaller)
- [ ] 模型文件打包策略 (首次启动下载 vs 预打包)
- [ ] Windows 安装包生成

#### 阶段 6 验收标准
- ✅ 连续对话 30 分钟不崩溃、不卡顿
- ✅ 首字延迟 < 2 秒，打断延迟 < 300ms
- ✅ 所有配置项可通过 UI 修改
- ✅ 离线状态 (无 LLM API) 有友好提示
- ✅ 生成可分发安装包

---

## 6. 配置系统设计

### 6.1 配置文件层次

```
优先级 (高 → 低):
1. 环境变量 (敏感信息): .env 文件
2. 用户配置: config.user.yaml (不提交 git)
3. 默认配置: config.default.yaml (提交 git)
```

### 6.2 默认配置文件

```yaml
# backend/config.default.yaml

# === 应用基础 ===
app:
  name: "智能助手"
  version: "0.1.0"
  host: "127.0.0.1"
  port: 8765
  log_level: "info"  # debug | info | warn | error

# === 语音活动检测 ===
vad:
  engine: "silero"           # silero
  sample_rate: 16000
  frame_duration_ms: 30      # 每帧时长
  speech_threshold: 0.5      # 语音概率阈值 (0~1)
  speech_start_frames: 5     # 连续 N 帧有声 → 开始说话
  silence_end_frames: 15     # 连续 N 帧静音 → 说话结束 (~450ms)
  interrupt_frames: 4        # 打断检测需要的连续语音帧 (~120ms)
  max_speech_duration_s: 30  # 单次说话最长时长（超时自动截断）

# === 语音识别 ===
asr:
  engine: "funasr"           # funasr | whisper | sherpa-onnx
  funasr:
    model: "iic/SenseVoiceSmall"
    device: "cpu"            # cpu | cuda
    language: "zh"
    use_itn: true            # 逆文本归一化
    use_punc: true           # 标点恢复

# === 语音合成 ===
tts:
  engine: "edge-tts"         # edge-tts | gpt-sovits
  edge_tts:
    voice: "zh-CN-XiaoxiaoNeural"
    speed: "+0%"             # 语速: -50% ~ +100%
    pitch: "+0Hz"            # 音调
  gpt_sovits:
    api_url: "http://localhost:9880"
    character: "default"

# === 大语言模型 ===
llm:
  engine: "openai"           # openai | ollama | claude
  system_prompt: >
    你是一个友好的桌面 AI 助手，名叫小助。你有 Live2D 形象，能与用户进行语音对话。
    回答应当简洁、自然，像日常对话一样。回答不超过 100 字。
    当用户询问时间、天气、需要计算或搜索时，使用可用的工具。
  
  openai:
    model: "gpt-4o"
    base_url: "https://api.openai.com/v1"
    temperature: 0.7
    max_tokens: 1024
    # api_key 从环境变量 OPENAI_API_KEY 读取
    
  ollama:
    base_url: "http://localhost:11434"
    model: "qwen2.5:7b"
    temperature: 0.7
    
  claude:
    model: "claude-sonnet-4-6"
    max_tokens: 1024
    # api_key 从环境变量 ANTHROPIC_API_KEY 读取

# === Live2D ===
live2d:
  model_path: "frontend/public/live2d/hiyori/hiyori.model3.json"
  scale: 1.0
  auto_blink: true
  blink_interval_min_ms: 2000
  blink_interval_max_ms: 6000
  idle_motion_group: "idle"
  breathing_rate: 0.8       # 呼吸频率

# === 工具系统 ===
tools:
  user_tools_dir: "backend/tools/user_tools"
  enabled_builtin:           # 启用的内置工具
    - "get_current_time"
    - "get_weather"
    - "calculate"
    - "web_search"
  max_tool_rounds: 5        # 单次对话最多工具调用轮数

# === 对话 ===
conversation:
  max_history_messages: 20   # 最大历史消息数
  max_context_tokens: 4000   # 最大上下文 token 数
  silence_timeout_s: 30      # 无对话超时回到 IDLE
```

---

## 7. 项目目录结构

```
project/
│
├── README.md                     # 项目说明
├── DESIGN_AND_PLAN.md            # 本文档
│
├── backend/                      # Python 后端
│   ├── main.py                   # FastAPI 入口 + WebSocket 端点
│   ├── config.py                 # 配置加载
│   ├── config.default.yaml       # 默认配置
│   ├── requirements.txt          # Python 依赖
│   ├── .env.example              # 环境变量模板
│   │
│   ├── session/                  # 会话管理
│   │   ├── __init__.py
│   │   ├── manager.py           # 会话状态机
│   │   └── context.py           # 对话上下文
│   │
│   ├── vad/                      # 语音活动检测
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── silero_adapter.py
│   │
│   ├── asr/                      # 语音识别
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── funasr_adapter.py
│   │
│   ├── tts/                      # 语音合成
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── edge_tts_adapter.py
│   │   └── streaming.py         # 流式 TTS 编排器
│   │
│   ├── llm/                      # 大语言模型
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── openai_adapter.py
│   │   ├── ollama_adapter.py
│   │   └── claude_adapter.py
│   │
│   ├── tools/                    # 工具系统
│   │   ├── __init__.py
│   │   ├── base.py              # 工具基类
│   │   ├── registry.py          # 注册中心
│   │   ├── builtin/             # 内置工具
│   │   │   ├── __init__.py
│   │   │   ├── time_tool.py
│   │   │   ├── weather_tool.py
│   │   │   ├── calculator.py
│   │   │   └── web_search.py
│   │   └── user_tools/          # 用户自定义工具
│   │       └── .gitkeep
│   │
│   └── live2d/                   # Live2D 动画控制
│       ├── __init__.py
│       └── motion_controller.py
│
├── frontend/                     # React 前端
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── index.html
│   │
│   ├── public/
│   │   └── live2d/              # Live2D 模型文件
│   │       └── hiyori/          # 示例模型
│   │           ├── hiyori.model3.json
│   │           ├── Hiyori.moc3
│   │           ├── textures/
│   │           ├── motions/
│   │           └── expressions/
│   │
│   └── src/
│       ├── App.tsx               # 主应用
│       ├── App.css
│       ├── main.tsx              # React 入口
│       │
│       ├── components/           # UI 组件
│       │   ├── Live2DCanvas.tsx      # Live2D 画布
│       │   ├── Live2DModel.ts        # Live2D 模型封装
│       │   ├── LipSyncEngine.ts      # 口型同步引擎
│       │   ├── StatusIndicator.tsx   # 状态指示器
│       │   ├── ChatBubble.tsx        # 对话气泡
│       │   ├── ToolPanel.tsx         # 工具面板
│       │   └── SettingsPanel.tsx     # 设置面板
│       │
│       ├── hooks/                # React Hooks
│       │   ├── useWebSocket.ts       # WebSocket 连接
│       │   ├── useAudioCapture.ts    # 麦克风捕获
│       │   ├── useAudioPlayback.ts   # 音频播放
│       │   └── useLive2D.ts          # Live2D 控制
│       │
│       ├── services/             # 服务
│       │   └── ws-client.ts          # WebSocket 客户端
│       │
│       ├── stores/               # 状态管理
│       │   └── agent-store.ts        # Zustand Store
│       │
│       └── types/                # 类型定义
│           └── index.ts
│
├── electron/                     # Electron 主进程
│   ├── main.ts                   # 主进程入口
│   ├── preload.ts               # 预加载脚本
│   ├── python-bridge.ts         # Python 进程管理
│   └── audio-capture.ts         # 音频设备管理
│
├── resources/                    # 静态资源
│   ├── models/                   # ASR/VAD 模型下载目录 (gitignore)
│   │   └── .gitkeep
│   └── icons/                    # 应用图标
│
├── docs/                         # 文档
│   ├── tool-development.md       # 工具开发指南
│   ├── live2d-setup.md           # Live2D 配置指南
│   └── troubleshooting.md        # 常见问题
│
├── .gitignore
└── electron-builder.json         # Electron 打包配置
```

---

## 8. 风险与对策

### 8.1 技术风险

| 编号 | 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|------|----------|
| R1 | FunASR 在 Windows pip 安装依赖冲突 | 中 | 高 | 备选 Sherpa-ONNX (纯 C++ 编译, Windows 支持好)；第二阶段预留时间解决 |
| R2 | Edge-TTS 字词边界精度不足以驱动嘴型 | 中 | 中 | 降级方案：简单的音量驱动嘴型 (audio-driven)，放弃精确音素同步；或使用 GPT-SoVITS |
| R3 | Live2D Cubism SDK for Web 学习曲线 | 中 | 中 | 使用 pixi-live2d-display 社区封装简化集成；准备足够的第四阶段时间 |
| R4 | Electron 打包 Python 环境体积过大 | 高 | 低 | 使用嵌入式 Python (python-embed-amd64) 减少体积；模型文件首次启动下载 |
| R5 | Silero VAD 在嘈杂环境中误触发 | 低 | 中 | 提供灵敏度配置滑块；可考虑前端侧做简单的能量阈值预过滤 |
| R6 | Python asyncio 任务取消不彻底 (Windows 限制) | 中 | 中 | 使用 cancel_event 模式替代 Task.cancel；关键路径加检查点 |

### 8.2 应对策略

1. **分阶段应对**：每个阶段有验收标准，不通过不进入下一阶段
2. **接口先行**：所有模块先定义抽象接口，实现可替换
3. **降级策略**：每个模块至少有一个可行的备选方案
4. **时间缓冲**：每个阶段的时间预估已包含 20% 缓冲

---

## 9. 验收标准

### 9.1 分阶段验收

见"分阶段施工计划"中各阶段的验收标准。

### 9.2 最终验收

| 验收项 | 标准 |
|--------|------|
| 语音识别准确率 | 安静环境中文识别准确率 > 95% |
| 端到端延迟 | 从 ASR 完成到首字播放 < 2 秒 |
| 打断响应 | 从用户开始说话到 AI 停止 < 300ms |
| Live2D 口型同步 | 目测无明显错位 |
| 工具调用准确率 | 常见问题 (时间、天气、计算) 正确调用率 100% |
| 稳定性 | 连续对话 30 分钟无崩溃 |
| 内存占用 | 空闲 < 500MB，对话中 < 2GB |
| CPU 占用 | 空闲 < 5%，对话中 < 40% |
| 可扩展性 | 添加新工具 < 50 行代码 |

---

## 附录 A: Python 依赖清单

```
# backend/requirements.txt

# Web 框架
fastapi==0.115.*
uvicorn[standard]==0.34.*

# 音频处理
pyaudio==0.2.*
numpy==2.*
soundfile==0.12.*

# VAD
silero-vad==5.*

# ASR - FunASR
funasr==1.*
torch==2.*        # FunASR 依赖

# TTS - Edge-TTS
edge-tts==6.*

# LLM
openai==1.*       # OpenAI SDK (兼容 Ollama)
anthropic==0.*    # Claude SDK (可选)

# 配置
pyyaml==6.*
python-dotenv==1.*

# 工具
httpx==0.28.*     # 异步 HTTP 客户端 (搜索/天气 API 用)
pydantic==2.*     # 数据校验

# 工具开发
zoneinfo==0.*     # 时区支持
```

## 附录 B: 前端依赖清单

```json
{
  "dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "zustand": "^5.0.0",
    "pixi.js": "^8.0.0",
    "pixi-live2d-display": "^0.5.0"
  },
  "devDependencies": {
    "typescript": "^5.7.0",
    "vite": "^6.0.0",
    "@vitejs/plugin-react": "^4.0.0",
    "electron": "^31.0.0",
    "electron-builder": "^25.0.0",
    "vite-plugin-electron": "^0.28.0"
  }
}
```

---

> **下一步：** 确认本计划后，按阶段 1 → 2 → 3 → 4 → 5 → 6 的顺序开始施工。每个阶段完成后进行验收，验收通过再进入下一阶段。
