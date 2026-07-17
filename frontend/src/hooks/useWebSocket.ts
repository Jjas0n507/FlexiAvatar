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

    // LLM 流式输出
    unsubs.push(
      wsClient.on("llm.stream", (msg: WSMessage) => {
        const payload = msg.payload as Record<string, unknown>;
        const text = payload.text as string;
        const isFirstChunk = payload.isFirstChunk as boolean;
        const isLastChunk = payload.isLastChunk as boolean;

        if (isFirstChunk) {
          // 开始新的 assistant 消息
          useAgentStore.getState().setStreamingText(text);
        } else {
          appendStreamingText(text);
        }

        if (isLastChunk) {
          // 完成：将流式文本转为消息
          const finalText = useAgentStore.getState().streamingText;
          addMessage({ role: "assistant", text: finalText });
          useAgentStore.getState().setStreamingText("");
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

    // TTS speech (合并后的 audio + timeline)
    unsubs.push(
      wsClient.on("tts.speech", (msg: WSMessage) => {
        const payload = msg.payload as unknown as TTSSpeechPayload;
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
