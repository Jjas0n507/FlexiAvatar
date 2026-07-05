/**
 * TTS 音频播放 Hook。
 *
 * 监听 WebSocket 的 tts.audio 消息，将 base64 WAV 解码为 Blob 并播放。
 * ponytail: 用原生 Audio API，不加音频队列/淡入淡出，需要时再加。
 */

import { useEffect, useRef } from "react";
import { wsClient } from "../services/ws-client";

export function useAudioPlayback() {
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    const unsub = wsClient.on("tts.audio", (msg) => {
      const pl = msg.payload as Record<string, unknown>;
      const audioB64 = pl.audio as string;
      if (!audioB64) return;

      // 停止前一个正在播放的音频
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }

      try {
        // base64 → binary → WAV Blob
        const binary = atob(audioB64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
          bytes[i] = binary.charCodeAt(i);
        }
        const blob = new Blob([bytes], { type: "audio/wav" });
        const url = URL.createObjectURL(blob);

        const audio = new Audio(url);
        audioRef.current = audio;

        audio.onended = () => {
          URL.revokeObjectURL(url);
          audioRef.current = null;
        };
        audio.onerror = () => {
          URL.revokeObjectURL(url);
          audioRef.current = null;
        };

        audio.play().catch((e) => console.warn("[Audio] playback failed:", e));
      } catch (e) {
        console.error("[Audio] decode failed:", e);
      }
    });

    return () => {
      unsub();
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
    };
  }, []);
}
