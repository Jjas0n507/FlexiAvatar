/**
 * 公共「音频解码 + 播放 + RMS 口型采样」模块。
 *
 * 从 Live2DCanvas 的 speak 桥抽出，供所有渲染器复用（Live2D / 数字人）。
 *
 * 设计要点（都是踩过的坑，勿随意改）：
 * - 音频输出走 <audio>（媒体线程）：本机任何 running AudioContext 都会拖死渲染，
 *   所以解码只用 OfflineAudioContext（纯内存，永不开输出流）。
 * - 播放位置与采样消费同源（el.currentTime）→ 口型结构上不失步。
 * - 看门狗：onended 偶发丢失会永久卡死播放泵（后续段全不播 = 听感截断）。
 *   读播放头判定：还在推进就按剩余时长顺延（绝不切尾音），播完/停滞才放行。
 * - 管线预热：Chromium 首次 <audio> 播放要初始化系统音频设备，期间 currentTime
 *   正常推进但无声音 → 先播 50ms 静音 WAV，消除首句前几个字无声。
 *
 * 对外只暴露「拉取式」接口 getRMS()，让两种消费时钟都能用：
 * - Live2D：在 beforeModelUpdate 钩子里拉（动作已应用、core 求值前）
 * - 数字人：在 requestAnimationFrame 里拉
 */

import { useEffect, useRef, useState } from "react";
import { registerSpeaker, bridgeState } from "./useAudioPlayback";
import type { SpeakerBridge } from "./useAudioPlayback";

export interface LipSyncController {
  /** 当前口型开合度 0..1（已含 gain 与平滑）；未播放时恒为 0 */
  getRMS: () => number;
  /** 是否正在播放 TTS 音频（空闲行为用它让位） */
  isSpeaking: () => boolean;
  /** 归零闭嘴（播完 / 打断 / 切换形象） */
  reset: () => void;
}

export interface LipSyncOptions {
  /** RMS 增益（不同模型的嘴部敏感度不同，必须按模型标定） */
  gain?: number;
  /** 指数平滑系数 0..1，越大越跟手 */
  smoothing?: number;
}

const DEFAULT_GAIN = 5.0;
const DEFAULT_SMOOTHING = 0.5;

// ── 播放器 ────────────────────────────────────────

class LipSyncPlayer {
  private readonly audio: HTMLAudioElement;
  private readonly decodeCtx: OfflineAudioContext;
  private gain: number;
  private smoothing: number;

  // 口型采样状态：与 el.currentTime 同源
  private samples: Float32Array[] | null = null;
  private sampleRate = 0;
  private perChannel = 0;
  private offset = 0;
  private prev = 0;

  private currentUrl: string | null = null;
  private finishCurrent: (() => void) | null = null;

  constructor(opts: LipSyncOptions = {}) {
    this.gain = opts.gain ?? DEFAULT_GAIN;
    this.smoothing = opts.smoothing ?? DEFAULT_SMOOTHING;
    this.decodeCtx = new OfflineAudioContext(1, 1, 44100);

    this.audio = new Audio();
    this.audio.preload = "auto";
    this.prime();
  }

  /** 预热音频输出管线（见文件头注释） */
  private prime(): void {
    void (async () => {
      try {
        const sr = 24000, ms = 50, n = Math.floor((sr * ms) / 1000), ds = n * 2;
        const buf = new ArrayBuffer(44 + ds);
        const v = new DataView(buf);
        const w = (o: number, s: string) => {
          for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i));
        };
        w(0, "RIFF"); v.setUint32(4, 36 + ds, true); w(8, "WAVE");
        w(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true);
        v.setUint16(22, 1, true); v.setUint32(24, sr, true); v.setUint32(28, sr * 2, true);
        v.setUint16(32, 2, true); v.setUint16(34, 16, true);
        w(36, "data"); v.setUint32(40, ds, true);
        const url = URL.createObjectURL(new Blob([buf], { type: "audio/wav" }));
        this.audio.src = url;
        await this.audio.play();
        this.audio.pause();
        this.audio.currentTime = 0;
        URL.revokeObjectURL(url);
        console.log("[Audio] pipeline primed");
      } catch {
        /* 静默失败，不影响后续播放 */
      }
    })();
  }

  private clearSamples(): void {
    this.samples = null;
    this.offset = 0;
    this.prev = 0;
  }

  private revokeUrl(): void {
    if (this.currentUrl) {
      URL.revokeObjectURL(this.currentUrl);
      this.currentUrl = null;
    }
  }

  /**
   * 拉取当前口型值。消费 [offset, now) 的采样窗口并推进 offset，
   * 因此每帧调用一次；同一媒体时钟刻内重复调用保持上一帧值。
   */
  getRMS(): number {
    if (import.meta.env.DEV) {
      const probe = (globalThis as unknown as { __lipSyncProbe?: { current: number | null } })
        .__lipSyncProbe;
      if (probe && probe.current !== null) return probe.current;
    }
    let rms = 0;
    if (this.samples && !this.audio.paused) {
      const goal = Math.min(
        Math.floor(this.audio.currentTime * this.sampleRate),
        this.perChannel,
      );
      if (goal > this.offset) {
        let sum = 0;
        for (const ch of this.samples) {
          for (let i = this.offset; i < goal; i++) sum += ch[i] * ch[i];
        }
        const n = (goal - this.offset) * this.samples.length;
        const inst = Math.min(1, Math.sqrt(sum / n) * this.gain);
        rms = this.prev + (inst - this.prev) * this.smoothing; // 指数平滑
        this.offset = goal;
        if (goal >= this.perChannel) this.samples = null; // 播完闭嘴
      } else {
        rms = this.prev; // 媒体时钟同刻内保持
      }
    }
    this.prev = rms;
    return rms;
  }

  reset(): void {
    this.clearSamples();
  }

  /** 正在播放 TTS 音频？（与旧实现 `samples && !el.paused` 同语义） */
  isSpeaking(): boolean {
    return this.samples !== null && !this.audio.paused;
  }

  /** 按当前形象的 profile 热更新标定参数（模型可后于 hook 创建到达） */
  applyOptions(gain?: number, smoothing?: number): void {
    if (typeof gain === "number" && gain > 0) this.gain = gain;
    if (typeof smoothing === "number" && smoothing > 0 && smoothing <= 1) {
      this.smoothing = smoothing;
    }
  }

  /** 播放一段音频；resolve = 播放结束（或被 stop 打断） */
  async speak(buf: ArrayBuffer, mime: string): Promise<void> {
    // Blob 先建（复制字节），decodeAudioData 会 detach 原 buffer
    const blob = new Blob([buf], { type: mime });
    let decoded: AudioBuffer;
    try {
      decoded = await this.decodeCtx.decodeAudioData(buf);
    } catch (e) {
      console.error("[Audio] decode failed:", e);
      throw e; // pump 捕获后跳本段
    }
    console.log(`[Audio] decoded: ${decoded.duration.toFixed(2)}s @${decoded.sampleRate}Hz`);

    this.revokeUrl();
    this.currentUrl = URL.createObjectURL(blob);
    this.audio.src = this.currentUrl;

    this.sampleRate = decoded.sampleRate;
    this.perChannel = decoded.length;
    this.samples = Array.from({ length: decoded.numberOfChannels }, (_, i) =>
      decoded.getChannelData(i),
    );
    this.offset = 0;
    this.prev = 0;

    await new Promise<void>((resolve) => {
      let done = false;
      let watchdog: ReturnType<typeof setTimeout>;
      const finish = (reason: string) => {
        if (done) return;
        done = true;
        clearTimeout(watchdog);
        if (reason === "ended") console.log("[Audio] ended");
        else console.warn(`[Audio] finish: ${reason}`);
        resolve();
      };
      // 看门狗: onended 偶发丢失会永久卡死泵（后续段全部不播 = 听感截断）。
      // 读播放头判定：还在正常推进就按剩余时长顺延（绝不切尾音），播完/停滞才放行。
      const checkEnd = () => {
        if (done) return;
        const remain = decoded.duration - this.audio.currentTime;
        if (!this.audio.paused && this.audio.currentTime > 0 && isFinite(remain) && remain > 0.05) {
          watchdog = setTimeout(checkEnd, Math.max(remain * 1000 + 300, 250));
        } else {
          finish(
            `watchdog (onended lost? t=${this.audio.currentTime.toFixed(2)}/${decoded.duration.toFixed(2)})`,
          );
        }
      };
      watchdog = setTimeout(checkEnd, decoded.duration * 1000 + 750);
      this.finishCurrent = () => finish("stopped");
      this.audio.onended = () => finish("ended");
      this.audio.onerror = () =>
        finish(`media error ${this.audio.error?.code ?? "?"} ${this.audio.error?.message ?? ""}`);
      this.audio
        .play()
        .then(() => console.log("[Audio] playing"))
        .catch((e) => finish(`play() rejected: ${e}`));
    });
    this.finishCurrent = null;
    this.clearSamples();
    this.revokeUrl();
  }

  /** 立即停止：停音频 + 清采样 + 解锁 pending speak */
  stop(): void {
    this.audio.pause();
    this.clearSamples();
    this.finishCurrent?.();
    this.finishCurrent = null;
    this.revokeUrl();
  }

  dispose(): void {
    this.stop();
  }
}

// ── Hook ─────────────────────────────────────────

// 进程级单例：<audio> + OfflineAudioContext。
//
// dev 排查口：__lipSyncProbe.current 非 null 时，getRMS() 直接返回该值。
// 用途：headless/无用户手势环境下 <audio> 会被自动播放策略拦截（无播放头 →
// RMS 恒 0），此时无法验证「口型通道」本身。该开关仅 DEV 生效，生产不读取。
//
// 为什么是单例而不是 per-mount：应用开着 <StrictMode>，开发模式下 effect 会
// 「挂载 → 清理 → 再挂载」。若每次挂载新建实例并在清理时销毁，切换渲染器
// （或开发态热更新）会打断已在播放的音频 —— 用户听到的是"第一句莫名没声"。
// 音频链路上层已有 playback.done 与打断门控，单例不会造成状态串台。
let _player: LipSyncPlayer | null = null;

function getPlayer(gain?: number, smoothing?: number): LipSyncPlayer {
  if (!_player) _player = new LipSyncPlayer({ gain, smoothing });
  else _player.applyOptions(gain, smoothing);
  return _player;
}

/**
 * 注册 speak 桥 + 暴露口型控制器。
 *
 * 返回的 controller 引用稳定，可直接在渲染循环里调用。
 * 传 `active=false`（如预览实例）时不接管音频桥，只保留 getRMS 能力。
 */
export function useLipSyncAudio(
  gain?: number,
  smoothing?: number,
  active = true,
): LipSyncController {
  // owner token 每次挂载新建 —— StrictMode 双挂载时后一个实例合法接管
  const ownerRef = useRef<symbol>(Symbol("lipSync"));
  const gainRef = useRef(gain);
  const smoothingRef = useRef(smoothing);
  gainRef.current = gain;
  smoothingRef.current = smoothing;
  const player = getPlayer(gain, smoothing);

  // 控制器引用稳定：渲染循环/定时器可以直接持有
  const controllerRef = useRef<LipSyncController>({
    getRMS: () => player.getRMS(),
    isSpeaking: () => player.isSpeaking(),
    reset: () => player.reset(),
  });

  const [controller] = useState(() => ({
    getRMS: () => controllerRef.current.getRMS(),
    isSpeaking: () => controllerRef.current.isSpeaking(),
    reset: () => controllerRef.current.reset(),
  }));

  useEffect(() => {
    if (!active) return;
    const owner = ownerRef.current;
    // 必须通过 getPlayer() 取**当前**单例，不能闭包捕获本渲染时的 player：
    // 应用开着 StrictMode，首次渲染拿到的 player 之后可能已被新实例替换，
    // 闭包捕获旧实例会让 speak 走向已废弃的 <audio>（切形象后音频卡死/无声）。
    const bridge: SpeakerBridge = {
      speak: (buf, mime) => getPlayer(gainRef.current, smoothingRef.current).speak(buf, mime),
      stop: () => {
        const p = getPlayer();
        p.stop();
        p.reset();
      },
    };
    registerSpeaker(bridge, owner);
    return () => {
      // 只注销桥；不销毁单例播放器（StrictMode 重挂载 / 切形象后仍要用）。
      // owner 不匹配时本调用无效 —— 不会踢掉新实例的桥。
      registerSpeaker(null, owner);
    };
  }, [player, active]);

  useEffect(() => {
    player.applyOptions(gain, smoothing);
  }, [player, gain, smoothing]);

  return controller;
}

// dev 排查口（与 __wsClient / __agentStore 同一约定，打包版不含）
if (import.meta.env.DEV) {
  const g = globalThis as unknown as Record<string, unknown>;
  g.__lipSyncProbe = { current: null };
  g.__lipSyncState = bridgeState; // 桥归属：切形象后应指向新渲染器实例
}
