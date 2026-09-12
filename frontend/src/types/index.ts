/**
 * 全局类型定义
 */

// ── 会话状态 ────────────────────────────────
export type SessionState =
  | "idle"
  | "listening"
  | "processing"
  | "speaking"
  | "interrupted";

// ── WebSocket 消息基础结构 ──────────────────
export interface WSMessage {
  type: string;
  id: string;
  timestamp: number;
  payload: Record<string, unknown>;
}

// ── 具体消息类型 ────────────────────────────

export interface StateChangePayload {
  state: SessionState;
  previous?: string;
  reason?: string;
  tools?: string[];
}

export interface ASRResultPayload {
  text: string;
  isFinal: boolean;
  confidence: number;
}

export interface LLMStreamPayload {
  text: string;
  isFirstChunk: boolean;
  isLastChunk: boolean;
}

export interface TTSAudioPayload {
  sentence: string;
  format: string;    // "wav" | "mp3"
  // audio data follows as binary
}

/** tts.audio 附带的表情事件（分段开头应用） */
export interface TTSExpression {
  name: string;
  durationMs: number;
}

/** 后端 tts.audio 消息的 payload（一句话一段音频，口型由前端 RMS 驱动） */
export interface TTSSpeechPayload {
  utteranceId: string;        // 一次 LLM 回复一个 id，打断后丢弃迟到段
  seq: number;                // 句序号
  audio: string;              // base64 音频（format 指定编码）
  format: "wav" | "mp3";
  durationMs: number;
  text?: string;
  expressions: TTSExpression[];
}

export interface Live2DControlPayload {
  command: "expression" | "motion" | "interrupt" | "reset" | "state";
  expression?: ExpressionParams;
  motion?: MotionParams;
  state?: string;
  idleEnabled?: boolean;
}

export interface ExpressionParams {
  name: string;
  intensity: number;
  fadeInMs: number;
  durationMs: number;
  fadeOutMs: number;
}

export interface MotionParams {
  group: string;
  index: number;
  priority: number;
}

export interface ToolProgressPayload {
  name: string;
  status: "calling" | "running" | "done" | "error";
  params?: Record<string, unknown>;
  result?: string;
  error?: string;
}

export interface ErrorPayload {
  code: string;
  message: string;
  recoverable: boolean;
}

// ── 应用配置 ────────────────────────────────
// ── ModelProfile (后端 live2d.profile 消息) ─────

export interface ModelProfileLipSync {
  open_y: string;
  form: string;
}

export interface ModelProfileEyes {
  left_open: string;
  right_open: string;
  left_smile: string;
  right_smile: string;
  eyeball_x: string;
  eyeball_y: string;
}

export interface ModelProfileBrows {
  left_y: string;
  right_y: string;
  left_x: string;
  right_x: string;
}

export interface ModelProfileHead {
  angle_z: string;
}

export interface ModelProfileBody {
  angle_x: string;
}

export interface ModelProfileParameters {
  lip_sync: ModelProfileLipSync;
  eyes: ModelProfileEyes;
  brows: ModelProfileBrows;
  head: ModelProfileHead;
  body: ModelProfileBody;
  extra: string[];
}

export interface MouthShapeValue {
  open_y: number;
  form: number;
}

export interface ModelProfileExpression {
  type: "native" | "params";
  name?: string | null;
  params?: Record<string, number>;
}

export interface ModelProfileMotion {
  group: string;
  index: number;
}

export interface ModelProfileIdle {
  expression_cycle: string[];
  expression_interval: [number, number];
  blink_interval: [number, number];
  eye_drift_range: number;
  head_tilt_chance: number;
  head_tilt_angle: number;
}

export interface ModelProfile {
  name: string;
  model3_path: string;
  scale: number;
  parameters: ModelProfileParameters;
  mouth_shapes: Record<string, MouthShapeValue>;
  expressions: Record<string, ModelProfileExpression>;
  motions: Record<string, ModelProfileMotion[]>;
  idle: ModelProfileIdle;
}

// ── 应用配置 ────────────────────────────────
export interface AppConfig {
  asr: {
    engine: string;
    language: string;
  };
  tts: {
    engine: string;
    voice: string;
    speed: string;
  };
  llm: {
    engine: string;
    model: string;
  };
  live2d: {
    modelPath: string;
    scale: number;
  };
  vad: {
    threshold: number;
    silenceDurationMs: number;
  };
}

// ── 形象（Avatar）────────────────────────────
// 后端 avatar.profile 消息按 type 判别的联合类型。
// Live2D 沿用 ModelProfile（结构不变），数字人用 DigitalHumanProfile。

export type AvatarType = "live2d" | "digital_human";

/** 数字人的一个情绪实现 */
export type AvatarExpression =
  /** 多个 morph 加权（RPM / ARKit / VRoid / facecap 这类逐 blendshape 模型） */
  | { type: "blendshapes"; params: Record<string, number> }
  /** 单个整脸 morph（RobotExpressive 这类只有整脸表情的模型） */
  | { type: "morph"; name: string };

/** 口型驱动方式 */
export type AvatarMouthOpen =
  /** 直接驱动某个 morph 的权重（配 lip_sync.gain 标定） */
  | { kind: "morph"; name: string }
  /** 无嘴部 morph 时的发声代理：以 amount 强度整体叠加某个整脸 morph */
  | { kind: "add"; name: string; amount: number };

export interface DigitalHumanProfile {
  type: "digital_human";
  name: string;
  model_path: string;                 // 相对 public 的 URL，如 "avatar/_placeholder/facecap.glb"
  camera?: {
    position?: [number, number, number];
    target?: [number, number, number];
    fov?: number;
  };
  morphs: {
    mouth_open?: AvatarMouthOpen;
    blink_left?: string;
    blink_right?: string;
  };
  lip_sync: { gain: number; smoothing: number };
  expressions: Record<string, AvatarExpression>;
  idle: {
    blink_interval: [number, number];
    expression_cycle: string[];
    expression_interval: [number, number];
    look_at_range: number;
  };
  // 预留关联字段（本版只显示，不消费）
  persona_id?: string;
  voice_id?: string;
}

export interface Live2DAvatarProfile extends ModelProfile {
  type: "live2d";
}

export type AvatarProfile = Live2DAvatarProfile | DigitalHumanProfile;

/** 后端 /api/avatars 与 avatar.select 的形象清单条目 */
export interface AvatarEntry {
  id: string;
  name: string;
  type: AvatarType;
  model_path: string;
  profile_path: string;
  valid: boolean;
  reason?: string;
  // 预留关联字段（本版只显示，不消费）
  persona_id?: string;
  voice_id?: string;
}

export interface AvatarCatalog {
  live2d: AvatarEntry[];
  digital_human: AvatarEntry[];
  /** 后端当前生效的形象 id（用于选择页默认高亮） */
  current?: string;
  /** 后端当前生效的类型（用于选择页默认模式页签） */
  type?: AvatarType;
}

