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
