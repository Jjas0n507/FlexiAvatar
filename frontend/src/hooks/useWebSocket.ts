/**
 * WebSocket 连接管理 Hook
 *
 * 在组件挂载时连接后端，卸载时断开。
 * 自动将后端消息分发到 Zustand Store。
 */

import { useEffect, useCallback } from "react";
import { wsClient } from "../services/ws-client";
import { useAgentStore } from "../stores/agent-store";
import type { WSMessage, SessionState, ModelProfile, TTSSpeechPayload } from "../types";

// ponytail: 文本缓冲 — 延迟到首段 TTS 音频到达才显示，避免 SoVITS 高延迟下文字全出而语音未播
let _pendingText = "";
let _textShown = false;
let _pendingLastChunk = false;

export function useWebSocket() {
  const {
    setWsConnected,
    setSessionState,
    appendStreamingText,
    addMessage,
    setCurrentASRText,
    updateToolProgress,
    setLive2DControl,
    setModelProfile,
    setTtsSpeech,
    setLastError,
    setAvailableTools,
  } = useAgentStore();

  useEffect(() => {
    // 注册消息处理器
    const unsubs: (() => void)[] = [];

    // 状态变更
    unsubs.push(
      wsClient.on("state.change", (msg: WSMessage) => {
        const payload = msg.payload as Record<string, unknown>;
        setSessionState(payload.state as SessionState);
        if (payload.tools) {
          setAvailableTools(payload.tools as string[]);
        }
        // 语音播放结束 → 将流式文本转为永久消息
        if (payload.state === "idle" && _pendingLastChunk) {
          const finalText = useAgentStore.getState().streamingText;
          if (finalText) {
            addMessage({ role: "assistant", text: finalText });
            useAgentStore.getState().setStreamingText("");
          }
          _pendingLastChunk = false;
        }
      })
    );

    // ASR 结果
    unsubs.push(
      wsClient.on("asr.result", (msg: WSMessage) => {
        const payload = msg.payload as Record<string, unknown>;
        setCurrentASRText(
          payload.text as string,
          payload.isFinal as boolean
        );
      })
    );

    // LLM 流式输出 — 缓冲到首段 TTS 音频到达再显示，避免文字全出语音未播
    let _flushTimer: ReturnType<typeof setTimeout> | null = null;
    unsubs.push(
      wsClient.on("llm.stream", (msg: WSMessage) => {
        const payload = msg.payload as Record<string, unknown>;
        const text = payload.text as string;
        const isFirstChunk = payload.isFirstChunk as boolean;
        const isLastChunk = payload.isLastChunk as boolean;

        if (isFirstChunk) {
          _pendingText = text;
          _textShown = false;
          _pendingLastChunk = false;
          if (_flushTimer) { clearTimeout(_flushTimer); _flushTimer = null; }
        } else if (!_textShown) {
          _pendingText += text;
        } else {
          appendStreamingText(text);
        }

        if (isLastChunk) {
          if (!_textShown) {
            _pendingLastChunk = true;
            // 兜底：5s 内无音频到达 → 直接显示文本（TTS 可能失败）
            _flushTimer = setTimeout(() => {
              if (!_textShown && _pendingText) {
                useAgentStore.getState().setStreamingText(_pendingText);
                _textShown = true;
                addMessage({ role: "assistant", text: _pendingText });
                useAgentStore.getState().setStreamingText("");
                _pendingLastChunk = false;
              }
            }, 5000);
          } else {
            const finalText = useAgentStore.getState().streamingText;
            addMessage({ role: "assistant", text: finalText });
            useAgentStore.getState().setStreamingText("");
          }
        }
      })
    );

    // 工具进度
    unsubs.push(
      wsClient.on("tool.progress", (msg: WSMessage) => {
        updateToolProgress(msg.payload as unknown as {
          name: string;
          status: "calling" | "running" | "done" | "error";
          params?: Record<string, unknown>;
          result?: string;
          error?: string;
        });
      })
    );

    // Live2D 控制
    unsubs.push(
      wsClient.on("live2d.control", (msg: WSMessage) => {
        setLive2DControl(msg.payload as unknown as Parameters<typeof setLive2DControl>[0]);
      })
    );

    // Live2D ModelProfile (后端连接后发送)
    unsubs.push(
      wsClient.on("live2d.profile", (msg: WSMessage) => {
        const profile = msg.payload as unknown as ModelProfile;
        setModelProfile(profile);
        console.log("[WS] ModelProfile received:", profile.name);
      })
    );

    // TTS audio — 首段到达时 flush 缓冲的 LLM 文本（文字与语音同步，解码/播放延迟自然提供 ~0.2s 领先）
    unsubs.push(
      wsClient.on("tts.audio", (msg: WSMessage) => {
        const payload = msg.payload as unknown as TTSSpeechPayload;
        console.log(`[WS] tts.audio seq=${payload.seq} fmt=${payload.format} b64len=${payload.audio?.length ?? 0}`);

        if (!_textShown && _pendingText) {
          if (_flushTimer) { clearTimeout(_flushTimer); _flushTimer = null; }
          useAgentStore.getState().setStreamingText(_pendingText);
          _textShown = true;
          // 若 LLM 已结束 → 不立即 finalize，等 state→idle（播放完毕）再转消息
        }

        setTtsSpeech(payload);
      })
    );

    // 错误
    unsubs.push(
      wsClient.on("error", (msg: WSMessage) => {
        const payload = msg.payload as Record<string, unknown>;
        setLastError(payload.message as string);
        console.error("[Agent Error]", payload);
      })
    );

    // 连接状态回调
    wsClient.onConnected = () => setWsConnected(true);
    wsClient.onDisconnected = () => setWsConnected(false);

    // 建立连接
    wsClient.connect();

    return () => {
      unsubs.forEach((fn) => fn());
      wsClient.onConnected = null;
      wsClient.onDisconnected = null;
      wsClient.disconnect();
    };
  }, []);

  // 暴露方法
  const sendText = useCallback((text: string) => {
    // 用户文字消息入库，与 ASR 最终结果路径一致（setCurrentASRText isFinal→addMessage）
    useAgentStore.getState().addMessage({ role: "user", text });
    wsClient.sendTextChat(text);
  }, []);

  const sendInterrupt = useCallback(() => {
    wsClient.sendInterrupt();
  }, []);

  // ponytail: 从 store 读取 (reactive)，不是 wsClient.isConnected (非 reactive getter)
  const isConnected = useAgentStore((s) => s.wsConnected);

  return {
    isConnected,
    sendText,
    sendInterrupt,
  };
}
