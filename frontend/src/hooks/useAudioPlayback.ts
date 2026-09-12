/**
 * TTS 音频播放 Hook（RMS 口型驱动）。
 *
 * FIFO 队列 + 泵循环：每段先应用表情，再 await speak(bytes) —
 * 渲染器的 speak 桥负责解码(OfflineAudioContext)、播放(<audio>)、
 * 每帧 RMS 驱动口型；口型与播放头同源(el.currentTime)，结构上不失步。
 *
 * 队列排空 → 300ms 防抖发送 playback.done。
 * 打断（sessionState=interrupted）→ stopAll()：停音频+清队列+按 utteranceId 丢迟到段。
 *
 * 单例约束：播放泵是模块级单例（同一时刻只应有一条播放链）。
 * 桥的注册带 owner token —— 运行期切换渲染器时，旧画布的 cleanup
 * 不得把新画布刚注册的桥置空（历史上这会让音频整体静默）。
 */

import { useEffect } from "react";
import { useAgentStore } from "../stores/agent-store";
import { wsClient } from "../services/ws-client";

// ── 桥接口（渲染器在模型加载后注册）────────
export interface SpeakerBridge {
  /** 播放一段音频并驱动口型；resolve = 播放结束 */
  speak: (buf: ArrayBuffer, mime: string) => Promise<void>;
  /** 立即停止播放和口型 */
  stop: () => void;
}

interface Segment {
  buf: ArrayBuffer;
  mime: string;
  expression: string | null;
  utteranceId: string;
}

// ── 模块级单例 ────────────────────────────────────
let _bridge: SpeakerBridge | null = null;
let _bridgeOwner: symbol | null = null;
let _exprSetter: ((name: string) => void) | null = null;
let _exprOwner: symbol | null = null;
const _queue: Segment[] = [];
let _pumping = false;
let _staleUtteranceId: string | null = null;
let _lastUtteranceId: string | null = null;
let _doneTimer: ReturnType<typeof setTimeout> | null = null;

/**
 * 注册 speak 桥。`owner` 是渲染器实例的身份 token（通常 useRef(Symbol())）。
 *
 * 传 bridge 时：无条件接管（新实例永远优先）。
 * 传 null 时：**只有当前 owner 才能注销** —— 否则旧实例的 cleanup 会踢掉
 * 新实例刚注册的桥，导致 audio 播放链整体静默（切形象时必踩）。
 */
export function registerSpeaker(bridge: SpeakerBridge | null, owner: symbol): void {
  if (bridge === null) {
    if (_bridgeOwner !== owner) return; // 已被新实例接管，旧实例无权注销
    _bridge = null;
    _bridgeOwner = null;
    return;
  }
  _bridge = bridge;
  _bridgeOwner = owner;
  if (_queue.length > 0) void pump(); // 模型晚于音频就绪时补泵
}

export function registerExpressionSetter(fn: ((name: string) => void) | null, owner: symbol): void {
  if (fn === null) {
    if (_exprOwner !== owner) return;
    _exprSetter = null;
    _exprOwner = null;
    return;
  }
  _exprSetter = fn;
  _exprOwner = owner;
}

function schedulePlaybackDone(): void {
  if (_doneTimer) clearTimeout(_doneTimer);
  _doneTimer = setTimeout(() => {
    console.log("[Audio] sending playback.done");
    wsClient.sendPlaybackDone();
    _doneTimer = null;
  }, 300);
}

async function pump(): Promise<void> {
  if (_pumping) return;
  _pumping = true;
  try {
    while (_queue.length > 0) {
      if (!_bridge) return; // 模型未就绪：保留队列，registerSpeaker 时补泵
      const seg = _queue.shift()!;
      if (seg.utteranceId === _staleUtteranceId) continue; // 打断后的迟到段
      _exprSetter?.(seg.expression ?? "neutral");
      try {
        await _bridge.speak(seg.buf, seg.mime);
      } catch (e) {
        console.error("[Audio] segment playback failed (skipped):", e);
        // decode/播放失败只跳本段，泵不停
      }
    }
    schedulePlaybackDone();
  } finally {
    _pumping = false;
    if (_bridge && _queue.length > 0) void pump(); // 泵收尾瞬间的新入队
  }
}

/** 停止播放：清队列 + 停音频/口型 + 表情复位；之后同 utteranceId 的迟到段直接丢弃 */
export function stopAll(): void {
  _staleUtteranceId = _lastUtteranceId;
  _queue.length = 0;
  _bridge?.stop();
  _exprSetter?.("neutral");
  if (_doneTimer) {
    clearTimeout(_doneTimer);
    _doneTimer = null;
  }
}

export function useAudioPlayback(): void {
  useEffect(() => {
    const unsubTts = useAgentStore.subscribe(
      (state) => state.ttsSpeech,
      (speech) => {
        if (!speech?.audio) return;
        if (speech.utteranceId && speech.utteranceId === _staleUtteranceId) {
          console.log("[Audio] stale segment dropped:", speech.utteranceId, speech.seq);
          return;
        }

        // base64 → ArrayBuffer
        const binary = atob(speech.audio);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

        _lastUtteranceId = speech.utteranceId ?? null;
        // 新 utterance 开始 → 丢弃队列里其它 utterance 的陈段
        // （桥未注册的窗口期可能积压上一轮的段，恢复后不应播旧语音）
        if (speech.utteranceId && _queue.length > 0 && _queue[0].utteranceId !== speech.utteranceId) {
          console.log(`[Audio] dropping ${_queue.length} stale queued segment(s)`);
          _queue.length = 0;
        }
        console.log(
          `[Audio] enqueue seq=${speech.seq} ${bytes.length}B fmt=${speech.format} queue=${_queue.length + 1} bridge=${!!_bridge}`,
        );
        _queue.push({
          buf: bytes.buffer,
          mime: speech.format === "wav" ? "audio/wav" : "audio/mpeg",
          expression: speech.expressions?.[0]?.name ?? null,
          utteranceId: speech.utteranceId ?? "",
        });
        if (_doneTimer) {
          clearTimeout(_doneTimer);
          _doneTimer = null;
        }
        void pump();
      }
    );

    const unsubState = useAgentStore.subscribe(
      (state) => state.sessionState,
      (state) => {
        if (state === "interrupted") stopAll();
      }
    );

    return () => {
      unsubTts();
      unsubState();
      stopAll();
    };
  }, []);
}
