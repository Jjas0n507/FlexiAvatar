/**
 * 麦克风采集 Hook。
 *
 * 使用 getUserMedia + ScriptProcessorNode 采集音频，转为 Int16 PCM
 * base64 后通过 WebSocket 发送 audio.chunk 消息给后端。
 *
 * ponytail: 用 ScriptProcessor (废弃但简单)，不写 AudioWorklet。
 *           16kHz mono 足够 VAD + ASR，bufferSize=512 匹配 VAD 要求。
 */

import { useRef, useCallback, useState } from "react";
import { wsClient } from "../services/ws-client";

export function useMicCapture() {
  const [isRecording, setIsRecording] = useState(false);
  const ctxRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const startMic = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      streamRef.current = stream;

      const ctx = new AudioContext({ sampleRate: 16000 });
      ctxRef.current = ctx;

      const source = ctx.createMediaStreamSource(stream);
      // ponytail: createScriptProcessor deprecated but works everywhere
      const processor = ctx.createScriptProcessor(512, 1, 1);

      processor.onaudioprocess = (e) => {
        if (!wsClient.isConnected) return;
        // Float32Array → Int16Array
        const floatSamples = e.inputBuffer.getChannelData(0);
        const int16 = new Int16Array(floatSamples.length);
        for (let i = 0; i < floatSamples.length; i++) {
          const s = Math.max(-1, Math.min(1, floatSamples[i]));
          int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
        // Int16Array → Uint8Array → binary string → base64
        const bytes = new Uint8Array(int16.buffer);
        let binary = "";
        for (let i = 0; i < bytes.length; i++) {
          binary += String.fromCharCode(bytes[i]);
        }
        const b64 = btoa(binary);
        wsClient.send("audio.chunk", { data: b64 });
      };

      source.connect(processor);
      processor.connect(ctx.destination); // 连接 destination 避免静音，但不输出到扬声器
      ctx.destination.channelCount = 1;   // mono 输出

      setIsRecording(true);
      console.log("[Mic] Started");
    } catch (e) {
      console.error("[Mic] Failed:", e);
    }
  }, []);

  const stopMic = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    ctxRef.current?.close();
    ctxRef.current = null;
    setIsRecording(false);
    console.log("[Mic] Stopped");
  }, []);

  return { startMic, stopMic, isRecording };
}
