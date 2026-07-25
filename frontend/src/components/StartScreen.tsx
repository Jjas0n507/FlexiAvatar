/**
 * 开始界面组件
 *
 * 三种状态：startup（开始按钮）/ loading（加载中）/ error（错误重试）
 * 未来可扩展模型选择、设置面板等。
 */

import React from "react";
import type { AppPhase } from "../stores/agent-store";

interface StartScreenProps {
  phase: AppPhase | "error";
  error?: string;
  onStart: () => void;
  onRetry: () => void;
}

const StartScreen: React.FC<StartScreenProps> = ({
  phase,
  error,
  onStart,
  onRetry,
}) => {
  return (
    <div className="start-screen">
      <div className="start-card">
        <h1 className="start-title">FlexiAvatar</h1>
        <p className="start-subtitle">你的 AI 虚拟伴侣</p>

        {/* TODO: 未来可在此添加模型选择 / 设置面板 */}

        {phase === "startup" && (
          <button className="start-btn" onClick={onStart}>
            开始对话
          </button>
        )}

        {phase === "loading" && (
          <>
            <div className="start-spinner" />
            <p className="start-status">正在加载模型...</p>
          </>
        )}

        {phase === "error" && (
          <>
            <p className="start-error">{error ?? "连接失败"}</p>
            <button className="start-btn" onClick={onRetry}>
              重试
            </button>
          </>
        )}
      </div>
    </div>
  );
};

export default StartScreen;
