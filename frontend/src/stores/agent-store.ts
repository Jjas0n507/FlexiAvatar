/**
 * 全局状态管理 (Zustand Store)
 *
 * 管理:
 * - 后端连接状态
 * - 会话状态 (idle/listening/processing/speaking/interrupted)
 * - 对话消息列表
 * - Live2D 控制状态
 * - 工具调用状态
 */

import { create } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";
import type {
  SessionState,
  ToolProgressPayload,
  Live2DControlPayload,
} from "../types";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "tool";
  text: string;
  timestamp: number;
  isStreaming?: boolean;
}

export interface AgentState {
  // 连接
  wsConnected: boolean;
  setWsConnected: (connected: boolean) => void;

  // 会话状态
  sessionState: SessionState;
  setSessionState: (state: SessionState, reason?: string) => void;

  // 对话
  messages: ChatMessage[];
  addMessage: (msg: Omit<ChatMessage, "id" | "timestamp">) => void;
  updateLastAssistant: (text: string) => void;
  clearMessages: () => void;

  // 当前流式文本
  streamingText: string;
  setStreamingText: (text: string) => void;
  appendStreamingText: (chunk: string) => void;

  // ASR 结果
  currentASRText: string;
  setCurrentASRText: (text: string, isFinal: boolean) => void;

  // 工具调用
  activeToolCalls: Map<string, ToolProgressPayload>;
  updateToolProgress: (payload: ToolProgressPayload) => void;

  // Live2D
  live2dControl: Live2DControlPayload | null;
  setLive2DControl: (control: Live2DControlPayload | null) => void;

  // 错误
  lastError: string | null;
  setLastError: (error: string | null) => void;

  // 配置
  availableTools: string[];
  setAvailableTools: (tools: string[]) => void;
}

export const useAgentStore = create<AgentState>()(
  subscribeWithSelector((set, get) => ({
  // 连接
  wsConnected: false,
  setWsConnected: (connected) => set({ wsConnected: connected }),

  // 会话状态
  sessionState: "idle",
  setSessionState: (state, _reason) =>
    set({ sessionState: state }),

  // 对话
  messages: [],
  addMessage: (msg) =>
    set((s) => ({
      messages: [
        ...s.messages,
        {
          ...msg,
          id: crypto.randomUUID(),
          timestamp: Date.now(),
        },
      ],
    })),
  updateLastAssistant: (text) =>
    set((s) => {
      const msgs = [...s.messages];
      const last = msgs[msgs.length - 1];
      if (last && last.role === "assistant") {
        msgs[msgs.length - 1] = { ...last, text, isStreaming: false };
      }
      return { messages: msgs };
    }),
  clearMessages: () => set({ messages: [] }),

  // 流式
  streamingText: "",
  setStreamingText: (text) => set({ streamingText: text }),
  appendStreamingText: (chunk) =>
    set((s) => ({ streamingText: s.streamingText + chunk })),

  // ASR
  currentASRText: "",
  setCurrentASRText: (text, isFinal) => {
    set({ currentASRText: text });
    if (isFinal && text.trim()) {
      get().addMessage({ role: "user", text });
      set({ currentASRText: "" });
    }
  },

  // 工具调用
  activeToolCalls: new Map(),
  updateToolProgress: (payload) =>
    set((s) => {
      const updated = new Map(s.activeToolCalls);
      updated.set(payload.name, payload);
      if (payload.status === "done" || payload.status === "error") {
        // 完成后保留 5 秒再移除
        setTimeout(() => {
          set((s2) => {
            const cleaned = new Map(s2.activeToolCalls);
            cleaned.delete(payload.name);
            return { activeToolCalls: cleaned };
          });
        }, 5000);
      }
      return { activeToolCalls: updated };
    }),

  // Live2D
  live2dControl: null,
  setLive2DControl: (control) => set({ live2dControl: control }),

  // 错误
  lastError: null,
  setLastError: (error) => set({ lastError: error }),

  // 配置
  availableTools: [],
  setAvailableTools: (tools) => set({ availableTools: tools }),
  }))
);
