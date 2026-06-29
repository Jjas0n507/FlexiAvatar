import { BrowserWindow as e, app as t, session as n } from "electron";
import r from "path";
import { spawn as i } from "child_process";
import a from "fs";
//#region ../electron/python-bridge.ts
var o = 8765, s = 5e3, c = 2e3, l = 5, u = 3e3, d = class {
	process = null;
	restartCount = 0;
	healthTimer = null;
	_ready = !1;
	onLog = null;
	onError = null;
	onReady = null;
	onExit = null;
	findPython() {
		let e = r.join(process.env.USERPROFILE || "~", "anaconda3", "envs", "ai-agent", "python.exe");
		return a.existsSync(e) ? e : "python";
	}
	async start() {
		let e = this.findPython(), t = r.join(__dirname, "..", "..", "backend");
		console.log(`[PythonBridge] Starting: ${e}`), console.log(`[PythonBridge] Working dir: ${t}`);
		let n = {
			...process.env,
			PYTHONUNBUFFERED: "1",
			PYTHONPATH: r.join(__dirname, "..", "..")
		};
		return this.process = i(e, [
			"-m",
			"uvicorn",
			"backend.main:app",
			"--host",
			"127.0.0.1",
			"--port",
			String(o),
			"--log-level",
			"info"
		], {
			cwd: r.join(__dirname, "..", ".."),
			env: n,
			stdio: [
				"pipe",
				"pipe",
				"pipe"
			],
			windowsHide: !0
		}), this.process.stdout?.on("data", (e) => {
			let t = e.toString();
			this.onLog?.(t), (t.includes("Uvicorn running") || t.includes("Application startup complete")) && (this._ready = !0, this.restartCount = 0, this.startHealthCheck(), this.onReady?.());
		}), this.process.stderr?.on("data", (e) => {
			let t = e.toString();
			this.onError?.(t), (t.includes("Uvicorn running") || t.includes("Application startup complete")) && (this._ready = !0, this.restartCount = 0, this.startHealthCheck(), this.onReady?.());
		}), this.process.on("exit", (e) => {
			console.log(`[PythonBridge] Process exited with code ${e}`), this._ready = !1, this.stopHealthCheck(), this.onExit?.(e), e !== 0 && e !== null && this.restartCount < l && (this.restartCount++, console.log(`[PythonBridge] Restarting in ${u}ms (attempt ${this.restartCount}/${l})`), setTimeout(() => this.start(), u));
		}), this.process.on("error", (e) => {
			console.error(`[PythonBridge] Failed to start: ${e.message}`), this._ready = !1;
		}), new Promise((e) => {
			let t = setTimeout(() => {
				this._ready || (console.warn("[PythonBridge] Startup timeout"), e(!1));
			}, 15e3), n = () => {
				this._ready ? (clearTimeout(t), e(!0)) : setTimeout(n, 200);
			};
			n();
		});
	}
	async stop() {
		if (this.stopHealthCheck(), this.process) return new Promise((e) => {
			let t = setTimeout(() => {
				this.process && this.process.exitCode === null && (console.warn("[PythonBridge] Force killing..."), this.process.kill("SIGKILL")), e();
			}, 5e3);
			this.process.on("exit", () => {
				clearTimeout(t), e();
			}), this.process.kill("SIGTERM");
		});
	}
	async healthCheck() {
		try {
			let e = new AbortController(), t = setTimeout(() => e.abort(), c), n = await fetch(`http://127.0.0.1:${o}/health`, { signal: e.signal });
			return clearTimeout(t), n.ok;
		} catch {
			return !1;
		}
	}
	startHealthCheck() {
		this.stopHealthCheck(), this.healthTimer = setInterval(async () => {
			!await this.healthCheck() && this._ready && console.warn("[PythonBridge] Health check failed");
		}, s);
	}
	stopHealthCheck() {
		this.healthTimer &&= (clearInterval(this.healthTimer), null);
	}
	get isReady() {
		return this._ready;
	}
}, f = !t.isPackaged, p = null, m = new d();
function h() {
	p = new e({
		width: 900,
		height: 700,
		minWidth: 600,
		minHeight: 400,
		frame: !0,
		transparent: !1,
		titleBarStyle: "default",
		title: "AI 智能助手",
		backgroundColor: "#1a1a2e",
		webPreferences: {
			preload: r.join(__dirname, "preload.js"),
			nodeIntegration: !1,
			contextIsolation: !0
		}
	}), n.defaultSession.setPermissionRequestHandler((e, t, n) => {
		n(t === "media");
	}), f ? (p.loadURL("http://localhost:5173"), p.webContents.openDevTools({ mode: "detach" })) : p.loadFile(r.join(__dirname, "..", "dist", "index.html")), p.on("closed", () => {
		p = null;
	});
}
t.whenReady().then(async () => {
	console.log("[Electron] Starting Python backend..."), await m.start() ? console.log("[Electron] Python backend started") : console.error("[Electron] Failed to start Python backend"), h(), t.on("activate", () => {
		e.getAllWindows().length === 0 && h();
	});
}), t.on("window-all-closed", () => {
	process.platform !== "darwin" && t.quit();
}), t.on("before-quit", async () => {
	console.log("[Electron] Shutting down..."), await m.stop();
}), t.on("web-contents-created", (e, t) => {
	t.setWindowOpenHandler(({ url: e }) => {
		let t = new URL(e);
		return t.hostname === "127.0.0.1" || t.hostname === "localhost" ? { action: "allow" } : { action: "deny" };
	});
});
//#endregion
export {};
