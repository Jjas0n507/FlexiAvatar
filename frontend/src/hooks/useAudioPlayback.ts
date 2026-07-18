/**
 * TTS 音频播放 Hook（RMS 口型驱动）。
 *
 * FIFO 队列 + 泵循环：每段先应用表情，再 await speak(bytes) —
 * live2d-renderer 的 inputAudio 负责解码(MP3/WAV)、播放、每帧 RMS 驱动口型，
 * 音频和口型读同一份采样数据，结构上不可能失步。
 *
 * 队列排空 → 300ms 防抖发送 playback.done。
 * 打断（sessionState=interrupted）→ stopAll()：停音频+清队列+按 utteranceId 丢迟到段。
 */

import { useEffect } from "react";
import { useAgentStore } from "../stores/agent-store";
import { wsClient } from "../services/ws-client";

// ── 桥接口（Live2DCanvas 在模型加载后注册）────────
export interface SpeakerBridge {
  /** 播放一段音频并驱动口型；resolve = 播放结束 */
  speak: (buf: ArrayBuffer, mime: string) => Promise<void>;
  /** 立即停止播放和口型 */
  stop: () => void;
}

interface Segment {
  buf: ArrayBuffer;
  mime: string;
  expression: string | null;
  utteranceId: string;
}

// ── 模块级单例 ────────────────────────────────────
let _bridge: SpeakerBridge | null = null;
let _exprSetter: ((name: string) => void) | null = null;
const _queue: Segment[] = [];
let _pumping = false;
let _staleUtteranceId: string | null = null;
let _lastUtteranceId: string | null = null;
let _doneTimer: ReturnType<typeof setTimeout> | null = null;

export function registerSpeaker(bridge: SpeakerBridge | null): void {
  _bridge = bridge;
  if (bridge && _queue.length > 0) void pump(); // 模型晚于音频就绪时补泵
}

export function registerExpressionSetter(fn: ((name: string) => void) | null): void {
  _exprSetter = fn;
}

function schedulePlaybackDone(): void {
  if (_doneTimer) clearTimeout(_doneTimer);
  _doneTimer = setTimeout(() => {
    console.log("[Audio] sending playback.done");
    wsClient.sendPlaybackDone();
    _doneTimer = null;
  }, 300);
}

async function pump(): Promise<void> {
  if (_pumping) return;
  _pumping = true;
  try {
    while (_queue.length > 0) {
      if (!_bridge) return; // 模型未就绪：保留队列，registerSpeaker 时补泵
      const seg = _queue.shift()!;
      if (seg.utteranceId === _staleUtteranceId) continue; // 打断后的迟到段
      _exprSetter?.(seg.expression ?? "neutral");
      try {
        await _bridge.speak(seg.buf, seg.mime);
      } catch (e) {
        console.error("[Audio] segment playback failed (skipped):", e);
        // decode/播放失败只跳本段，泵不停
      }
    }
    schedulePlaybackDone();
  } finally {
    _pumping = false;
    if (_bridge && _queue.length > 0) void pump(); // 泵收尾瞬间的新入队
  }
}

/** 停止播放：清队列 + 停音频/口型 + 表情复位；之后同 utteranceId 的迟到段直接丢弃 */
export function stopAll(): void {
  _staleUtteranceId = _lastUtteranceId;
  _queue.length = 0;
  _bridge?.stop();
  _exprSetter?.("neutral");
  if (_doneTimer) {
    clearTimeout(_doneTimer);
    _doneTimer = null;
  }
}

export function useAudioPlayback(): void {
  useEffect(() => {
    const unsubTts = useAgentStore.subscribe(
      (state) => state.ttsSpeech,
      (speech) => {
        if (!speech?.audio) return;
        if (speech.utteranceId && speech.utteranceId === _staleUtteranceId) {
          console.log("[Audio] stale segment dropped:", speech.utteranceId, speech.seq);
          return;
        }

        // base64 → ArrayBuffer
        const binary = atob(speech.audio);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

        _lastUtteranceId = speech.utteranceId ?? null;
        _queue.push({
          buf: bytes.buffer,
          mime: speech.format === "wav" ? "audio/wav" : "audio/mpeg",
          expression: speech.expressions?.[0]?.name ?? null,
          utteranceId: speech.utteranceId ?? "",
        });
        if (_doneTimer) {
          clearTimeout(_doneTimer);
          _doneTimer = null;
        }
        void pump();
      }
    );

    const unsubState = useAgentStore.subscribe(
      (state) => state.sessionState,
      (state) => {
        if (state === "interrupted") stopAll();
      }
    );

    return () => {
      unsubTts();
      unsubState();
      stopAll();
    };
  }, []);
}
