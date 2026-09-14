/**
 * 形象清单 + 选择握手。
 *
 * 流程：
 *   1. 连上后端后 GET /api/avatars（路径由后端计算，前端零硬编码）
 *   2. 用户点选卡片 → wsClient.send("avatar.select", {id})
 *   3. 后端校验/加载后回 avatar.profile → store.avatarProfile 落定
 *
 * 选择结果通过「订阅 store」判定，而不是监听 ws 原始消息：
 * 这样无论 profile 从哪条路径进来（avatar.profile），判定逻辑都一致。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useAgentStore } from "../stores/agent-store";
import { wsClient } from "../services/ws-client";
import type { AvatarCatalog, AvatarProfile } from "../types";

/** 等待后端 profile 的超时（模型/引擎加载不该拖这么久） */
const SELECT_TIMEOUT_MS = 15_000;

export type SelectPhase = "idle" | "selecting" | "error";

export interface UseAvatarCatalogResult {
  /** 拉取清单（供重试） */
  reload: () => void;
  /** 提交选择；resolve = 后端已回执成功，reject = 失败或超时 */
  select: (id: string) => Promise<AvatarProfile>;
  loading: boolean;
  phase: SelectPhase;
  error: string | null;
  catalog: AvatarCatalog | null;
}

/** 带超时的 Promise */
function withTimeout<T>(p: Promise<T>, ms: number, onTimeout: () => Error): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(onTimeout()), ms);
    p.then(
      (v) => {
        clearTimeout(timer);
        resolve(v);
      },
      (e) => {
        clearTimeout(timer);
        reject(e);
      },
    );
  });
}

export function useAvatarCatalog(): UseAvatarCatalogResult {
  const wsConnected = useAgentStore((s) => s.wsConnected);
  const setAvatarCatalog = useAgentStore((s) => s.setAvatarCatalog);
  const setSelectedAvatar = useAgentStore((s) => s.setSelectedAvatar);
  const setAvatarProfile = useAgentStore((s) => s.setAvatarProfile);
  const setLastError = useAgentStore((s) => s.setLastError);

  const [loading, setLoading] = useState(false);
  const [phase, setPhase] = useState<SelectPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const catalog = useAgentStore((s) => s.avatarCatalog);

  // 待决的选择请求（后端回 profile 或报错时结算）
  const pendingRef = useRef<{
    resolve: (p: AvatarProfile) => void;
    reject: (e: Error) => void;
  } | null>(null);
  // 结算基线：zustand.subscribe 会**立即**用当前值回调一次。若不做基线比较，
  // 上一次留下（或 HMR 保留）的 avatarProfile 会立刻把刚发出的请求"结算"掉。
  //
  // 不能用「对象引用比较」做基线：后端每次都是新对象，切回同一个形象时引用
  // 必然不同却又"看起来没变"（实测：切回 Live2D 时 select 永不结算 → 卡在选择页）。
  // 改为**发请求前主动清空 avatarProfile**，于是「非 null 到达」本身就是明确回执。
  const baselineRef = useRef<{ profile: AvatarProfile | null; error: string | null }>({
    profile: null,
    error: null,
  });

  // ── 订阅「选择结果」 ────────────────────────
  useEffect(() => {
    const settle = (ok: boolean, value: AvatarProfile | string) => {
      const pending = pendingRef.current;
      if (!pending) return;
      pendingRef.current = null;
      if (ok) pending.resolve(value as AvatarProfile);
      else pending.reject(new Error(value as string));
    };

    const unsubOk = useAgentStore.subscribe(
      (s) => s.avatarProfile,
      (profile) => {
        // 只在「相比基线发生了变化且非空」时才算回执
        if (profile && profile !== baselineRef.current.profile) settle(true, profile);
        baselineRef.current.profile = profile;
      },
    );
    const unsubErr = useAgentStore.subscribe(
      (s) => s.lastError,
      (err) => {
        if (err && err !== baselineRef.current.error) settle(false, err);
        baselineRef.current.error = err;
      },
    );
    return () => {
      unsubOk();
      unsubErr();
    };
  }, []);

  // ── 拉取清单 ────────────────────────────────
  const reload = useCallback(() => {
    if (!wsConnected) return;
    setLoading(true);
    setError(null);
    fetch("/api/avatars")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<AvatarCatalog>;
      })
      .then((data) => {
        setAvatarCatalog(data);
        setPhase("idle");
      })
      .catch((e: unknown) => {
        setError(`形象清单获取失败: ${String(e)}`);
        setPhase("error");
      })
      .finally(() => setLoading(false));
  }, [wsConnected, setAvatarCatalog]);

  // 初次连上后自动拉一次
  useEffect(() => {
    if (!wsConnected || catalog) return;
    reload();
  }, [wsConnected, catalog, reload]);

  // ── 提交选择 ────────────────────────────────
  const select = useCallback(
    (id: string): Promise<AvatarProfile> => {
      setError(null);
      setLastError(null);
      // 先清空：让"新 profile 到达"成为无歧义的回执（见 baselineRef 注释）
      setAvatarProfile(null);
      baselineRef.current = { profile: null, error: null };
      setPhase("selecting");

      const entry =
        catalog?.live2d.find((e) => e.id === id) ??
        catalog?.digital_human.find((e) => e.id === id) ??
        null;
      setSelectedAvatar(entry);

      const promise = new Promise<AvatarProfile>((resolve, reject) => {
        pendingRef.current = { resolve, reject };
        const sent = wsClient.send("avatar.select", { id });
        if (!sent) {
          pendingRef.current = null;
          reject(new Error("与后端连接已断开，请重试"));
        }
      });

      return withTimeout(
        promise,
        SELECT_TIMEOUT_MS,
        () => new Error("形象选择超时：后端未返回 profile"),
      )
        .then((profile) => {
          setPhase("idle");
          return profile;
        })
        .catch((e: unknown) => {
          const msg = e instanceof Error ? e.message : String(e);
          setError(msg);
          setPhase("error");
          setSelectedAvatar(null);
          throw e;
        });
    },
    [catalog, setSelectedAvatar, setLastError, setAvatarProfile],
  );

  return { reload, select, loading, phase, error, catalog };
}
