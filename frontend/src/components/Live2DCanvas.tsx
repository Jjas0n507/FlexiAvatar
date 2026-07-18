/**
 * Live2D 渲染画布组件。
 *
 * 使用 live2d-renderer 库加载 Cubism 模型，处理 WebSocket 传来的
 * 表情、动作指令。内置呼吸、自动眨眼、物理模拟。
 *
 * 口型: 库内置 RMS 音量驱动（enableLipsync + inputAudio），
 *       经 registerSpeaker 桥接给 useAudioPlayback 的播放队列。
 */

import React, { useRef, useEffect, useCallback, useState } from "react";
import { Live2DCubismModel } from "live2d-renderer";
import { useAgentStore } from "../stores/agent-store";
import { registerSpeaker, registerExpressionSetter } from "../hooks/useAudioPlayback";
import type { Live2DControlPayload, ModelProfile } from "../types";

// MotionPriority enum 值 (live2d-renderer 导出为 type，运行时用数值)
const MotionPriority = {
  None: 0,
  Idle: 1,
  Normal: 2,
  Force: 3,
} as const;

// ── 配置 ────────────────────────────────────────
// ponytail: CDN WASM 404s, use local copy. JS contains wasm asm.js fallback.
const CUBISM_CORE_PATH = "/live2d/live2dcubismcore.min.js";

// 默认硬编码值（profile 为 null 时的 fallback）
const FALLBACK_MODEL_PATH = "/live2d/有马加奈/有马加奈.model3.json";
const FALLBACK_EMOJI_PARAMS = ["Paramemoji1", "Paramemoji2", "Paramemoji6", "Paramemoji7"];
const FALLBACK_IDLE_EXPRESSIONS = ["neutral", "happy", "thinking", "surprised"];

/** 从 profile 获取模型路径，不存在时 fallback */
function getModelPath(profile: ModelProfile | null): string {
  if (profile) {
    // model3_path 是相对于模型目录的，拼接完整路径
    const dir = profile.model3_path.includes("/")
      ? profile.model3_path.replace(/[^/]+$/, "")
      : "/live2d/有马加奈/";
    return dir + (profile.model3_path.split("/").pop() ?? "有马加奈.model3.json");
  }
  return FALLBACK_MODEL_PATH;
}

// ponytail: live2d-renderer 的 loadCubismCore 只等 script.onload，
// 但 Emscripten WASM 初始化是异步的。需要对 Live2DCubismCore 做轮询。
async function ensureCubismCoreLoaded(src: string): Promise<void> {
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
  // poll for Emscripten async init to complete
  for (let i = 0; i < 100; i++) {
    if (win.Live2DCubismCore) return;
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("Live2DCubismCore not defined after 10s");
}

// ponytail: live2d-renderer 的 setParameter 运行时可用但 .d.ts 未完整声明
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ModelWithSetParam = Live2DCubismModel & {
  setParameter: (name: string, value: number) => void;
};

// ── 辅助：获取可用动作组名 ──────────────────────

function getAvailableMotions(model: Live2DCubismModel): string[] {
  const ids = model.getMotions();
  // 提取分组名: "害羞嘴.motion3.json_0" → "害羞嘴.motion3.json"
  const groups = new Set<string>();
  for (const id of ids) {
    const lastUnderscore = id.lastIndexOf("_");
    if (lastUnderscore > 0) {
      groups.add(id.substring(0, lastUnderscore));
    }
  }
  return [...groups];
}

// ── 组件 ────────────────────────────────────────

const Live2DCanvas: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const modelRef = useRef<Live2DCubismModel | null>(null);
  const animFrameRef = useRef<number>(0);
  const containerRef = useRef<HTMLDivElement>(null);

  const [loadState, setLoadState] = useState<"loading" | "loaded" | "error">("loading");
  const [loadError, setLoadError] = useState<string>("");

  // 缓存可用的动作组名
  const motionGroupsRef = useRef<string[]>([]);

  // ModelProfile（从后端 live2d.profile 消息接收，null 时 fallback 硬编码）
  const profileRef = useRef<ModelProfile | null>(null);

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
    // 初始化时也读取一次
    const initial = useAgentStore.getState().modelProfile;
    if (initial) profileRef.current = initial;
    return unsub;
  }, []);

  // ponytail: 自主表情/动作定时器
  const autoBehaviorTimerRef = useRef<ReturnType<typeof setInterval>>(undefined);

  // ── 模型初始化 ────────────────────────────────

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    let destroyed = false;

    const initModel = async () => {
      try {
        // 先等 CubismCore 脚本加载并完成初始化（Emscripten WASM init 是异步的）
        await ensureCubismCoreLoaded(CUBISM_CORE_PATH);
        console.log("[Live2D] CubismCore ready:", typeof (window as any).Live2DCubismCore);

        // 创建模型实例
        const model = new Live2DCubismModel(canvas, {
          cubismCorePath: CUBISM_CORE_PATH,
          scale: 1.2,
          autoInteraction: false,   // ponytail: 关闭鼠标跟随
          autoAnimate: false,       // 库内置循环用模块级全局 id 存 rAF 句柄，StrictMode
                                    // 双实例下 destroy() 会随机杀错循环 → 自己跑循环
          randomMotion: true,       // ponytail: 随机动作循环
          enablePhysics: true,
          enableEyeblink: true,
          enableBreath: true,
          enableLipsync: true,      // 库内置 RMS 口型（model3.json LipSync 组）
          enableMotion: true,       // ponytail: 启用动作自动循环
          enableExpression: true,   // ponytail: 启用表情系统
          enableMovement: false,    // ponytail: 关闭拖拽驱动头部运动
        });

        // 加载模型
        const modelPath = getModelPath(profileRef.current);
        console.log("[Live2D] Loading model...", modelPath);
        await model.load(modelPath);
        console.log("[Live2D] Model loaded:", modelPath);

        if (destroyed) {
          model.destroy();
          return;
        }

        modelRef.current = model;

        // GPU 诊断：llvmpipe/SwiftShader = 软渲染，就是 FPS 崩的根因
        const gl = canvas.getContext("webgl2") ?? canvas.getContext("webgl");
        const dbg = gl?.getExtension("WEBGL_debug_renderer_info");
        console.log(
          "[Live2D] GL renderer:",
          gl && dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : "unknown",
        );
        canvas.addEventListener("webglcontextlost", () =>
          console.error("[Live2D] WebGL context LOST → 已回退软渲染"),
        );

        // 自己接管渲染循环（autoAnimate:false）：每帧一次 model.update()，
        // 生命周期由 destroyed 标志控制，StrictMode 双挂载安全。FPS 计数顺带。
        const fps = { frames: 0, lastLog: performance.now() };
        const renderLoop = () => {
          if (destroyed) return;
          model.update();
          fps.frames++;
          const now = performance.now();
          if (now - fps.lastLog >= 3000) {
            console.log(`[Live2D] FPS: ${Math.round(fps.frames / ((now - fps.lastLog) / 1000))}`);
            fps.frames = 0;
            fps.lastLog = now;
          }
          animFrameRef.current = requestAnimationFrame(renderLoop);
        };
        renderLoop();

        // ★ 再处理动作 — 读可用分组，不在则跳过
        motionGroupsRef.current = getAvailableMotions(model);
        console.log("[Live2D] Available motions:", motionGroupsRef.current);
        console.log("[Live2D] Available expressions:", model.getExpressions());

        if (motionGroupsRef.current.length > 0) {
          model.startRandomMotion(
            null, // null = 随机分组
            MotionPriority.Idle
          );
          console.log("[Live2D] Started idle motion");
        } else {
          console.log("[Live2D] No motions found, using default pose");
        }

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
      modelRef.current?.destroy();
      modelRef.current = null;
    };
  }, []);

  // ── 画布尺寸自适应 ────────────────────────────

  useEffect(() => {
    const resizeObserver = new ResizeObserver(() => {
      const model = modelRef.current;
      if (!model?.loaded) return;
      model.needsResize = true;
    });

    if (containerRef.current) {
      resizeObserver.observe(containerRef.current);
    }

    return () => resizeObserver.disconnect();
  }, []);

  // ── 动作播放 ──────────────────────────────────

  const playMotion = useCallback(
    (group: string, index: number, priority: number = MotionPriority.Normal) => {
      const model = modelRef.current;
      if (!model?.loaded) return;
      model.stopMotions();
      model.startMotion(group, index, priority);
    },
    []
  );

  // ── 表情切换（优先使用 profile，无 profile 时 fallback 硬编码）──

  const setExpression = useCallback((name: string) => {
    const model = modelRef.current;
    if (!model?.loaded) return;

    const profile = profileRef.current;
    const exprDef = profile?.expressions?.[name];

    if (exprDef) {
      if (exprDef.type === "native" && exprDef.name) {
        // 原生 .exp3.json 表情
        const available = model.getExpressions();
        if (available.includes(exprDef.name)) {
          model.setExpression(exprDef.name);
          return;
        }
        // 原生表情不可用时降级到 params
      }
      if (exprDef.type === "params" && exprDef.params) {
        // 参数直设：先重置 extra 参数
        const m = model as unknown as ModelWithSetParam;
        const extraParams = profile?.parameters?.extra ?? FALLBACK_EMOJI_PARAMS;
        for (const p of extraParams) {
          m.setParameter(p, 0);
        }
        // 设置表情参数
        for (const [key, value] of Object.entries(exprDef.params)) {
          m.setParameter(key, value);
        }
        return;
      }
      // type=native 但 name=null → neutral，只重置 extra
      if (exprDef.type === "native" && !exprDef.name) {
        const m = model as unknown as ModelWithSetParam;
        const extraParams = profile?.parameters?.extra ?? FALLBACK_EMOJI_PARAMS;
        for (const p of extraParams) {
          m.setParameter(p, 0);
        }
        return;
      }
    }

    // ── Fallback: 硬编码表情逻辑（profile 为 null 或表情未定义时）──
    const m = model as unknown as ModelWithSetParam;
    const emojiParams = FALLBACK_EMOJI_PARAMS;
    for (const p of emojiParams) {
      m.setParameter(p, 0);
    }

    switch (name) {
      case "surprised":
        m.setParameter("ParamEyeLOpen", 1.2);
        m.setParameter("ParamEyeROpen", 1.2);
        m.setParameter("ParamBrowLY", 0.5);
        m.setParameter("ParamBrowRY", 0.5);
        break;
      case "happy":
        m.setParameter("ParamEyeLSmile", 0.6);
        m.setParameter("ParamEyeRSmile", 0.6);
        break;
      case "sad":
        m.setParameter("ParamBrowLY", -0.4);
        m.setParameter("ParamBrowRY", -0.4);
        m.setParameter("ParamEyeLSmile", -0.2);
        m.setParameter("ParamEyeRSmile", -0.2);
        break;
      case "thinking":
        m.setParameter("ParamBrowLX", -0.2);
        m.setParameter("ParamBrowRX", 0.2);
        break;
      // neutral: 不做任何操作
    }
  }, []);

  // ── speak/stop 桥（useAudioPlayback 的播放队列 → 库内置 RMS 口型）──
  //
  // ponytail: 音频输出走 <audio>（浏览器媒体线程），不走 WebAudio 输出——
  // 这台 AMD/Linux 机器上运行中的 AudioContext 会把 WebGL 压到 ~10 FPS
  // 且不恢复（f03b6db 时代同一个坑）。AudioContext 永久 suspended，
  // 只用 decodeAudioData 拿采样喂 RMS；播放位置读 el.currentTime（媒体
  // 硬件时钟），与采样消费同源，口型结构上不漂移。

  useEffect(() => {
    if (loadState !== "loaded") return;
    const model = modelRef.current;
    if (!model) return;

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const wc = model.wavController as any;
    const el = new Audio();
    el.preload = "auto";
    let currentUrl: string | null = null;
    let finishCurrent: (() => void) | null = null;

    // 解码不需要 running 状态；保持 suspended 保 FPS
    void model.audioContext?.suspend()?.catch?.(() => { /* ignore */ });

    const clearSamples = () => {
      wc.samples = null;
      wc.rms = 0;
      wc.previousRms = 0;
    };
    const revokeUrl = () => {
      if (currentUrl) {
        URL.revokeObjectURL(currentUrl);
        currentUrl = null;
      }
    };

    // 重写库的 RMS 时钟：播放位置 = <audio> 媒体时钟
    wc.update = () => {
      const samples: Float32Array[] | null = wc.samples;
      if (!samples || samples.length === 0) {
        wc.rms = 0;
        wc.previousRms = 0;
        return;
      }
      if (el.paused) return; // 未开播/已暂停：不消费采样
      const goal = Math.min(
        Math.floor(el.currentTime * wc.sampleRate),
        wc.samplesPerChannel,
      );
      if (goal <= wc.sampleOffset) return;

      let sum = 0;
      for (const ch of samples) {
        for (let i = wc.sampleOffset; i < goal; i++) sum += ch[i] * ch[i];
      }
      const n = (goal - wc.sampleOffset) * samples.length;
      const rms = Math.min(1, Math.sqrt(sum / n) * 5);
      const k = wc.smoothingFactor > 0 ? wc.smoothingFactor : 1;
      wc.rms = wc.previousRms * (1 - k) + rms * k;
      wc.previousRms = wc.rms;
      wc.sampleOffset = goal;

      if (goal >= wc.samplesPerChannel) clearSamples(); // 播完立即闭嘴
    };

    registerSpeaker({
      speak: async (buf: ArrayBuffer, mime: string) => {
        const m = modelRef.current;
        if (!m?.loaded) return;
        // Blob 先建（复制字节），decodeAudioData 会 detach 原 buffer
        const blob = new Blob([buf], { type: mime });
        const decoded = await m.audioContext.decodeAudioData(buf);

        revokeUrl();
        currentUrl = URL.createObjectURL(blob);
        el.src = currentUrl;

        wc.numChannels = decoded.numberOfChannels;
        wc.sampleRate = decoded.sampleRate;
        wc.samplesPerChannel = decoded.length;
        wc.samples = Array.from(
          { length: decoded.numberOfChannels },
          (_, i) => decoded.getChannelData(i),
        );
        wc.sampleOffset = 0;
        wc.rms = 0;
        wc.previousRms = 0;

        await new Promise<void>((resolve) => {
          finishCurrent = resolve;
          el.onended = () => resolve();
          el.onerror = () => resolve();
          el.play().catch((e) => {
            console.error("[Live2D] audio play failed:", e);
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

    return () => {
      registerSpeaker(null);
      registerExpressionSetter(null);
      el.pause();
      clearSamples();
      finishCurrent?.();
      finishCurrent = null;
      revokeUrl();
    };
  }, [loadState, setExpression]);

  // ── 自主行为定时器 ────────────────────────────

  useEffect(() => {
    if (loadState !== "loaded") return;

    const scheduleNext = () => {
      const profile = profileRef.current;
      const idleExprs = profile?.idle?.expression_cycle ?? FALLBACK_IDLE_EXPRESSIONS;
      const [minInterval, maxInterval] = profile?.idle?.expression_interval ?? [5.0, 12.0];
      // ponytail: 使用 profile 的空闲间隔或默认 5-12 秒
      const delay = (minInterval + Math.random() * (maxInterval - minInterval)) * 1000;
      autoBehaviorTimerRef.current = setTimeout(() => {
        const expr = idleExprs[Math.floor(Math.random() * idleExprs.length)];
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
              playMotion(
                control.motion.group,
                control.motion.index,
                control.motion.priority
              );
            }
            break;

          case "interrupt":
            // 音频/口型停止由 useAudioPlayback 的 sessionState 订阅处理
            modelRef.current?.stopMotions();
            setExpression("surprised");
            break;

          case "reset":
            modelRef.current?.stopMotions();
            // 恢复到待机动作
            if (motionGroupsRef.current.length > 0) {
              modelRef.current?.startRandomMotion(null, MotionPriority.Idle);
            }
            break;
        }
      },
      { equalityFn: (a, b) => a === b }
    );

    return unsub;
  }, [playMotion, setExpression]);

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
