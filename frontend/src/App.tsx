/**
 * 主应用组件
 *
 * 阶段管理：
 *   startup  → StartScreen（未连接 WS，不加载模型）
 *   picking  → AvatarPicker（连接 WS + 拉形象清单 + 用户选择）
 *   loading  → 连接 WS + 加载模型，StartScreen 遮罩
 *   ready    → 主界面，自动开麦，VAD 驱动语音交互
 *
 * WebSocket 连接由 App 单点持有（见下方注释），阶段切换不再重连。
 */

import React, { useEffect, useRef } from "react";
import { useWebSocket } from "./hooks/useWebSocket";
import { useAudioPlayback } from "./hooks/useAudioPlayback";
import { useMicCapture } from "./hooks/useMicCapture";
import AvatarCanvas from "./components/AvatarCanvas";
import AvatarPicker from "./components/AvatarPicker";
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

  // WebSocket 连接在这里**唯一持有**：此前 picking / main 各挂一次，
  // 阶段切换时前者的 cleanup 会 disconnect、后者再 connect —— 每次切页面
  // 都断连重连一次（后端日志可见连接/断开成对刷屏，且重连窗口内上行会丢）。
  const { sendText } = useWebSocket();

  const handleStart = () => {
    setLastError(null);
    setAppPhase("picking");
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

  if (appPhase === "picking") {
    return (
      <div className="app-container">
        <AvatarPicker
          onSelected={() => setAppPhase("loading")}
          onBack={() => setAppPhase("startup")}
        />
      </div>
    );
  }

  return <MainApp onRetry={handleRetry} sendText={sendText} />;
};

// ── MainApp（仅在非 startup 阶段挂载）──

const MainApp: React.FC<{ onRetry: () => void; sendText: (text: string) => void }> = ({
  onRetry,
  sendText,
}) => {
  const isConnected = useAgentStore((s) => s.wsConnected);
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
      <AvatarCanvas />
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
