/**
 * TTS 音频播放 Hook (HTMLAudioElement 驱动)。
 *
 * 监听 store 的 ttsSpeech 状态，用 <audio> 元素播放音频并记录
 * playbackStartTime 供 Live2D rAF 同步口型。
 *
 * Phase B: 音频自然结束后发送 playback.done 通知后端。
 *
 * ponytail: 用 <audio> 替代 WebAudio API (decodeAudioData + AudioBufferSourceNode)。
 *           浏览器媒体栈独立线程处理音频，不与 WebGL 渲染争主线程，
 *           避免 Linux/AMD 上 AudioContext + WebGL 竞争导致 60→7 FPS 暴跌。
 *           保留 AudioContext 仅用于 currentTime 时钟。
 */

import { useEffect } from "react";
import { useAgentStore } from "../stores/agent-store";
import { wsClient } from "../services/ws-client";

// ── 模块级单例 ────────────────────────────────────
let _audioCtx: AudioContext | null = null;
let _audioEl: HTMLAudioElement | null = null;
let _playbackStartTime = 0;
let _currentBlobUrl: string | null = null;
let _doneTimer: ReturnType<typeof setTimeout> | null = null;

function getAudioContext(): AudioContext | null {
  if (_audioCtx) return _audioCtx;
  try {
    const Ctx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!Ctx) return null;
    _audioCtx = new Ctx();
  } catch {
    return null;
  }
  return _audioCtx;
}

function getAudioEl(): HTMLAudioElement {
  if (!_audioEl) {
    _audioEl = new Audio();
    _audioEl.preload = "auto";
  }
  return _audioEl;
}

// ponytail: 全局导出 audioEngine 供 Live2DCanvas rAF 同步
export const audioEngine = {
  get audioCtx(): AudioContext | null {
    return _audioCtx;
  },
  get playbackStartTime(): number {
    return _playbackStartTime;
  },
  stop(): void {
    const el = _audioEl;
    if (el) {
      el.pause();
      el.currentTime = 0;
    }
    _playbackStartTime = 0;
  },
};

function schedulePlaybackDone(): void {
  if (_doneTimer) clearTimeout(_doneTimer);
  _doneTimer = setTimeout(() => {
    console.log("[Audio] sending playback.done");
    wsClient.sendPlaybackDone();
    _doneTimer = null;
  }, 300);
}

export function useAudioPlayback(): void {
  useEffect(() => {
    const unsub = useAgentStore.subscribe(
      (state) => state.ttsSpeech,
      async (speech) => {
        if (!speech?.audio) return;

        if (_doneTimer) {
          clearTimeout(_doneTimer);
          _doneTimer = null;
        }

        console.log("[Audio] ttsSpeech received, phonemes:", speech.phonemes?.length, "durationMs:", speech.durationMs);

        // 确保 AudioContext 存在（仅用作时钟源）
        const ctx = getAudioContext();
        if (!ctx) {
          console.warn("[Audio] No AudioContext, skipping");
          return;
        }

        if (ctx.state === "suspended") {
          try { await ctx.resume(); } catch { /* ignore */ }
        }

        // 停止前一段音频
        audioEngine.stop();

        // 释放旧 blob URL
        if (_currentBlobUrl) {
          URL.revokeObjectURL(_currentBlobUrl);
          _currentBlobUrl = null;
        }

        try {
          // base64 → Blob → Object URL
          const binary = atob(speech.audio);
          const bytes = new Uint8Array(binary.length);
          for (let i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
          }
          const blob = new Blob([bytes.buffer], { type: "audio/wav" });
          _currentBlobUrl = URL.createObjectURL(blob);

          const el = getAudioEl();
          el.src = _currentBlobUrl;

          // ponytail: HTMLAudioElement 播放，浏览器媒体线程处理
          await el.play();
          _playbackStartTime = ctx.currentTime;
          console.log("[Audio] playback started via <audio>, playbackStartTime:", _playbackStartTime);

          el.onended = () => {
            console.log("[Audio] playback ended (natural)");
            schedulePlaybackDone();
          };
        } catch (e) {
          console.error("[Audio] playback failed:", e);
        }
      }
    );

    return () => {
      unsub();
      audioEngine.stop();
      if (_currentBlobUrl) {
        URL.revokeObjectURL(_currentBlobUrl);
        _currentBlobUrl = null;
      }
      if (_doneTimer) {
        clearTimeout(_doneTimer);
        _doneTimer = null;
      }
    };
  }, []);
}
