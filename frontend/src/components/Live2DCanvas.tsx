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
import { useLipSyncAudio } from "../hooks/useLipSyncAudio";
import { registerExpressionSetter } from "../hooks/useAudioPlayback";
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

  // ── 口型（公共模块：解码 + <audio> 播放 + RMS 采样窗口）──
  // bridge 在公共模块内注册（带 owner token，切形象时不会被旧实例踢掉）；
  // 这里只在 beforeModelUpdate 里拉取值写参数。
  const lipSync = useLipSyncAudio();

  // owner token：本实例对 speak/expression 桥的所有权标识
  const ownerRef = useRef<symbol>(Symbol("live2d"));

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
          // 口型：与 <audio> 媒体时钟同源，由公共口型模块按采样窗口给出
          const rms = lipSync.getRMS();
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

  // ── 表情桥 + 口型桥（公共口型模块负责解码/播放/RMS）──
  //
  // 音频输出走 <audio>（媒体线程）；解码用 OfflineAudioContext（纯内存，
  // 永不开输出流）。播放位置与采样消费同源（el.currentTime），结构上不漂移。
  // 详见 hooks/useLipSyncAudio.ts。

  useEffect(() => {
    if (loadState !== "loaded") return;
    const owner = ownerRef.current; // 在 effect 内取一次，cleanup 不再读 ref
    registerExpressionSetter(setExpression, owner);
    return () => registerExpressionSetter(null, owner);
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
        // 说话时跳过表情切换：原生表达式会在 beforeModelUpdate 之后覆写口型参数
        if (lipSync.isSpeaking()) {
          scheduleNext();
          return;
        }
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

  // ── 交互：拖拽 / 缩放 / 眼神跟随 ──────────────

  const interactRef = useRef<{
    state: "idle" | "pressing" | "dragging" | "tracking";
    startX: number;
    startY: number;
    modelStartX: number;
    modelStartY: number;
    timer: ReturnType<typeof setTimeout> | null;
  }>({ state: "idle", startX: 0, startY: 0, modelStartX: 0, modelStartY: 0, timer: null });
  // 最近一次 pointer 坐标，用于进入 tracking 时立即 focus（不等 pointermove）
  const lastPointerRef = useRef({ x: 0, y: 0 });

  useEffect(() => {
    if (loadState !== "loaded") return;
    const container = containerRef.current;
    if (!container) return;

    const interact = interactRef.current;
    const DRAG_THRESHOLD = 5;
    const LONG_PRESS_MS = 1200;
    const ZOOM_STEP = 0.05;
    const ZOOM_MIN = 0.5;
    const ZOOM_MAX = 2.5;
    const getModel = () => modelRef.current;

    // 退出眼神跟随：直调 FocusController 回正，绕过 model.focus() 的 atan2 转换
    const exitTracking = () => {
      interact.state = "idle";
      container.style.cursor = "";
      const model = getModel();
      // ponytail: Live2DModel.focus() 内部 atan2/cos/sin 转换期望世界空间像素坐标，
      // 归一化值应直调 focusController.focus()
      if (model) model.internalModel.focusController.focus(0, 0);
    };

    // 判断事件是否发生在 UI 元素上（聊天面板、顶栏等）
    const isOnUI = (e: Event) => {
      const el = e.target as HTMLElement;
      return !!(el.closest(".chat-panel") || el.closest(".topbar") || el.closest(".start-screen"));
    };

    const onPointerDown = (e: PointerEvent) => {
      if (isOnUI(e)) return;
      if (interact.state === "tracking") {
        exitTracking();
        return;
      }
      const model = getModel();
      if (!model) return;
      interact.state = "pressing";
      interact.startX = e.clientX;
      interact.startY = e.clientY;
      interact.modelStartX = model.position.x;
      interact.modelStartY = model.position.y;
      container.setPointerCapture(e.pointerId);
      interact.timer = setTimeout(() => {
        if (interact.state === "pressing") {
          interact.state = "tracking";
          container.style.cursor = "crosshair";
          // 进入 tracking 立即看向当前鼠标位置（不等 pointermove）
          const model = getModel();
          if (model) {
            const rect = container.getBoundingClientRect();
            const p = lastPointerRef.current;
            const nx = ((p.x - rect.left) / rect.width) * 2 - 1;
            const ny = ((p.y - rect.top) / rect.height) * 2 - 1;
            const cx = Math.max(-0.8, Math.min(0.8, nx));
            const cy = Math.max(-0.8, Math.min(0.8, -ny));
            model.internalModel.focusController.focus(cx, cy);
          }
        }
      }, LONG_PRESS_MS);
    };

    const onPointerMove = (e: PointerEvent) => {
      lastPointerRef.current = { x: e.clientX, y: e.clientY };
      if (isOnUI(e)) return;
      const model = getModel();
      if (!model) return;

      if (interact.state === "pressing") {
        const dx = e.clientX - interact.startX;
        const dy = e.clientY - interact.startY;
        if (Math.abs(dx) > DRAG_THRESHOLD || Math.abs(dy) > DRAG_THRESHOLD) {
          if (interact.timer) { clearTimeout(interact.timer); interact.timer = null; }
          interact.state = "dragging";
          container.style.cursor = "grabbing";
        }
      }

      if (interact.state === "dragging") {
        model.position.x = interact.modelStartX + (e.clientX - interact.startX);
        model.position.y = interact.modelStartY + (e.clientY - interact.startY);
      }

      if (interact.state === "tracking") {
        const rect = container.getBoundingClientRect();
        const nx = ((e.clientX - rect.left) / rect.width) * 2 - 1;
        const ny = ((e.clientY - rect.top) / rect.height) * 2 - 1;
        const cx = Math.max(-0.8, Math.min(0.8, nx));
        const cy = Math.max(-0.8, Math.min(0.8, -ny));
        model.internalModel.focusController.focus(cx, cy);
      }
    };

    const onPointerUp = () => {
      if (interact.timer) { clearTimeout(interact.timer); interact.timer = null; }
      if (interact.state === "dragging" || interact.state === "pressing") {
        interact.state = "idle";
        container.style.cursor = "";
      }
    };

    const onWheel = (e: WheelEvent) => {
      if (isOnUI(e)) return;
      const model = getModel();
      if (!model) return;
      e.preventDefault();
      const delta = e.deltaY > 0 ? -ZOOM_STEP : ZOOM_STEP;
      const s = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, model.scale.x + delta));
      model.scale.set(s);
    };

    const onDblClick = (e: MouseEvent) => {
      if (isOnUI(e)) return;
      fitRef.current?.();
      if (interact.state === "tracking") exitTracking();
    };

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && interact.state === "tracking") exitTracking();
    };

    container.addEventListener("pointerdown", onPointerDown);
    container.addEventListener("pointermove", onPointerMove);
    container.addEventListener("pointerup", onPointerUp);
    container.addEventListener("pointercancel", onPointerUp);
    container.addEventListener("wheel", onWheel, { passive: false });
    container.addEventListener("dblclick", onDblClick);
    window.addEventListener("keydown", onKeyDown);

    return () => {
      if (interact.timer) { clearTimeout(interact.timer); interact.timer = null; }
      container.removeEventListener("pointerdown", onPointerDown);
      container.removeEventListener("pointermove", onPointerMove);
      container.removeEventListener("pointerup", onPointerUp);
      container.removeEventListener("pointercancel", onPointerUp);
      container.removeEventListener("wheel", onWheel);
      container.removeEventListener("dblclick", onDblClick);
      window.removeEventListener("keydown", onKeyDown);
      container.style.cursor = "";
    };
  }, [loadState]);

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
