/**
 * TTS 音频播放 Hook (AudioContext 驱动)。
 *
 * 监听 store 的 ttsSpeech 状态，用 AudioContext + AudioBufferSourceNode
 * 精确播放音频，并记录 playbackStartTime 供 Live2D rAF 同步口型。
 *
 * Phase B: 音频自然结束后发送 playback.done 通知后端。
 *
 * ponytail: 模块级单例 audioEngine，避免重复创建 AudioContext。
 *           所有 AudioContext 操作包裹 try-catch，失败不影响渲染。
 */

import { useEffect } from "react";
import { useAgentStore } from "../stores/agent-store";
import { wsClient } from "../services/ws-client";

// ── 模块级单例 (惰性初始化，不在模块加载时创建) ──────────
let _audioCtx: AudioContext | null = null;
let _playbackStartTime = 0;
let _currentSource: AudioBufferSourceNode | null = null;
let _doneTimer: ReturnType<typeof setTimeout> | null = null;  // Phase B

function getAudioContext(): AudioContext | null {
  if (_audioCtx) return _audioCtx;
  try {
    const Ctx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!Ctx) return null;
    _audioCtx = new Ctx();
  } catch (e) {
    console.error("[Audio] AudioContext init failed:", e);
    return null;
  }
  return _audioCtx;
}

export const audioEngine = {
  get audioCtx(): AudioContext | null {
    return _audioCtx;
  },
  get playbackStartTime(): number {
    return _playbackStartTime;
  },
  stop(): void {
    if (_currentSource) {
      try {
        _currentSource.stop();
      } catch {
        // already stopped
      }
      _currentSource = null;
    }
    _playbackStartTime = 0;
  },
};

/** Phase B: 调度 playback.done，会被新音频到达取消 */
function schedulePlaybackDone(): void {
  if (_doneTimer) clearTimeout(_doneTimer);
  _doneTimer = setTimeout(() => {
    console.log("[Audio] sending playback.done");
    wsClient.sendPlaybackDone();
    _doneTimer = null;
  }, 300);  // 300ms 宽限期，让后续音频段有机会到达
}

export function useAudioPlayback(): void {
  useEffect(() => {
    const unsub = useAgentStore.subscribe(
      (state) => state.ttsSpeech,
      async (speech) => {
        if (!speech?.audio) return;

        // Phase B: 新音频到达时取消待发的 playback.done
        if (_doneTimer) {
          clearTimeout(_doneTimer);
          _doneTimer = null;
        }

        console.log("[Audio] ttsSpeech received, phonemes:", speech.phonemes?.length, "durationMs:", speech.durationMs);

        const ctx = getAudioContext();
        if (!ctx) {
          console.warn("[Audio] No AudioContext, skipping playback");
          return;
        }

        // autoplay policy: resume if suspended
        if (ctx.state === "suspended") {
          try {
            await ctx.resume();
            console.log("[Audio] AudioContext resumed");
          } catch {
            // ignore
          }
        }

        // stop previous source
        audioEngine.stop();

        try {
          // base64 → ArrayBuffer
          const binary = atob(speech.audio);
          const bytes = new Uint8Array(binary.length);
          for (let i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
          }

          // decode WAV → AudioBuffer
          const audioBuffer = await ctx.decodeAudioData(bytes.buffer.slice(0));
          console.log("[Audio] decoded, duration:", audioBuffer.duration, "s");

          // create source + play
          const source = ctx.createBufferSource();
          source.buffer = audioBuffer;
          source.connect(ctx.destination);
          source.start();
          _currentSource = source;
          _playbackStartTime = ctx.currentTime;
          console.log("[Audio] playback started, playbackStartTime:", _playbackStartTime);

          source.onended = () => {
            if (_currentSource === source) {
              // 自然播完（未被新段打断）
              _currentSource = null;
              console.log("[Audio] playback ended (natural)");
              // Phase B: 宽限期后通知后端（等待后续音频段）
              schedulePlaybackDone();
            } else {
              console.log("[Audio] playback ended (interrupted by next segment)");
            }
          };
        } catch (e) {
          console.error("[Audio] playback failed:", e);
        }
      }
    );

    return () => {
      unsub();
      audioEngine.stop();
      if (_doneTimer) {
        clearTimeout(_doneTimer);
        _doneTimer = null;
      }
    };
  }, []);
}
