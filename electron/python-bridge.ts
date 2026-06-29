/**
 * Python 子进程管理
 *
 * 职责:
 * - 启动 Python 后端子进程 (uvicorn)
 * - 健康检查轮询
 * - 异常退出时自动重启
 * - 优雅关闭
 */

import { spawn, ChildProcess } from "child_process";
import path from "path";
import fs from "fs";

const BACKEND_PORT = 8765;
const HEALTH_CHECK_INTERVAL_MS = 5000;
const HEALTH_CHECK_TIMEOUT_MS = 2000;
const MAX_RESTART_COUNT = 5;
const RESTART_DELAY_MS = 3000;

export class PythonBridge {
  private process: ChildProcess | null = null;
  private restartCount = 0;
  private healthTimer: ReturnType<typeof setInterval> | null = null;
  private _ready = false;

  // 回调
  onLog: ((message: string) => void) | null = null;
  onError: ((message: string) => void) | null = null;
  onReady: (() => void) | null = null;
  onExit: ((code: number | null) => void) | null = null;

  /**
   * 查找 Python 可执行文件路径
   * 优先级: conda env > 系统 python
   */
  private findPython(): string {
    // 尝试 conda 环境中的 python
    const condaEnvPath = path.join(
      process.env.USERPROFILE || "~",
      "anaconda3",
      "envs",
      "ai-agent",
      "python.exe"
    );
    if (fs.existsSync(condaEnvPath)) {
      return condaEnvPath;
    }

    // 回退到系统 python
    return "python";
  }

  /**
   * 启动 Python 后端
   */
  async start(): Promise<boolean> {
    const pythonPath = this.findPython();
    const backendDir = path.join(__dirname, "..", "..", "backend");

    console.log(`[PythonBridge] Starting: ${pythonPath}`);
    console.log(`[PythonBridge] Working dir: ${backendDir}`);

    // 设置环境变量
    const env = {
      ...process.env,
      PYTHONUNBUFFERED: "1",
      PYTHONPATH: path.join(__dirname, "..", ".."),
    };

    this.process = spawn(
      pythonPath,
      [
        "-m", "uvicorn",
        "backend.main:app",
        "--host", "127.0.0.1",
        "--port", String(BACKEND_PORT),
        "--log-level", "info",
      ],
      {
        cwd: path.join(__dirname, "..", ".."),
        env,
        stdio: ["pipe", "pipe", "pipe"],
        windowsHide: true,
      }
    );

    // 监控 stdout
    this.process.stdout?.on("data", (data: Buffer) => {
      const text = data.toString();
      this.onLog?.(text);
      // 检测启动完成
      if (text.includes("Uvicorn running") || text.includes("Application startup complete")) {
        this._ready = true;
        this.restartCount = 0;
        this.startHealthCheck();
        this.onReady?.();
      }
    });

    // 监控 stderr
    this.process.stderr?.on("data", (data: Buffer) => {
      const text = data.toString();
      this.onError?.(text);
      // uvicorn 把日志打到 stderr
      if (text.includes("Uvicorn running") || text.includes("Application startup complete")) {
        this._ready = true;
        this.restartCount = 0;
        this.startHealthCheck();
        this.onReady?.();
      }
    });

    // 退出处理
    this.process.on("exit", (code) => {
      console.log(`[PythonBridge] Process exited with code ${code}`);
      this._ready = false;
      this.stopHealthCheck();
      this.onExit?.(code);

      // 非正常退出时尝试重启
      if (code !== 0 && code !== null && this.restartCount < MAX_RESTART_COUNT) {
        this.restartCount++;
        console.log(
          `[PythonBridge] Restarting in ${RESTART_DELAY_MS}ms (attempt ${this.restartCount}/${MAX_RESTART_COUNT})`
        );
        setTimeout(() => this.start(), RESTART_DELAY_MS);
      }
    });

    this.process.on("error", (err) => {
      console.error(`[PythonBridge] Failed to start: ${err.message}`);
      this._ready = false;
    });

    // 等待启动完成或超时
    return new Promise((resolve) => {
      const timeout = setTimeout(() => {
        if (!this._ready) {
          console.warn("[PythonBridge] Startup timeout");
          resolve(false);
        }
      }, 15000);

      const checkReady = () => {
        if (this._ready) {
          clearTimeout(timeout);
          resolve(true);
        } else {
          setTimeout(checkReady, 200);
        }
      };
      checkReady();
    });
  }

  /**
   * 停止 Python 后端
   */
  async stop(): Promise<void> {
    this.stopHealthCheck();

    if (!this.process) return;

    return new Promise((resolve) => {
      const forceKillTimeout = setTimeout(() => {
        if (this.process && this.process.exitCode === null) {
          console.warn("[PythonBridge] Force killing...");
          this.process.kill("SIGKILL");
        }
        resolve();
      }, 5000);

      this.process!.on("exit", () => {
        clearTimeout(forceKillTimeout);
        resolve();
      });

      // 发送 SIGTERM
      this.process!.kill("SIGTERM");
    });
  }

  /**
   * 健康检查
   */
  async healthCheck(): Promise<boolean> {
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), HEALTH_CHECK_TIMEOUT_MS);

      const response = await fetch(`http://127.0.0.1:${BACKEND_PORT}/health`, {
        signal: controller.signal,
      });
      clearTimeout(timeout);
      return response.ok;
    } catch {
      return false;
    }
  }

  private startHealthCheck(): void {
    this.stopHealthCheck();
    this.healthTimer = setInterval(async () => {
      const healthy = await this.healthCheck();
      if (!healthy && this._ready) {
        console.warn("[PythonBridge] Health check failed");
      }
    }, HEALTH_CHECK_INTERVAL_MS);
  }

  private stopHealthCheck(): void {
    if (this.healthTimer) {
      clearInterval(this.healthTimer);
      this.healthTimer = null;
    }
  }

  get isReady(): boolean {
    return this._ready;
  }
}
