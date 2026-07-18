/**
 * WebSocket 客户端封装
 *
 * 职责：
 * - 与 Python 后端建立 WebSocket 连接
 * - 自动重连
 * - 消息分发 (按 type 路由到不同的 handler)
 * - 心跳保持
 */

import type { WSMessage } from "../types";

type MessageHandler = (msg: WSMessage) => void;

const DEFAULT_URL = "ws://127.0.0.1:8765/ws";
const RECONNECT_DELAY_MS = 3000;
const MAX_RECONNECT_DELAY_MS = 30000;
const HEARTBEAT_INTERVAL_MS = 10000;

export class WSClient {
  private ws: WebSocket | null = null;
  private url: string;
  private handlers: Map<string, Set<MessageHandler>> = new Map();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private currentReconnectDelay: number;
  private _isConnected = false;
  private _intentionalClose = false;

  // 回调
  onConnected: (() => void) | null = null;
  onDisconnected: (() => void) | null = null;
  onError: ((error: Event) => void) | null = null;

  constructor(url: string = DEFAULT_URL) {
    this.url = url;
    this.currentReconnectDelay = RECONNECT_DELAY_MS;
  }

  // ── 连接管理 ──────────────────────────────

  connect(): void {
    // OPEN/CONNECTING/CLOSING 一律不重建：重复 connect（如 StrictMode 双挂载）
    // 曾造成孤儿 socket —— 它的 handler 继续喂消息（能收），但 this.ws 指向
    // 别处或 null（不能发），playback.done 等上行全部静默丢失。
    if (this.ws && this.ws.readyState !== WebSocket.CLOSED) return;
    this._intentionalClose = false;

    let sock: WebSocket;
    try {
      sock = new WebSocket(this.url);
    } catch (e) {
      console.error("[WS] Failed to create WebSocket:", e);
      this.scheduleReconnect();
      return;
    }
    this.ws = sock;

    // 所有回调带身份守卫：this.ws 已易主的旧 socket 事件一律忽略/自闭
    sock.onopen = () => {
      if (this.ws !== sock) {
        sock.close();
        return;
      }
      console.log("[WS] Connected");
      this._isConnected = true;
      this.currentReconnectDelay = RECONNECT_DELAY_MS;
      this.clearReconnectTimer(); // 清掉断线期间遗留的重连定时器
      this.startHeartbeat();
      this.onConnected?.();
    };

    sock.onclose = (event) => {
      if (this.ws !== sock) return;
      console.log(`[WS] Disconnected (code: ${event.code})`);
      this.ws = null;
      this._isConnected = false;
      this.stopHeartbeat();
      this.onDisconnected?.();
      if (!this._intentionalClose) {
        this.scheduleReconnect();
      }
    };

    sock.onerror = (event) => {
      if (this.ws !== sock) return;
      console.error("[WS] Error:", event);
      this.onError?.(event);
    };

    sock.onmessage = (event) => {
      if (this.ws !== sock) return;
      try {
        const msg: WSMessage = JSON.parse(event.data as string);
        this.dispatch(msg);
      } catch (e) {
        console.error("[WS] Failed to parse message:", e);
      }
    };
  }

  disconnect(): void {
    this._intentionalClose = true;
    this.stopHeartbeat();
    this.clearReconnectTimer();
    const sock = this.ws;
    this.ws = null; // 先易主再 close，旧 socket 的回调被身份守卫忽略
    sock?.close();
    this._isConnected = false;
  }

  get isConnected(): boolean {
    return this._isConnected;
  }

  // ── 消息发送 ──────────────────────────────

  send(type: string, payload: Record<string, unknown> = {}): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn("[WS] Cannot send, not connected");
      return false;
    }
    const msg: WSMessage = {
      type,
      id: crypto.randomUUID(),
      timestamp: Date.now(),
      payload,
    };
    this.ws.send(JSON.stringify(msg));
    return true;
  }

  sendPing(): void {
    this.send("ping");
  }

  sendTextChat(text: string): void {
    this.send("chat.text", { text });
  }

  sendInterrupt(): void {
    this.send("user.interrupt");
  }

  sendPlaybackDone(): void {
    this.send("playback.done");
  }

  // ── 消息订阅 ──────────────────────────────

  on(type: string, handler: MessageHandler): () => void {
    if (!this.handlers.has(type)) {
      this.handlers.set(type, new Set());
    }
    this.handlers.get(type)!.add(handler);

    // 返回取消订阅函数
    return () => {
      this.handlers.get(type)?.delete(handler);
    };
  }

  /**
   * 订阅多种类型的消息（便捷方法）
   */
  onTypes(types: string[], handler: MessageHandler): () => void {
    const unsubs = types.map((t) => this.on(t, handler));
    return () => unsubs.forEach((fn) => fn());
  }

  private dispatch(msg: WSMessage): void {
    const typeHandlers = this.handlers.get(msg.type);
    if (typeHandlers) {
      typeHandlers.forEach((handler) => {
        try {
          handler(msg);
        } catch (e) {
          console.error(`[WS] Handler error for ${msg.type}:`, e);
        }
      });
    }

    // 总是分发给 '*' 通配符处理器
    const wildcardHandlers = this.handlers.get("*");
    if (wildcardHandlers) {
      wildcardHandlers.forEach((handler) => {
        try {
          handler(msg);
        } catch (e) {
          console.error("[WS] Wildcard handler error:", e);
        }
      });
    }
  }

  // ── 心跳 ──────────────────────────────────

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      this.sendPing();
    }, HEARTBEAT_INTERVAL_MS);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  // ── 重连 ──────────────────────────────────

  private scheduleReconnect(): void {
    this.clearReconnectTimer();
    console.log(`[WS] Reconnecting in ${this.currentReconnectDelay}ms...`);
    this.reconnectTimer = setTimeout(() => {
      this.connect();
      // 指数退避
      this.currentReconnectDelay = Math.min(
        this.currentReconnectDelay * 1.5,
        MAX_RECONNECT_DELAY_MS
      );
    }, this.currentReconnectDelay);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }
}

// 全局单例
export const wsClient = new WSClient();

// dev 排查口: 暴露到全局便于 devtools/CDP 驱动（打包版不含）
if (import.meta.env.DEV) {
  (globalThis as unknown as Record<string, unknown>).__wsClient = wsClient;
}
