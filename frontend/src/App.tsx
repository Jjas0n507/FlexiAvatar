/**
 * 主应用组件
 *
 * 渲染 Live2D 画布（占位）、状态指示器、对话气泡、调试控制台。
 */

import React, { useState } from "react";
import { useWebSocket } from "./hooks/useWebSocket";
import { useAudioPlayback } from "./hooks/useAudioPlayback";
import { useMicCapture } from "./hooks/useMicCapture";
import { StatusIndicator } from "./components/StatusIndicator";
import { ChatBubble } from "./components/ChatBubble";
import Live2DCanvas from "./components/Live2DCanvas";
import { useAgentStore } from "./stores/agent-store";
import "./App.css";

const App: React.FC = () => {
  const { isConnected, sendText, sendInterrupt } = useWebSocket();
  useAudioPlayback();
  const { startMic, stopMic, isRecording } = useMicCapture();
  const sessionState = useAgentStore((s) => s.sessionState);
  const availableTools = useAgentStore((s) => s.availableTools);
  const [inputText, setInputText] = useState("");
  const [showDebug, setShowDebug] = useState(true);

  const handleSendText = () => {
    if (!inputText.trim()) return;
    sendText(inputText.trim());
    setInputText("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendText();
    }
  };

  return (
    <div className="app-container">
      {/* Live2D 角色渲染 */}
      <Live2DCanvas />

      {/* 状态指示器 */}
      <StatusIndicator />

      {/* 对话气泡 */}
      <ChatBubble />

      {/* 底部控制栏 */}
      <div className="control-bar">
        {/* 打断按钮 */}
        <button
          className={`interrupt-btn ${
            sessionState === "speaking" || sessionState === "processing"
              ? "active"
              : ""
          }`}
          onClick={sendInterrupt}
          disabled={
            sessionState !== "speaking" && sessionState !== "processing"
          }
          title="打断 AI"
        >
          ⏹ 打断
        </button>

        {/* 麦克风按钮 */}
        <button
          className={`mic-btn ${isRecording ? "active" : ""}`}
          onClick={isRecording ? stopMic : startMic}
          title={isRecording ? "停止录音" : "开始录音"}
        >
          {isRecording ? "🔴 停止" : "🎤 说话"}
        </button>

        {/* 文字输入 (调试用) */}
        <div className="text-input-group">
          <input
            type="text"
            className="text-input"
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入文字对话（调试模式）..."
          />
          <button className="send-btn" onClick={handleSendText}>
            发送
          </button>
        </div>
      </div>

      {/* 调试面板 */}
      {showDebug && (
        <div className="debug-panel">
          <div className="debug-header">
            <span>调试面板</span>
            <button onClick={() => setShowDebug(false)}>收起</button>
          </div>
          <div className="debug-content">
            <div>
              <strong>WebSocket:</strong>{" "}
              <span className={isConnected ? "status-ok" : "status-err"}>
                {isConnected ? "已连接" : "未连接"}
              </span>
            </div>
            <div>
              <strong>会话状态:</strong> {sessionState}
            </div>
            <div>
              <strong>已加载工具:</strong>{" "}
              {availableTools.length > 0
                ? availableTools.join(", ")
                : "(无)"}
            </div>
          </div>
        </div>
      )}

      {/* 显示/隐藏调试面板按钮 */}
      {!showDebug && (
        <button className="debug-toggle" onClick={() => setShowDebug(true)}>
          ☰
        </button>
      )}
    </div>
  );
};

export default App;
