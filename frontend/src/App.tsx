/**
 * 主应用组件
 *
 * 阶段管理：
 *   startup  → StartScreen（未连接 WS，不加载模型）
 *   loading  → 连接 WS + 加载模型，StartScreen 遮罩
 *   ready    → 主界面，自动开麦，VAD 驱动语音交互
 */

import React, { useEffect, useRef } from "react";
import { useWebSocket } from "./hooks/useWebSocket";
import { useAudioPlayback } from "./hooks/useAudioPlayback";
import { useMicCapture } from "./hooks/useMicCapture";
import Live2DCanvas from "./components/Live2DCanvas";
import StartScreen from "./components/StartScreen";
import TopBar from "./components/TopBar";
import ChatPanel from "./components/ChatPanel";
import { useAgentStore } from "./stores/agent-store";
import "./App.css";

const CONNECT_TIMEOUT_MS = 15_000;
const MIN_LOADING_MS = 600;

const App: React.FC = () => {
  const appPhase = useAgentStore((s) => s.appPhase);
  const lastError = useAgentStore((s) => s.lastError);
  const setAppPhase = useAgentStore((s) => s.setAppPhase);
  const setLastError = useAgentStore((s) => s.setLastError);

  const handleStart = () => {
    setLastError(null);
    setAppPhase("loading");
  };

  const handleRetry = () => {
    setLastError(null);
    setAppPhase("loading");
  };

  if (appPhase === "startup") {
    return (
      <div className="app-container">
        <StartScreen
          phase={lastError ? "error" : "startup"}
          error={lastError ?? undefined}
          onStart={handleStart}
          onRetry={handleRetry}
        />
      </div>
    );
  }

  return <MainApp onRetry={handleRetry} />;
};

// ── MainApp（仅在非 startup 阶段挂载）──

const MainApp: React.FC<{ onRetry: () => void }> = ({ onRetry }) => {
  const { isConnected, sendText } = useWebSocket();
  useAudioPlayback();
  const { startMic, isRecording } = useMicCapture();

  const appPhase = useAgentStore((s) => s.appPhase);
  const setAppPhase = useAgentStore((s) => s.setAppPhase);
  const sessionState = useAgentStore((s) => s.sessionState);
  const setLastError = useAgentStore((s) => s.setLastError);

  const connectStartRef = useRef(Date.now());
  const micStartedRef = useRef(false);

  // ── loading → ready 转换 ──────────────────

  useEffect(() => {
    if (appPhase !== "loading") return;
    if (!isConnected) return;
    if (sessionState !== "idle") return;

    const elapsed = Date.now() - connectStartRef.current;
    const remaining = Math.max(0, MIN_LOADING_MS - elapsed);
    const timer = setTimeout(() => setAppPhase("ready"), remaining);
    return () => clearTimeout(timer);
  }, [appPhase, isConnected, sessionState, setAppPhase]);

  // ── 连接超时 ──────────────────────────────

  useEffect(() => {
    if (appPhase !== "loading") return;
    const timer = setTimeout(() => {
      const s = useAgentStore.getState();
      if (s.appPhase === "loading" && !s.wsConnected) {
        setLastError("无法连接到后端，请确认服务已启动");
        setAppPhase("startup");
      }
    }, CONNECT_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [appPhase, setAppPhase, setLastError]);

  // ── ready 后自动开麦 ──────────────────────

  useEffect(() => {
    if (appPhase !== "ready") return;
    if (isRecording) return;
    if (micStartedRef.current) return;
    micStartedRef.current = true;

    startMic().catch(() => {
      console.warn("[App] 麦克风启动失败，仍可使用文字对话");
    });
  }, [appPhase, isRecording, startMic]);

  // ── 渲染 ──────────────────────────────────

  return (
    <div className="app-container">
      <Live2DCanvas />
      <TopBar />
      <ChatPanel onSend={sendText} />

      {/* loading 遮罩 */}
      {appPhase === "loading" && (
        <StartScreen phase="loading" onStart={() => {}} onRetry={onRetry} />
      )}
    </div>
  );
};

export default App;
