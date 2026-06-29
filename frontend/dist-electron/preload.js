import { contextBridge as e, ipcRenderer as t } from "electron";
//#region ../electron/preload.ts
e.exposeInMainWorld("electronAPI", {
	platform: process.platform,
	getBackendStatus: () => t.invoke("backend:status"),
	getAppVersion: () => t.invoke("app:version"),
	minimizeWindow: () => t.send("window:minimize"),
	closeWindow: () => t.send("window:close"),
	onBackendReady: (e) => (t.on("backend:ready", e), () => t.removeListener("backend:ready", e)),
	onBackendError: (e) => (t.on("backend:error", e), () => t.removeListener("backend:error", e))
});
//#endregion
export {};
