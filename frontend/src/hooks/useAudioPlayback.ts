/**
 * TTS 音频播放 Hook (AudioContext 驱动)。
 *
 * 监听 store 的 ttsSpeech 状态，用 AudioContext + AudioBufferSourceNode
 * 精确播放音频，并记录 playbackStartTime 供 Live2D rAF 同步口型。
 *
 * ponytail: 模块级单例 audioEngine，避免重复创建 AudioContext。
 *           所有 AudioContext 操作包裹 try-catch，失败不影响渲染。
 */

import { useEffect } from "react";
import { useAgentStore } from "../stores/agent-store";

// ── 模块级单例 (惰性初始化，不在模块加载时创建) ──────────
let _audioCtx: AudioContext | null = null;
let _playbackStartTime = 0;
let _currentSource: AudioBufferSourceNode | null = null;

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

export function useAudioPlayback(): void {
  useEffect(() => {
    const unsub = useAgentStore.subscribe(
      (state) => state.ttsSpeech,
      async (speech) => {
        if (!speech?.audio) return;
        console.log("[Audio] ttsSpeech received, entries:", speech.entries?.length, "durationMs:", speech.durationMs);

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
              _currentSource = null;
            }
            console.log("[Audio] playback ended");
          };
        } catch (e) {
          console.error("[Audio] playback failed:", e);
        }
      }
    );

    return () => {
      unsub();
      audioEngine.stop();
    };
  }, []);
}
