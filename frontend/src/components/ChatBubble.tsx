/**
 * 对话气泡组件
 *
 * 显示对话历史，支持用户和 AI 消息的区分样式。
 */

import React, { useEffect, useRef } from "react";
import { useAgentStore } from "../stores/agent-store";
import type { ChatMessage } from "../stores/agent-store";

const MessageBubble: React.FC<{ msg: ChatMessage }> = ({ msg }) => {
  const isUser = msg.role === "user";
  return (
    <div
      style={{
        ...styles.bubble,
        alignSelf: isUser ? "flex-end" : "flex-start",
        background: isUser ? "rgba(33,150,243,0.8)" : "rgba(255,255,255,0.15)",
        color: isUser ? "#fff" : "#e0e0e0",
      }}
    >
      <div style={styles.role}>{isUser ? "You" : "AI"}</div>
      <div>{msg.text}</div>
    </div>
  );
};

export const ChatBubble: React.FC = () => {
  const messages = useAgentStore((s) => s.messages);
  const streamingText = useAgentStore((s) => s.streamingText);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingText]);

  return (
    <div style={styles.container}>
      <div style={styles.messages}>
        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}
        {streamingText && (
          <div
            style={{
              ...styles.bubble,
              alignSelf: "flex-start",
              background: "rgba(255,255,255,0.15)",
              color: "#e0e0e0",
            }}
          >
            <div style={styles.role}>AI</div>
            <div>
              {streamingText}
              <span style={styles.cursor}>|</span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
};

const styles: Record<string, React.CSSProperties> = {
  container: {
    position: "fixed",
    bottom: 100,
    left: "50%",
    transform: "translateX(-50%)",
    width: "100%",
    maxWidth: 600,
    maxHeight: "40vh",
    overflowY: "auto",
    zIndex: 50,
    pointerEvents: "none",
  },
  messages: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
    padding: "16px",
  },
  bubble: {
    padding: "10px 16px",
    borderRadius: 16,
    maxWidth: "80%",
    backdropFilter: "blur(8px)",
    fontSize: 14,
    lineHeight: 1.5,
    animation: "fadeIn 0.3s ease",
  },
  role: {
    fontSize: 11,
    fontWeight: 600,
    opacity: 0.6,
    marginBottom: 4,
    textTransform: "uppercase",
  },
  cursor: {
    animation: "blink 1s step-end infinite",
    fontWeight: 100,
  },
};
