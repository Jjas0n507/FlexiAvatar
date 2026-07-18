/**
 * 麦克风采集 Hook。
 *
 * MediaStreamTrackProcessor 直读 AudioData —— 全程零 AudioContext。
 * 这台 AMD/Linux 机器上任何 running AudioContext 都会把 WebGL 压到
 * ~10FPS 且不恢复（旧 ScriptProcessor 方案的 processor→destination
 * 打开了扬声器输出流，正是 FPS 崩溃的根因）。
 * 设备采样率（常见 48k）线性重采样到 16k，攒满 512 样本
 * （Silero VAD 帧长）发一包 audio.chunk。
 */

import { useRef, useCallback, useState } from "react";
import { wsClient } from "../services/ws-client";

const TARGET_RATE = 16000;
const FRAME = 512; // Silero VAD 要求 512 样本 @ 16kHz

// MediaStreamTrackProcessor 尚未进 TS dom lib，最小声明
interface AudioDataFrame {
  numberOfFrames: number;
  sampleRate: number;
  copyTo(dest: Float32Array, opts: { planeIndex: number; format?: string }): void;
  close(): void;
}

export function useMicCapture() {
  const [isRecording, setIsRecording] = useState(false);
  const stopRef = useRef<(() => void) | null>(null);

  const startMic = useCallback(async () => {
    if (!("MediaStreamTrackProcessor" in window)) {
      console.error("[Mic] MediaStreamTrackProcessor 不可用（需 Chromium 94+）");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: TARGET_RATE, channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      const track = stream.getAudioTracks()[0];
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const processor = new (window as any).MediaStreamTrackProcessor({ track });
      const reader: ReadableStreamDefaultReader<AudioDataFrame> = processor.readable.getReader();

      let alive = true;
      stopRef.current = () => {
        alive = false;
        void reader.cancel().catch(() => { /* ignore */ });
        track.stop();
      };

      // 跨 AudioData 块连续的线性重采样状态
      let pos = 0; // 小数读头，相对 [上块末样本, ...当前块] 拼接流
      let last = 0;
      let hasLast = false;
      const out = new Int16Array(FRAME);
      let outLen = 0;

      const sendFrame = () => {
        if (!wsClient.isConnected) return;
        const bytes = new Uint8Array(out.buffer, 0, FRAME * 2);
        let binary = "";
        for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
        wsClient.send("audio.chunk", { data: btoa(binary) });
      };

      void (async () => {
        try {
          while (alive) {
            const { value: frame, done } = await reader.read();
            if (done || !frame) break;
            const n = frame.numberOfFrames;
            const chunk = new Float32Array(n);
            frame.copyTo(chunk, { planeIndex: 0, format: "f32-planar" });
            const step = frame.sampleRate / TARGET_RATE;
            frame.close();

            // 拼上上一块末样本做跨界插值
            let src: Float32Array;
            if (hasLast) {
              src = new Float32Array(n + 1);
              src[0] = last;
              src.set(chunk, 1);
            } else {
              src = chunk;
            }

            let i = pos;
            while (i + 1 < src.length) {
              const i0 = Math.floor(i);
              const s = src[i0] + (src[i0 + 1] - src[i0]) * (i - i0);
              const clamped = Math.max(-1, Math.min(1, s));
              out[outLen++] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
              if (outLen === FRAME) {
                sendFrame();
                outLen = 0;
              }
              i += step;
            }
            pos = i - (src.length - 1);
            last = src[src.length - 1];
            hasLast = true;
          }
        } catch (e) {
          if (alive) console.error("[Mic] read loop error:", e);
        }
      })();

      setIsRecording(true);
      console.log("[Mic] Started (MediaStreamTrackProcessor, no AudioContext)");
    } catch (e) {
      console.error("[Mic] Failed:", e);
    }
  }, []);

  const stopMic = useCallback(() => {
    stopRef.current?.();
    stopRef.current = null;
    setIsRecording(false);
    console.log("[Mic] Stopped");
  }, []);

  return { startMic, stopMic, isRecording };
}
