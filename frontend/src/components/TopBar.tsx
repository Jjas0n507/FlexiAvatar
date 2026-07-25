/**
 * 顶栏组件 — 合并状态指示器 + 调试面板 + 返回键
 *
 * 左侧：返回键 + 状态圆点 + 状态文字
 * 右侧：调试信息（默认折叠，点击展开）
 */

import React, { useState } from "react";
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

const TopBar: React.FC = () => {
  const [debugOpen, setDebugOpen] = useState(false);
  const setAppPhase = useAgentStore((s) => s.setAppPhase);
  const wsConnected = useAgentStore((s) => s.wsConnected);
  const sessionState = useAgentStore((s) => s.sessionState);
  const appPhase = useAgentStore((s) => s.appPhase);
  const lastError = useAgentStore((s) => s.lastError);
  const availableTools = useAgentStore((s) => s.availableTools);

  const dotColor = wsConnected ? STATE_COLORS[sessionState] : "#f44336";
  const label = wsConnected ? STATE_LABELS[sessionState] : "未连接";

  return (
    <div className="topbar">
      {/* 左侧：返回键 + 状态 */}
      <div className="topbar-left">
        <button
          className="topbar-back-btn"
          onClick={() => setAppPhase("startup")}
          title="返回开始界面"
        >
          ←
        </button>
        <span
          className="topbar-dot"
          style={{
            backgroundColor: dotColor,
            animation:
              sessionState === "listening" || sessionState === "processing"
                ? "pulse 1s infinite"
                : "none",
          }}
        />
        <span className="topbar-label">{label}</span>
        {lastError && (
          <span className="topbar-error" title={lastError}>
            ⚠ {lastError}
          </span>
        )}
      </div>

      {/* 右侧：调试面板 */}
      <div className="topbar-right">
        <button
          className="topbar-debug-toggle"
          onClick={() => setDebugOpen(!debugOpen)}
        >
          {debugOpen ? "收起" : "调试"}
        </button>
      </div>

      {/* 展开的调试信息 */}
      {debugOpen && (
        <div className="topbar-debug-dropdown">
          <div>
            <strong>WebSocket:</strong>{" "}
            <span className={wsConnected ? "status-ok" : "status-err"}>
              {wsConnected ? "已连接" : "未连接"}
            </span>
          </div>
          <div>
            <strong>应用阶段:</strong> {appPhase}
          </div>
          <div>
            <strong>会话状态:</strong> {sessionState}
          </div>
          <div>
            <strong>已加载工具:</strong>{" "}
            {availableTools.length > 0 ? availableTools.join(", ") : "(无)"}
          </div>
        </div>
      )}
    </div>
  );
};

export default TopBar;
