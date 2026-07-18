/**
 * Electron 主进程
 *
 * 职责:
 * 1. 创建 BrowserWindow 并加载 React 前端
 * 2. 启动和管理 Python 后端子进程
 * 3. 健康检查 + 自动重启
 * 4. 系统托盘 (可选)
 */

import { app, BrowserWindow, session } from "electron";
import path from "path";
import { fileURLToPath } from "url";
import { PythonBridge } from "./python-bridge";

// ESM 兼容: __dirname 在 ES 模块中不可用
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// 开发模式检测
const isDev = !app.isPackaged;

let mainWindow: BrowserWindow | null = null;
const pythonBridge = new PythonBridge();

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 900,
    height: 700,
    minWidth: 600,
    minHeight: 400,
    frame: true,
    transparent: false,
    titleBarStyle: "default",
    title: "AI 智能助手",
    backgroundColor: "#1a1a2e",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  // 自动授予麦克风权限
  session.defaultSession.setPermissionRequestHandler(
    (_webContents, permission, callback) => {
      if (permission === "media") {
        callback(true);
      } else {
        callback(false);
      }
    }
  );

  if (isDev) {
    // 开发模式：加载 Vite dev server
    mainWindow.loadURL("http://localhost:5173");
    mainWindow.webContents.openDevTools({ mode: "detach" });
  } else {
    // 生产模式：加载打包后的文件
    mainWindow.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

// ── 应用生命周期 ────────────────────────────

app.whenReady().then(async () => {
  // GPU 诊断：等价 chrome://gpu 的特性表 — 看合成/WebGL/栅格化各自是硬件还是软件
  console.log("[GPU]", JSON.stringify(app.getGPUFeatureStatus()));

  // 启动 Python 后端
  console.log("[Electron] Starting Python backend...");
  const started = await pythonBridge.start();
  if (started) {
    console.log("[Electron] Python backend started");
  } else {
    console.error("[Electron] Failed to start Python backend");
  }

  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", async () => {
  console.log("[Electron] Shutting down...");
  await pythonBridge.stop();
});

// ── 安全策略 ────────────────────────────────

app.on("web-contents-created", (_event, contents) => {
  contents.setWindowOpenHandler(({ url }) => {
    // 只允许 WebSocket 连接到本地
    const parsed = new URL(url);
    if (parsed.hostname === "127.0.0.1" || parsed.hostname === "localhost") {
      return { action: "allow" };
    }
    return { action: "deny" };
  });
});
