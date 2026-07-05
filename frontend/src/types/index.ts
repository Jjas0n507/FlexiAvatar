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
