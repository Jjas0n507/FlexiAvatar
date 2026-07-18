/**
 * Live2D 渲染画布组件（pixi-live2d-display + PIXI 6，amadeus 同款栈）。
 *
 * 渲染层由 live2d-renderer 置换而来：其动作系统每次起动作全量重解析
 * motion3.json（实测 motion 90ms/帧 + 每秒几十 MB 分配），多次修补无果。
 *
 * 口型: <audio> 媒体线程播放（本机任何 running AudioContext 都会拖死渲染，
 *       解码用 OfflineAudioContext）+ 解码采样窗口 RMS，经 internalModel 的
 *       beforeModelUpdate 钩子写 LipSync 组参数（动作已应用、核心求值前）。
 */

import React, { useRef, useEffect, useCallback, useState } from "react";
import * as PIXI from "pixi.js";
import { Live2DModel, config as l2dConfig } from "pixi-live2d-display/cubism4";
import { useAgentStore } from "../stores/agent-store";
import { registerSpeaker, registerExpressionSetter } from "../hooks/useAudioPlayback";
import type { Live2DControlPayload, ModelProfile } from "../types";

// pixi-live2d-display 内部引用全局 PIXI（Ticker/utils）
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(window as any).PIXI = PIXI;
l2dConfig.sound = false; // 禁动作自带音效：不开输出流、不与 TTS 口型抢状态

// 与 WS 控制协议一致的数值优先级（同 pixi-live2d-display MotionPriority）
const MotionPriority = {
  None: 0,
  Idle: 1,
  Normal: 2,
  Force: 3,
} as const;

// ── 配置 ────────────────────────────────────────
const CUBISM_CORE_PATH = "/live2d/live2dcubismcore.min.js";

const FALLBACK_MODEL_PATH = "/live2d/有马加奈/有马加奈.model3.json";
const FALLBACK_IDLE_EXPRESSIONS = ["neutral", "happy", "thinking", "surprised"];

// Fallback 表情（无 profile 映射时）：标准参数持久覆写，切换时整体替换
const FALLBACK_EXPRESSION_PARAMS: Record<string, Record<string, number>> = {
  surprised: { ParamEyeLOpen: 1.2, ParamEyeROpen: 1.2, ParamBrowLY: 0.5, ParamBrowRY: 0.5 },
  happy: { ParamEyeLSmile: 0.6, ParamEyeRSmile: 0.6 },
  sad: { ParamBrowLY: -0.4, ParamBrowRY: -0.4, ParamEyeLSmile: -0.2, ParamEyeRSmile: -0.2 },
  thinking: { ParamBrowLX: -0.2, ParamBrowRX: 0.2 },
};

/** 从 profile 获取模型路径，不存在时 fallback */
function getModelPath(profile: ModelProfile | null): string {
  if (profile) {
    const dir = profile.model3_path.includes("/")
      ? profile.model3_path.replace(/[^/]+$/, "")
      : "/live2d/有马加奈/";
    return dir + (profile.model3_path.split("/").pop() ?? "有马加奈.model3.json");
  }
  return FALLBACK_MODEL_PATH;
}

// live2dcubismcore 的 Emscripten 初始化是异步的，轮询等待
async function ensureCubismCoreLoaded(src: string): Promise<void> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const win = window as any;
  if (win.Live2DCubismCore) return;
  if (!document.querySelector(`script[src="${src}"]`)) {
    await new Promise<void>((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = () => resolve();
      s.onerror = () => reject(new Error(`Failed to load ${src}`));
      document.body.appendChild(s);
    });
  }
  for (let i = 0; i < 100; i++) {
    if (win.Live2DCubismCore) return;
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("Live2DCubismCore not defined after 10s");
}

const norm = (s: string) => s.replace(/\.exp3\.json$/, "");

// ── 组件 ────────────────────────────────────────

const Live2DCanvas: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const modelRef = useRef<Live2DModel | null>(null);
  const animFrameRef = useRef<number>(0);

  const [loadState, setLoadState] = useState<"loading" | "loaded" | "error">("loading");
  const [loadError, setLoadError] = useState<string>("");

  const motionGroupsRef = useRef<string[]>([]);
  const profileRef = useRef<ModelProfile | null>(null);
  const autoBehaviorTimerRef = useRef<ReturnType<typeof setInterval>>(undefined);

  // ── 参数写入通道（init effect 装填，beforeModelUpdate 消费）──
  // 注意：pixi 每帧 loadParameters 回滚参数 → 覆写必须每帧重写才可见；
  // 反之，不再写的参数下一帧自动还原（motion/expression 各归其位），
  // 因此不需要"清零"机制 — 清零反而会碾掉原生表情和动作里的 emoji 曲线。
  const setParamRef = useRef<(id: string, v: number, w?: number) => void>(() => {});
  const overridesRef = useRef<Record<string, number>>({}); // 持久参数覆写，每帧重写，整体替换
  const lipSyncIdsRef = useRef<string[]>(["ParamMouthOpenY"]);
  const exprDefsRef = useRef<Array<{ Name: string; File?: string }>>([]);
  const fitRef = useRef<(() => void) | null>(null);

  // 口型状态：bridge 写入，beforeModelUpdate 消费（同一媒体时钟：el.currentTime）
  const mouthRef = useRef<{
    el: HTMLAudioElement | null;
    samples: Float32Array[] | null;
    sampleRate: number;
    perChannel: number;
    offset: number;
    prev: number;
  }>({ el: null, samples: null, sampleRate: 0, perChannel: 0, offset: 0, prev: 0 });

  // 订阅 profile 更新
  useEffect(() => {
    const unsub = useAgentStore.subscribe(
      (state) => state.modelProfile,
      (profile) => {
        if (profile) {
          profileRef.current = profile;
          console.log("[Live2D] Profile updated:", profile.name);
        }
      }
    );
    const initial = useAgentStore.getState().modelProfile;
    if (initial) profileRef.current = initial;
    return unsub;
  }, []);

  // ── 模型初始化 ────────────────────────────────

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    let destroyed = false;
    let app: PIXI.Application | null = null;

    const initModel = async () => {
      try {
        await ensureCubismCoreLoaded(CUBISM_CORE_PATH);
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        console.log("[Live2D] CubismCore ready:", typeof (window as any).Live2DCubismCore);

        app = new PIXI.Application({
          view: canvas,
          backgroundAlpha: 0,
          antialias: true,
          autoDensity: true,
          resolution: window.devicePixelRatio || 1,
          resizeTo: container,
        });

        const modelPath = getModelPath(profileRef.current);
        console.log("[Live2D] Loading model...", modelPath);
        const model = await Live2DModel.from(modelPath, {
          autoInteract: false,
          autoUpdate: false, // 我们自己在 ticker 里驱动 update（时钟自持原则）
        });
        console.log("[Live2D] Model loaded:", modelPath);

        if (destroyed) {
          model.destroy();
          app.destroy(false, { children: true, texture: true, baseTexture: true });
          return;
        }

        modelRef.current = model;
        app.stage.addChild(model);

        // GPU 诊断：llvmpipe/SwiftShader = 软渲染
        const gl = canvas.getContext("webgl2") ?? canvas.getContext("webgl");
        const dbg = gl?.getExtension("WEBGL_debug_renderer_info");
        console.log(
          "[Live2D] GL renderer:",
          gl && dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : "unknown",
        );
        canvas.addEventListener("webglcontextlost", () =>
          console.error("[Live2D] WebGL context LOST"),
        );

        // ── 原始 core 参数通道（绕过 CubismId 句柄，纯字符串索引）──
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const internal = model.internalModel as any;
        const core = internal.coreModel;
        const rawIds: string[] = core.getModel().parameters.ids;
        setParamRef.current = (id, v, w = 1) => {
          const i = rawIds.indexOf(id);
          if (i >= 0) core.setParameterValueByIndex(i, v, w);
        };

        // model3.json 的 LipSync 组 / 表情表 / 动作组
        const groups = (internal.settings?.groups ?? []) as Array<{ Name: string; Ids: string[] }>;
        const lipIds = groups.find((g) => g.Name === "LipSync")?.Ids ?? [];
        lipSyncIdsRef.current = lipIds.length > 0 ? lipIds : ["ParamMouthOpenY"];
        exprDefsRef.current = internal.settings?.expressions ?? [];
        motionGroupsRef.current = Object.keys(internal.settings?.motions ?? {});
        console.log("[Live2D] Available motions:", motionGroupsRef.current);
        console.log("[Live2D] Available expressions:", exprDefsRef.current.map((e) => e.Name));
        console.log("[Live2D] LipSync params:", lipSyncIdsRef.current);

        // ── 参数写入点：动作已应用、coreModel.update 之前 ──
        internal.on("beforeModelUpdate", () => {
          const setP = setParamRef.current;
          for (const [id, v] of Object.entries(overridesRef.current)) setP(id, v);
          // 口型：播放位置 = <audio> 媒体时钟，消费解码采样窗口
          const m = mouthRef.current;
          let rms = 0;
          if (m.samples && m.el && !m.el.paused) {
            const goal = Math.min(Math.floor(m.el.currentTime * m.sampleRate), m.perChannel);
            if (goal > m.offset) {
              let sum = 0;
              for (const ch of m.samples) {
                for (let i = m.offset; i < goal; i++) sum += ch[i] * ch[i];
              }
              const n = (goal - m.offset) * m.samples.length;
              const inst = Math.min(1, Math.sqrt(sum / n) * 5);
              rms = m.prev + (inst - m.prev) * 0.5; // 指数平滑
              m.offset = goal;
              if (goal >= m.perChannel) m.samples = null; // 播完闭嘴
            } else {
              rms = m.prev; // 媒体时钟同刻内保持
            }
          }
          m.prev = rms;
          for (const id of lipSyncIdsRef.current) setP(id, rms);
        });

        // ── 适配容器 ──
        const fit = () => {
          const w = container.clientWidth;
          const h = container.clientHeight;
          if (!w || !h || !internal.height) return;
          const s = (h / internal.height) * 1.2; // 与旧版 scale 1.2 视觉接近
          model.scale.set(s);
          model.anchor.set(0.5, 0.5);
          model.position.set(w / 2, h / 2);
        };
        fitRef.current = fit;
        fit();

        // ── ticker：update + 插桩（FPS | 裸 rAF | update 耗时 | 堆）──
        const fps = { frames: 0, lastLog: performance.now(), updMs: 0 };
        const bare = { frames: 0 };
        const bareLoop = () => {
          if (destroyed) return;
          bare.frames++;
          animFrameRef.current = requestAnimationFrame(bareLoop);
        };
        animFrameRef.current = requestAnimationFrame(bareLoop);

        app.ticker.add(() => {
          if (destroyed || !app) return;
          const t0 = performance.now();
          model.update(app.ticker.deltaMS);
          fps.updMs += performance.now() - t0;
          fps.frames++;
          const now = performance.now();
          if (now - fps.lastLog >= 3000) {
            const secs = (now - fps.lastLog) / 1000;
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const heap = (performance as any).memory?.usedJSHeapSize as number | undefined;
            console.log(
              `[Live2D] FPS: ${Math.round(fps.frames / secs)}` +
                ` | bare rAF: ${Math.round(bare.frames / secs)}` +
                ` | update: ${(fps.updMs / Math.max(1, fps.frames)).toFixed(1)}ms` +
                (heap ? ` | heap: ${Math.round(heap / 1048576)}MB` : ""),
            );
            fps.frames = 0;
            fps.updMs = 0;
            bare.frames = 0;
            fps.lastLog = now;
          }
        });

        // 空闲动作：库内置 idleMotionGroup="Idle" 自动循环，无需手动启动
        setLoadState("loaded");
      } catch (err) {
        console.error("[Live2D] Init error:", err);
        if (!destroyed) {
          setLoadState("error");
          setLoadError(String(err));
        }
      }
    };

    initModel();

    return () => {
      destroyed = true;
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = 0;
      fitRef.current = null;
      modelRef.current = null;
      // children:true 连同 model 一起销毁；false = 不销毁 canvas DOM
      app?.destroy(false, { children: true, texture: true, baseTexture: true });
      app = null;
    };
  }, []);

  // ── 画布尺寸自适应（renderer 由 resizeTo 处理，这里只重排模型）──

  useEffect(() => {
    const resizeObserver = new ResizeObserver(() => fitRef.current?.());
    if (containerRef.current) resizeObserver.observe(containerRef.current);
    return () => resizeObserver.disconnect();
  }, []);

  // ── 动作播放 ──────────────────────────────────

  const playMotion = useCallback(
    (group: string, index: number, priority: number = MotionPriority.Normal) => {
      const model = modelRef.current;
      if (!model) return;
      if (priority >= MotionPriority.Force) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (model.internalModel as any).motionManager.stopAllMotions();
      }
      void model.motion(group, index, priority);
    },
    []
  );

  const stopMotions = useCallback(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (modelRef.current?.internalModel as any)?.motionManager.stopAllMotions();
  }, []);

  // ── 表情切换（优先 profile，无 profile 时 fallback 硬编码）──

  const applyNativeExpression = useCallback((name: string): boolean => {
    const model = modelRef.current;
    if (!model) return false;
    const hit = exprDefsRef.current.find(
      (d) =>
        norm(d.Name) === norm(name) ||
        (d.File ? norm(d.File.split("/").pop() ?? "") === norm(name) : false),
    );
    if (!hit) return false;
    void model.expression(hit.Name);
    return true;
  }, []);

  const resetNativeExpression = useCallback(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (modelRef.current?.internalModel as any)?.motionManager?.expressionManager?.resetExpression?.();
  }, []);

  const setExpression = useCallback((name: string) => {
    const model = modelRef.current;
    if (!model) return;

    const exprDef = profileRef.current?.expressions?.[name];

    if (exprDef) {
      if (exprDef.type === "native" && exprDef.name) {
        if (applyNativeExpression(exprDef.name)) {
          overridesRef.current = {};
          return;
        }
        // 原生不可用时降级到 fallback
      }
      if (exprDef.type === "params" && exprDef.params) {
        resetNativeExpression(); // 之前可能有原生表情挂着
        overridesRef.current = { ...exprDef.params };
        return;
      }
      if (exprDef.type === "native" && !exprDef.name) {
        // neutral：清覆写 + 复位原生表情
        overridesRef.current = {};
        resetNativeExpression();
        return;
      }
    }

    // ── Fallback: 硬编码标准参数覆写（neutral 及未知名 → 全清）──
    resetNativeExpression();
    overridesRef.current = { ...(FALLBACK_EXPRESSION_PARAMS[name] ?? {}) };
  }, [applyNativeExpression, resetNativeExpression]);

  // ── speak/stop 桥（useAudioPlayback 播放队列 → RMS 口型）──
  //
  // 音频输出走 <audio>（媒体线程）；解码用 OfflineAudioContext（纯内存，
  // 永不开输出流）。播放位置与采样消费同源（el.currentTime），结构上不漂移。

  useEffect(() => {
    if (loadState !== "loaded") return;

    const el = new Audio();
    el.preload = "auto";
    const mouth = mouthRef.current; // 稳定模块对象，非 DOM 节点
    mouth.el = el;
    const decodeCtx = new OfflineAudioContext(1, 1, 44100);
    let currentUrl: string | null = null;
    let finishCurrent: (() => void) | null = null;

    const clearSamples = () => {
      mouth.samples = null;
      mouth.offset = 0;
      mouth.prev = 0;
    };
    const revokeUrl = () => {
      if (currentUrl) {
        URL.revokeObjectURL(currentUrl);
        currentUrl = null;
      }
    };

    registerSpeaker({
      speak: async (buf: ArrayBuffer, mime: string) => {
        if (!modelRef.current) return;
        console.log(`[Audio] speak: ${buf.byteLength}B ${mime}`);
        // Blob 先建（复制字节），decodeAudioData 会 detach 原 buffer
        const blob = new Blob([buf], { type: mime });
        let decoded: AudioBuffer;
        try {
          decoded = await decodeCtx.decodeAudioData(buf);
        } catch (e) {
          console.error("[Audio] decode failed:", e);
          throw e; // pump 捕获后跳本段
        }
        console.log(`[Audio] decoded: ${decoded.duration.toFixed(2)}s @${decoded.sampleRate}Hz`);

        revokeUrl();
        currentUrl = URL.createObjectURL(blob);
        el.src = currentUrl;

        const m = mouthRef.current;
        m.sampleRate = decoded.sampleRate;
        m.perChannel = decoded.length;
        m.samples = Array.from({ length: decoded.numberOfChannels }, (_, i) =>
          decoded.getChannelData(i),
        );
        m.offset = 0;
        m.prev = 0;

        await new Promise<void>((resolve) => {
          finishCurrent = resolve;
          el.onended = () => {
            console.log("[Audio] ended");
            resolve();
          };
          el.onerror = () => {
            console.error("[Audio] media error:", el.error?.code, el.error?.message);
            resolve();
          };
          el.play()
            .then(() => console.log("[Audio] playing"))
            .catch((e) => {
              console.error("[Audio] play() rejected:", e);
              resolve();
            });
        });
        finishCurrent = null;
        clearSamples();
        revokeUrl();
      },
      stop: () => {
        el.pause();
        clearSamples();
        finishCurrent?.(); // 解锁泵循环里 pending 的 speak
        finishCurrent = null;
        revokeUrl();
      },
    });
    registerExpressionSetter(setExpression);
    console.log("[Audio] speaker bridge registered");

    return () => {
      registerSpeaker(null);
      registerExpressionSetter(null);
      el.pause();
      clearSamples();
      finishCurrent?.();
      finishCurrent = null;
      revokeUrl();
      mouth.el = null;
    };
  }, [loadState, setExpression]);

  // ── 自主表情定时器 ────────────────────────────

  useEffect(() => {
    if (loadState !== "loaded") return;

    const scheduleNext = () => {
      const profile = profileRef.current;
      const idleExprs = profile?.idle?.expression_cycle ?? FALLBACK_IDLE_EXPRESSIONS;
      const [minInterval, maxInterval] = profile?.idle?.expression_interval ?? [5.0, 12.0];
      const delay = (minInterval + Math.random() * (maxInterval - minInterval)) * 1000;
      autoBehaviorTimerRef.current = setTimeout(() => {
        const expr = idleExprs[Math.floor(Math.random() * idleExprs.length)];
        console.log("[Live2D] idle expression:", expr);
        setExpression(expr);
        scheduleNext();
      }, delay);
    };

    scheduleNext();

    return () => clearTimeout(autoBehaviorTimerRef.current);
  }, [loadState, setExpression]);

  // ── 处理 WebSocket 控制指令 ──────────────────

  const prevControlRef = useRef<Live2DControlPayload | null>(null);

  useEffect(() => {
    const unsub = useAgentStore.subscribe(
      (state) => state.live2dControl,
      (control) => {
        if (!control || control === prevControlRef.current) return;
        prevControlRef.current = control;

        switch (control.command) {
          case "expression":
            if (control.expression?.name) {
              setExpression(control.expression.name);
            }
            break;

          case "motion":
            if (control.motion) {
              playMotion(control.motion.group, control.motion.index, control.motion.priority);
            }
            break;

          case "interrupt":
            // 音频/口型停止由 useAudioPlayback 的 sessionState 订阅处理
            stopMotions();
            setExpression("surprised");
            break;

          case "reset":
            stopMotions(); // 库会自动回到 Idle 组循环
            break;
        }
      },
      { equalityFn: (a, b) => a === b }
    );

    return unsub;
  }, [playMotion, setExpression, stopMotions]);

  // ── 会话状态变化 → Live2D 表情 ────────────────

  const prevStateRef = useRef<string>("idle");

  useEffect(() => {
    const unsub = useAgentStore.subscribe(
      (state) => state.sessionState,
      (state) => {
        if (state === prevStateRef.current) return;
        prevStateRef.current = state;

        if (state === "interrupted") return;

        if (state === "processing") {
          setExpression("thinking");
        }
      }
    );

    return unsub;
  }, [setExpression]);

  // ── 渲染 ──────────────────────────────────────

  return (
    <div ref={containerRef} className="live2d-canvas-container">
      <canvas
        ref={canvasRef}
        className="live2d-canvas"
        style={{ width: "100%", height: "100%" }}
      />
      {/* 加载/错误状态覆盖层 */}
      {loadState !== "loaded" && (
        <div className="live2d-status-overlay">
          {loadState === "loading" && (
            <p className="live2d-status-text">模型加载中...</p>
          )}
          {loadState === "error" && (
            <p className="live2d-status-text live2d-status-error">
              模型加载失败: {loadError}
            </p>
          )}
        </div>
      )}
    </div>
  );
};

export default Live2DCanvas;
