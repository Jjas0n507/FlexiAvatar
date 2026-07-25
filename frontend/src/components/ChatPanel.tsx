/**
 * 聊天面板组件 — 左侧透明浮动面板
 *
 * 组合对话历史 + 文本输入框 + 发送键。
 * 滚轮在消息区域内翻动历史，不影响模型缩放。
 */

import React, { useState, useRef, useEffect } from "react";
import { useAgentStore } from "../stores/agent-store";
import type { ChatMessage } from "../stores/agent-store";

interface ChatPanelProps {
  onSend: (text: string) => void;
}

// ── 单条消息气泡 ──────────────────────────────

const MessageBubble: React.FC<{ msg: ChatMessage }> = ({ msg }) => {
  const isUser = msg.role === "user";
  return (
    <div
      className={`chat-bubble ${isUser ? "chat-bubble-user" : "chat-bubble-ai"}`}
    >
      <div className="chat-bubble-role">{isUser ? "You" : "AI"}</div>
      <div>{msg.text}</div>
    </div>
  );
};

// ── 面板组件 ──────────────────────────────────

const ChatPanel: React.FC<ChatPanelProps> = ({ onSend }) => {
  const messages = useAgentStore((s) => s.messages);
  const streamingText = useAgentStore((s) => s.streamingText);
  const [inputText, setInputText] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingText]);

  const handleSend = () => {
    if (!inputText.trim()) return;
    onSend(inputText.trim());
    setInputText("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="chat-panel">
      {/* 消息列表 */}
      <div className="chat-messages">
        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}
        {streamingText && (
          <div className="chat-bubble chat-bubble-ai">
            <div className="chat-bubble-role">AI</div>
            <div>
              {streamingText}
              <span className="chat-cursor">|</span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* 输入区 */}
      <div className="chat-input-row">
        <input
          type="text"
          className="chat-input"
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入文字对话..."
        />
        <button className="chat-send-btn" onClick={handleSend}>
          发送
        </button>
      </div>
    </div>
  );
};

export default ChatPanel;
