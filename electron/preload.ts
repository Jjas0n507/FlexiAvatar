/**
 * Electron 预加载脚本
 *
 * 通过 contextBridge 向渲染进程暴露安全的 API。
 */

import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("electronAPI", {
  // 平台信息
  platform: process.platform,

  // Python 后端状态
  getBackendStatus: () => ipcRenderer.invoke("backend:status"),

  // 应用版本
  getAppVersion: () => ipcRenderer.invoke("app:version"),

  // 最小化/关闭
  minimizeWindow: () => ipcRenderer.send("window:minimize"),
  closeWindow: () => ipcRenderer.send("window:close"),

  // 监听主进程消息
  onBackendReady: (callback: () => void) => {
    ipcRenderer.on("backend:ready", callback);
    return () => ipcRenderer.removeListener("backend:ready", callback);
  },
  onBackendError: (callback: (_event: unknown, error: string) => void) => {
    ipcRenderer.on("backend:error", callback);
    return () => ipcRenderer.removeListener("backend:error", callback);
  },
});
