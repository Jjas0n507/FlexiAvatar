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
  phonemes: Phoneme[];
  format: string;    // "wav" | "mp3"
  // audio data follows as binary
}

export interface Phoneme {
  phoneme: string;
  startMs: number;
  endMs: number;
}

export interface Live2DControlPayload {
  command: "lip_sync" | "expression" | "motion" | "idle" | "reset" | "interrupt" | "state";
  lipSyncFrames?: LipSyncFrame[];
  expression?: ExpressionParams;
  motion?: MotionParams;
  state?: string;
  idleEnabled?: boolean;
  audioStartTime?: number;
}

export interface LipSyncFrame {
  timeMs: number;
  mouth: string;      // A, I, U, E, O, N
  params: Record<string, number>;
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
