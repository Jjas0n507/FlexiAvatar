/**
 * 状态指示器组件
 *
 * 显示当前会话状态和 WebSocket 连接状态。
 */

import React from "react";
import { useAgentStore } from "../stores/agent-store";
import type { SessionState } from "../types";

const STATE_LABELS: Record<SessionState, string> = {
  idle: "空闲",
  listening: "正在听...",
  processing: "思考中...",
  speaking: "说话中...",
  interrupted: "已打断",
};

const STATE_COLORS: Record<SessionState, string> = {
  idle: "#888",
  listening: "#4caf50",
  processing: "#ff9800",
  speaking: "#2196f3",
  interrupted: "#f44336",
};

export const StatusIndicator: React.FC = () => {
  const wsConnected = useAgentStore((s) => s.wsConnected);
  const sessionState = useAgentStore((s) => s.sessionState);
  const lastError = useAgentStore((s) => s.lastError);

  const dotColor = wsConnected ? STATE_COLORS[sessionState] : "#f44336";
  const label = wsConnected ? STATE_LABELS[sessionState] : "未连接";

  return (
    <div style={styles.container}>
      <div style={styles.indicator}>
        <span
          style={{
            ...styles.dot,
            backgroundColor: dotColor,
            animation:
              sessionState === "listening" || sessionState === "processing"
                ? "pulse 1s infinite"
                : "none",
          }}
        />
        <span style={styles.label}>{label}</span>
      </div>
      {lastError && (
        <div style={styles.error}>
          {lastError}
          <button
            style={styles.dismissBtn}
            onClick={() => useAgentStore.getState().setLastError(null)}
          >
            x
          </button>
        </div>
      )}
    </div>
  );
};

const styles: Record<string, React.CSSProperties> = {
  container: {
    position: "fixed",
    top: 16,
    left: 16,
    zIndex: 100,
    display: "flex",
    flexDirection: "column",
    gap: 8,
  },
  indicator: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "8px 16px",
    background: "rgba(0,0,0,0.6)",
    borderRadius: 20,
    backdropFilter: "blur(8px)",
  },
  dot: {
    width: 10,
    height: 10,
    borderRadius: "50%",
    display: "inline-block",
  },
  label: {
    color: "#fff",
    fontSize: 14,
    fontWeight: 500,
  },
  error: {
    padding: "8px 16px",
    background: "rgba(244,67,54,0.8)",
    borderRadius: 8,
    color: "#fff",
    fontSize: 13,
    display: "flex",
    alignItems: "center",
    gap: 8,
  },
  dismissBtn: {
    border: "none",
    background: "transparent",
    color: "#fff",
    cursor: "pointer",
    fontSize: 16,
  },
};
