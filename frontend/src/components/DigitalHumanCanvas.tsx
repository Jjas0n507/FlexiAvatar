/**
 * 数字人渲染画布（Three.js）。
 *
 * 范围（docs/digital-human-avatar-plan.md §4 Stage 5）：
 *   GLB 加载 → morph 权重表 → RMS 口型 → 情绪表情(lerp 平滑) → 眨眼 →
 *   拖拽/缩放 → 打断停止 → 资源释放
 *
 * 设计约束（均为实测结论，勿凭直觉改）：
 * 1. **只消费 profile 解析出的「最终 morph 权重表」**：type:"blendshapes" 与
 *    type:"morph" 两类模型走同一条代码路径 —— 这是后续换素材不改代码的关键。
 * 2. **morph 名一律取自 profile，代码零硬编码、零命名猜测**：实测 facecap 用
 *    `browDown_L`，ReadyPlayerMe 用 `browDownLeft`，命名不统一。
 * 3. **morph 缺失必须降级不崩**：找不到就走 warn + 跳过该通道；没有嘴部 morph 的
 *    模型（RobotExpressive）用 `mouth_open: {add: 名字, amount: x}` 发声代理。
 * 4. owner token 归属自己的音频桥，切形象时不会被旧实例踢掉。
 * 5. key 由 AvatarCanvas 用形象 id 指定 → 切换即重建，旧的完整 dispose。
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { KTX2Loader } from "three/examples/jsm/loaders/KTX2Loader.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";
import { useAgentStore } from "../stores/agent-store";
import { useLipSyncAudio } from "../hooks/useLipSyncAudio";
import { registerExpressionSetter } from "../hooks/useAudioPlayback";
import type { DigitalHumanProfile, AvatarExpression } from "../types";

// ── 参数 ────────────────────────────────────────

const MORPH_LERP = 0.2;          // 每帧逼近系数（表情平滑，顺带还掉 Live2D 的技术债）
const BLINK_CLOSE_MS = 70;       // 闭合用时
const BLINK_OPEN_MS = 120;       // 张开用时（快闭慢开）
const DRAG_ROTATE_MAX_X = 0.6;   // 俯仰限幅（弧度）

/** 会话状态 → 情绪（与 Live2D 路径语义一致） */
const STATE_EXPRESSION: Record<string, string> = {
  processing: "thinking",
  interrupted: "surprised",
};

/** 表情定义 → 最终权重表（两类 schema 归一） */
function resolveExpression(def: AvatarExpression | undefined): Record<string, number> {
  if (!def) return {};
  if (def.type === "morph") {
    return def.name ? { [def.name]: 1 } : {};
  }
  return { ...(def.params ?? {}) };
}

/** 口型通道：morph = 直接驱动权重；add = 发声时代理叠加整脸 morph */
function resolveMouth(profile: DigitalHumanProfile): Record<string, number> {
  const m = profile.morphs?.mouth_open;
  if (!m) return {};
  if (m.kind === "add") {
    // 权重由 amount 缩放后按 RMS 线性施加
    return { [m.name]: m.amount ?? 0.35 };
  }
  return { [m.name]: 1 };
}

// ── 组件 ────────────────────────────────────────

interface DigitalHumanCanvasProps {
  profile: DigitalHumanProfile;
}

const DigitalHumanCanvas: React.FC<DigitalHumanCanvasProps> = ({ profile }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const hostRef = useRef<HTMLDivElement>(null); // canvas 宿主：渲染器每次用**新建**的 canvas
  const ownerRef = useRef<symbol>(Symbol("digital-human"));

  const [loadState, setLoadState] = useState<"loading" | "loaded" | "error">("loading");
  const [loadError, setLoadError] = useState("");

  const lipSync = useLipSyncAudio(profile.lip_sync?.gain, profile.lip_sync?.smoothing);
  const sessionState = useAgentStore((s) => s.sessionState);

  // ── 解析 profile（memo：只在形象变化时重算）────────
  const mouthGain = useMemo(() => resolveMouth(profile), [profile]);
  const expressionTable = useMemo(() => {
    const table: Record<string, Record<string, number>> = {};
    for (const [name, def] of Object.entries(profile.expressions ?? {})) {
      table[name] = resolveExpression(def);
    }
    return table;
  }, [profile]);

  // ── 渲染期可变状态（避免 effect 依赖爆炸）────────
  const rigRef = useRef<{
    mesh: THREE.SkinnedMesh | THREE.Mesh;
    index: Record<string, number>;
  } | null>(null);
  const currentRef = useRef<Record<string, number>>({});      // 当前显示值（逐帧 lerp 到这里）
  const targetRef = useRef<Record<string, number>>({});       // 目标值
  const faceRef = useRef<Record<string, number>>({});         // 表情通道目标
  const blinkRef = useRef<Record<string, number>>({});        // 眨眼通道目标
  const applyTargetsRef = useRef<() => void>(() => {});
  const rootRef = useRef<THREE.Object3D | null>(null);
  const rigRefForFrame = rigRef;

  // ── 合成目标值：表情 + 口型 + 眨眼 ──────────────
  // 分通道保存、合成时叠加，避免「眨眼定时器把表情/口型覆盖掉」。
  useEffect(() => {
    applyTargetsRef.current = () => {
      const merged: Record<string, number> = { ...faceRef.current };
      const rms = lipSync.getRMS();
      for (const [name, base] of Object.entries(mouthGain)) {
        merged[name] = (merged[name] ?? 0) + base * rms;
      }
      for (const [name, v] of Object.entries(blinkRef.current)) {
        merged[name] = Math.max(merged[name] ?? 0, v);
      }
      targetRef.current = merged;
    };
  }, [lipSync, mouthGain]);

  // ── 表情设置（注册到播放泵 + 会话状态驱动）────────
  const setExpression = useCallback(
    (name: string) => {
      const def = expressionTable[name];
      if (!def) {
        if (name !== "neutral") {
          console.warn(`[DigitalHuman] profile 没有情绪 "${name}"，回退 neutral`);
        }
        faceRef.current = {};
        return;
      }
      faceRef.current = { ...def };
    },
    [expressionTable],
  );

  // ── 模型加载 ────────────────────────────────────
  useEffect(() => {
    const container = containerRef.current;
    const host = hostRef.current;
    if (!container || !host) return;

    let disposed = false;

    // 每次实例化都用**新建**的 canvas，不复用 DOM 节点：
    // 应用开着 <StrictMode>（挂载 → 清理 → 再挂载），而 React 会复用同一个
    // canvas 节点；上一次 cleanup 的 forceContextLoss() 会让该节点的上下文
    // 永久失效，第二次 new WebGLRenderer 就拿到 null →
    // "Cannot read properties of null (reading 'precision')"（实测踩到）。
    while (host.firstChild) host.removeChild(host.firstChild);
    const canvas = document.createElement("canvas");
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    canvas.style.display = "block";
    host.appendChild(canvas);

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        canvas,
        antialias: true,
        alpha: true,
      });
    } catch (e) {
      console.error("[DigitalHuman] WebGL 初始化失败:", e);
      setLoadState("error");
      setLoadError(`WebGL 初始化失败: ${e instanceof Error ? e.message : String(e)}`);
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setClearColor(0x000000, 0);

    const scene = new THREE.Scene();
    const cam = profile.camera ?? {};
    const camera = new THREE.PerspectiveCamera(cam.fov ?? 30, 1, 0.01, 100);
    const camPos = new THREE.Vector3(...(cam.position ?? [0, 1.55, 0.65]));
    const camTarget = new THREE.Vector3(...(cam.target ?? [0, 1.5, 0]));
    camera.position.copy(camPos);
    camera.lookAt(camTarget);

    // 光照：Headlight + 补光，保证没有环境贴图时也不至于死黑
    const key = new THREE.DirectionalLight(0xffffff, 2.0);
    key.position.set(0.6, 1.4, 1.2);
    scene.add(key);
    scene.add(new THREE.AmbientLight(0xffffff, 1.1));

    const fit = () => {
      const w = container.clientWidth || 1;
      const h = container.clientHeight || 1;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    fit();

    // 压缩资产支持：真实素材常用 KTX2 贴图 / meshopt 几何压缩
    // （占位用的 facecap.glb 同时用了 KTX2 + meshopt + 量化，实测必须接解码器）。
    // 解码器文件由 scripts/fetch-placeholder-avatars.sh 放到 public/decoders/。
    const loader = new GLTFLoader();
    const ktx2 = new KTX2Loader()
      .setTranscoderPath("/decoders/basis/")
      .detectSupport(renderer);
    loader.setKTX2Loader(ktx2);
    loader.setMeshoptDecoder(MeshoptDecoder);

    const modelUrl = "/" + String(profile.model_path).replace(/^\/+/, "");

    loader
      .loadAsync(modelUrl)
      .then((gltf) => {
        if (disposed) return;

        const root = gltf.scene;
        rootRef.current = root;
        scene.add(root);

        // ── 找 morph 宿主：遍历所有 mesh，取「profile 命中最多」的那个 ──
        // 不做命名猜测（RPM 是 Wolf3D_Head，facecap 是无名 mesh）。
        const wanted = new Set<string>([
          ...Object.keys(mouthGain),
          ...(profile.morphs?.blink_left ? [profile.morphs.blink_left] : []),
          ...(profile.morphs?.blink_right ? [profile.morphs.blink_right] : []),
          ...Object.values(expressionTable).flatMap((t) => Object.keys(t)),
        ]);

        let best: THREE.Mesh | THREE.SkinnedMesh | null = null;
        let bestDict: Record<string, number> = {};
        let bestHits = -1;
        root.traverse((obj) => {
          const mesh = obj as THREE.Mesh | THREE.SkinnedMesh;
          const dict = (mesh as THREE.Mesh).morphTargetDictionary;
          if (!dict) return;
          const hits = Object.keys(dict).filter((k) => wanted.has(k)).length;
          if (hits > bestHits) {
            best = mesh;
            bestDict = dict;
            bestHits = hits;
          }
        });

        if (!best || bestHits <= 0) {
          const names = Object.keys(bestDict);
          throw new Error(
            `模型里找不到 profile 声明的任何 morph（模型共有 ${names.length} 个：` +
              `${names.slice(0, 6).join("/") || "无"}）`,
          );
        }

        rigRef.current = { mesh: best, index: bestDict };

        // dev 排查口（与 __wsClient / __agentStore 同一约定，打包版不含）：
        // 暴露 morph 索引与当前权重，便于 CDP 直接验证口型/表情是否真的在动。
        if (import.meta.env.DEV) {
          (globalThis as unknown as Record<string, unknown>).__digitalHuman = {
            meshName: (best as THREE.Mesh).name || "(匿名)",
            index: bestDict,
            influences: () => {
              const inf = (best as THREE.Mesh).morphTargetInfluences;
              if (!inf) return {};
              const out: Record<string, number> = {};
              for (const [k, i] of Object.entries(bestDict)) {
                if (inf[i] !== undefined && Math.abs(inf[i]) > 1e-4) out[k] = inf[i];
              }
              return out;
            },
          };
        }

        // ── 缺失通道降级（不崩）──
        const missing: string[] = [];
        if (!(profile.morphs?.blink_left && bestDict[profile.morphs.blink_left])) {
          missing.push("眨眼(左)");
        }
        if (!(profile.morphs?.blink_right && bestDict[profile.morphs.blink_right])) {
          missing.push("眨眼(右)");
        }
        for (const [name, table] of Object.entries(expressionTable)) {
          const absent = Object.keys(table).filter((k) => !(k in bestDict));
          if (absent.length) missing.push(`${name}:${absent.join("+")}`);
        }
        if (missing.length) {
          console.warn(`[DigitalHuman] 以下 morph 在模型中不存在，已跳过：${missing.join(", ")}`);
        }
        const morphCount = Object.keys(bestDict).length;
        console.log(
          `[DigitalHuman] 已加载 ${profile.name}｜morph ${morphCount} 个｜` +
            `口型 ${Object.keys(mouthGain).join("/") || "无"}｜情绪 ${Object.keys(expressionTable).join("/")}`,
        );

        // ── 自动取景（模型尺度未知，按包围盒适配）──
        const box = new THREE.Box3().setFromObject(root);
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        const maxAxis = Math.max(size.x, size.y, size.z) || 1;
        const dist = maxAxis / (2 * Math.tan((camera.fov * Math.PI) / 360)) * 1.35;
        root.position.sub(new THREE.Vector3(center.x, center.y, center.z));
        camera.position.set(0, size.y * 0.06, dist);
        camera.lookAt(0, 0, 0);
        console.log(
          `[DigitalHuman] 包围盒 ${size.x.toFixed(2)}x${size.y.toFixed(2)}x${size.z.toFixed(2)} → 相机距离 ${dist.toFixed(2)}`,
        );

        setLoadState("loaded");
      })
      .catch((e: unknown) => {
        if (disposed) return;
        console.error("[DigitalHuman] 加载失败:", e);
        setLoadState("error");
        setLoadError(e instanceof Error ? e.message : String(e));
      });

    // ── 渲染循环 ────────────────────────────────────
    let raf = 0;
    const clock = new THREE.Clock();
    let blinkT = 0;
    let nextBlinkAt = 2 + Math.random() * 3;

    const frame = () => {
      if (disposed) return;
      raf = requestAnimationFrame(frame);
      const dt = clock.getDelta();
      const time = clock.elapsedTime;

      applyTargetsRef.current();

      const rig = rigRefForFrame.current;
      if (rig) {
        const influences = rig.mesh.morphTargetInfluences;
        const dict = rig.index;
        const current = currentRef.current;
        const target = targetRef.current;

        // 目标里已消失的 morph：向 0 收敛，收敛完就删（避免无限增长）
        for (const key of Object.keys(current)) {
          if (!(key in target)) {
            const v = current[key] + (0 - current[key]) * MORPH_LERP;
            if (v < 0.001) delete current[key];
            else current[key] = v;
          }
        }
        for (const [key, goal] of Object.entries(target)) {
          const idx = dict[key];
          if (idx === undefined) continue;
          const cur = current[key] ?? 0;
          current[key] = cur + (goal - cur) * MORPH_LERP;
        }
        if (influences) {
          influences.fill(0);
          for (const [key, v] of Object.entries(current)) {
            const idx = dict[key];
            if (idx !== undefined) influences[idx] = v;
          }
        }
      }

      // ── 眨眼（快闭慢开包络）──
      const bl = profile.morphs?.blink_left;
      const br = profile.morphs?.blink_right;
      if (bl || br) {
        blinkT += dt * 1000;
        const next = blinkRef.current;
        if (nextBlinkAt <= 0) {
          // 不处于眨眼过程中 → 抽下一次
          const [lo, hi] = profile.idle?.blink_interval ?? [2.5, 6.0];
          nextBlinkAt = (lo + Math.random() * (hi - lo)) * 1000;
        }
        nextBlinkAt -= dt * 1000;
        let v = 0;
        if (blinkT < BLINK_CLOSE_MS) v = blinkT / BLINK_CLOSE_MS;
        else if (blinkT < BLINK_CLOSE_MS + BLINK_OPEN_MS) {
          v = 1 - (blinkT - BLINK_CLOSE_MS) / BLINK_OPEN_MS;
        } else {
          blinkT = 0;
        }
        if (v === 0 && nextBlinkAt > 0) {
          delete next[bl ?? ""];
          delete next[br ?? ""];
        } else {
          if (bl) next[bl] = v;
          if (br) next[br] = v;
        }
      }

      // 轻微呼吸（无骨骼动画时的"活着"感）
      const root = rootRef.current;
      if (root) root.rotation.z = Math.sin(time * 0.8) * 0.006;

      renderer.render(scene, camera);
    };
    frame();

    const onResize = () => fit();
    const ro = new ResizeObserver(onResize);
    ro.observe(container);

    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      ro.disconnect();
      rigRef.current = null;
      rootRef.current = null;
      currentRef.current = {};
      targetRef.current = {};
      // 释放 GPU 资源：切换形象时必须彻底（否则 WebGL 上下文泄漏）
      scene.traverse((obj) => {
        const mesh = obj as THREE.Mesh;
        mesh.geometry?.dispose?.();
        const mat = mesh.material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
        else mat?.dispose?.();
      });
      ktx2.dispose();
      renderer.dispose();
      // canvas 是本实例私有的，可以安全地强制释放上下文（避免 GPU 上下文泄漏）
      renderer.forceContextLoss();
      canvas.remove();
      console.log("[DigitalHuman] 渲染器已释放");
    };
    // profile/mouthGain/expressionTable 变化即重建（key 已是形象 id，等价于换形象）
  }, [profile, mouthGain, expressionTable]);

  // ── 表情：注册到播放泵 + 会话状态驱动 ────────────
  useEffect(() => {
    if (loadState !== "loaded") return;
    const owner = ownerRef.current;
    registerExpressionSetter(setExpression, owner);
    return () => registerExpressionSetter(null, owner);
  }, [loadState, setExpression]);

  useEffect(() => {
    setExpression(STATE_EXPRESSION[sessionState] ?? "neutral");
  }, [sessionState, setExpression]);

  // ── 交互：拖拽旋转 / 滚轮缩放 ───────────────────
  useEffect(() => {
    const container = containerRef.current;
    if (loadState !== "loaded" || !container) return;

    let dragging = false;
    let lastX = 0;
    let lastY = 0;

    const isOnUI = (e: Event) => {
      const el = e.target as HTMLElement;
      return !!(el.closest?.(".chat-panel") || el.closest?.(".topbar") || el.closest?.(".start-screen"));
    };

    const onDown = (e: PointerEvent) => {
      if (isOnUI(e)) return;
      dragging = true;
      lastX = e.clientX;
      lastY = e.clientY;
      container.setPointerCapture(e.pointerId);
      container.style.cursor = "grabbing";
    };
    const onMove = (e: PointerEvent) => {
      if (!dragging) return;
      const root = rootRef.current;
      if (!root) return;
      const dx = e.clientX - lastX;
      const dy = e.clientY - lastY;
      lastX = e.clientX;
      lastY = e.clientY;
      root.rotation.y += dx * 0.01;
      root.rotation.x = Math.max(
        -DRAG_ROTATE_MAX_X,
        Math.min(DRAG_ROTATE_MAX_X, root.rotation.x + dy * 0.01),
      );
    };
    const onUp = () => {
      dragging = false;
      container.style.cursor = "";
    };
    const onWheel = (e: WheelEvent) => {
      if (isOnUI(e)) return;
      e.preventDefault();
      const root = rootRef.current;
      if (!root) return;
      const s = Math.max(0.4, Math.min(3, root.scale.x * (e.deltaY > 0 ? 0.94 : 1.06)));
      root.scale.setScalar(s);
    };

    container.addEventListener("pointerdown", onDown);
    container.addEventListener("pointermove", onMove);
    container.addEventListener("pointerup", onUp);
    container.addEventListener("pointercancel", onUp);
    container.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      container.removeEventListener("pointerdown", onDown);
      container.removeEventListener("pointermove", onMove);
      container.removeEventListener("pointerup", onUp);
      container.removeEventListener("pointercancel", onUp);
      container.removeEventListener("wheel", onWheel);
      container.style.cursor = "";
    };
  }, [loadState]);

  // ── 渲染 ────────────────────────────────────────
  return (
    <div ref={containerRef} className="live2d-canvas-container" data-avatar="digital-human">
      {/* canvas 由渲染器实例自建（见上方注释：不能复用 DOM 节点） */}
      <div ref={hostRef} className="live2d-canvas" />
      {loadState !== "loaded" && (
        <div className="live2d-status-overlay">
          {loadState === "loading" && <p className="live2d-status-text">模型加载中...</p>}
          {loadState === "error" && (
            <p className="live2d-status-text live2d-status-error">模型加载失败: {loadError}</p>
          )}
        </div>
      )}
    </div>
  );
};

export default DigitalHumanCanvas;
