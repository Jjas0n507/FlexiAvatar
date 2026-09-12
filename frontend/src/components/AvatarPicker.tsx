/**
 * 形象选择页（开始界面第二阶段）。
 *
 * 用户先选模式（数字人 / Live2D），再从该模式的清单里选具体模型。
 * 点卡片即提交选择（后端 avatar.select 校验 + 加载），成功后才进入主界面。
 *
 * 视觉复用 StartScreen 的 .start-* 样式；模型预览本版不做，
 * 但预留 .avatar-preview-slot —— 将来把预览渲染器挂进该节点即可，
 * 不需要动这个组件的结构（详见 docs/digital-human-avatar-plan.md §3.6）。
 */

import React, { useEffect, useMemo, useState } from "react";
import { useAgentStore } from "../stores/agent-store";
import { useAvatarCatalog } from "../hooks/useAvatarCatalog";
import type { AvatarEntry, AvatarType } from "../types";

interface AvatarPickerProps {
  /** 选择成功（后端已回执 profile）→ App 切到 loading */
  onSelected: () => void;
  /** 放弃选择，回到开始界面 */
  onBack: () => void;
}

const TYPE_LABELS: Record<AvatarType, string> = {
  digital_human: "数字人",
  live2d: "Live2D",
};

const AvatarCard: React.FC<{
  entry: AvatarEntry;
  busy: boolean;
  onPick: (id: string) => void;
}> = ({ entry, busy, onPick }) => {
  const disabled = busy || !entry.valid;
  const isPlaceholder = entry.id.includes("_placeholder");

  return (
    <button
      className={`avatar-card${entry.valid ? "" : " avatar-card--invalid"}`}
      disabled={disabled}
      onClick={() => onPick(entry.id)}
      title={entry.valid ? entry.model_path : entry.reason}
    >
      {/* 预览槽：本版为空，将来挂预览渲染器（不要在此直接创建 WebGL 上下文） */}
      <div className="avatar-preview-slot" data-avatar-id={entry.id} />
      <div className="avatar-card-name">{entry.name}</div>
      <div className="avatar-card-meta">
        <span className="avatar-badge">{TYPE_LABELS[entry.type] ?? entry.type}</span>
        {isPlaceholder && <span className="avatar-badge avatar-badge--warn">占位素材</span>}
        {!entry.valid && (
          <span className="avatar-badge avatar-badge--err" title={entry.reason}>
            不可用
          </span>
        )}
      </div>
      {!entry.valid && entry.reason && (
        <div className="avatar-card-reason">{entry.reason}</div>
      )}
    </button>
  );
};

const AvatarPicker: React.FC<AvatarPickerProps> = ({ onSelected, onBack }) => {
  const { catalog, loading, phase, error, reload, select } = useAvatarCatalog();
  const wsConnected = useAgentStore((s) => s.wsConnected);

  const availableTypes = useMemo<AvatarType[]>(() => {
    const types: AvatarType[] = [];
    if (catalog?.digital_human?.length) types.push("digital_human");
    if (catalog?.live2d?.length) types.push("live2d");
    return types;
  }, [catalog]);

  // 默认页签跟随「后端当前生效的类型」，否则用户选了 Live2D、返回后
  // 又看到数字人页签，要手动再切一次（实测体验问题）
  const [mode, setMode] = useState<AvatarType | null>(null);
  useEffect(() => {
    if (mode !== null || !catalog) return;
    if (catalog.type && availableTypes.includes(catalog.type)) setMode(catalog.type);
  }, [catalog, availableTypes, mode]);

  const requested: AvatarType = mode ?? catalog?.type ?? "digital_human";
  const effectiveMode: AvatarType = availableTypes.includes(requested)
    ? requested
    : (availableTypes[0] ?? "live2d");

  const entries = catalog?.[effectiveMode] ?? [];
  const busy = phase === "selecting";

  const handlePick = (id: string) => {
    if (busy) return;
    select(id)
      .then(() => onSelected())
      .catch(() => {
        /* 错误已进 store，页面就地提示 */
      });
  };

  const noCatalogAtAll =
    catalog !== null && availableTypes.length === 0;

  return (
    <div className="start-screen">
      <div className="start-card start-card--wide">
        <h1 className="start-title">选择形象</h1>
        <p className="start-subtitle">先选模式，再选具体模型</p>

        {/* 模式切换 */}
        {availableTypes.length > 1 && (
          <div className="avatar-mode-tabs">
            {availableTypes.map((t) => (
              <button
                key={t}
                className={`avatar-mode-tab${effectiveMode === t ? " avatar-mode-tab--active" : ""}`}
                onClick={() => setMode(t)}
                disabled={busy}
              >
                {TYPE_LABELS[t]}
              </button>
            ))}
          </div>
        )}

        {/* 连接 / 加载 / 错误 / 空清单 */}
        {!wsConnected && <p className="start-status">正在连接后端...</p>}
        {wsConnected && loading && <div className="start-spinner" />}

        {wsConnected && phase === "error" && (
          <>
            <p className="start-error">{error}</p>
            <button className="start-btn" onClick={reload} disabled={busy}>
              重试
            </button>
          </>
        )}

        {wsConnected && noCatalogAtAll && (
          <p className="start-error">
            没有发现任何形象。
            <br />
            <span style={{ fontSize: 12, opacity: 0.8 }}>
              数字人素材请放入 frontend/public/avatar/&lt;名字&gt;/（含 .glb 与 avatar_profile.yaml）；
              或运行 bash scripts/fetch-placeholder-avatars.sh 获取占位素材。
            </span>
          </p>
        )}

        {/* 形象清单 */}
        {wsConnected && entries.length > 0 && (
          <div className="avatar-grid">
            {entries.map((entry) => (
              <AvatarCard key={entry.id} entry={entry} busy={busy} onPick={handlePick} />
            ))}
          </div>
        )}

        {busy && <p className="start-status">正在加载形象...</p>}

        <button className="start-link-btn" onClick={onBack} disabled={busy}>
          ← 返回
        </button>
      </div>
    </div>
  );
};

export default AvatarPicker;
