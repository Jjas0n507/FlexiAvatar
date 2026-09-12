/**
 * 形象渲染分发壳。
 *
 * 按后端 `avatar.profile.type` 选择渲染器：
 *   "live2d"        → <Live2DCanvas/>        （现有实现，行为不变）
 *   "digital_human" → <DigitalHumanCanvas/>  （Three.js）
 *
 * key 用形象 id 强制重建：运行期切换形象时保证旧渲染器完整卸载
 * （WebGL 上下文释放），且只挂载一个渲染器 —— 不出现两个 GL 上下文并存。
 *
 * profile 缺失/type 非法时回退 Live2D 并告警（不黑屏）。
 * `.avatar-root[data-avatar-type]` 便于调试与后续选择页共用容器语义。
 */

import React from "react";
import { useAgentStore } from "../stores/agent-store";
import Live2DCanvas from "./Live2DCanvas";
import DigitalHumanCanvas from "./DigitalHumanCanvas";

const AvatarCanvas: React.FC = () => {
  const avatarProfile = useAgentStore((s) => s.avatarProfile);
  const selectedAvatar = useAgentStore((s) => s.selectedAvatar);

  const type = avatarProfile?.type;

  if (type && type !== "live2d" && type !== "digital_human") {
    console.error(`[Avatar] 未知形象类型 "${type}"，回退 Live2D`);
  }

  const useDigitalHuman = type === "digital_human";
  const renderKey = selectedAvatar?.id ?? type ?? "default";
  const resolvedType = useDigitalHuman ? "digital_human" : "live2d";

  return (
    <div className="avatar-root" data-avatar-type={resolvedType}>
      {useDigitalHuman && avatarProfile?.type === "digital_human" ? (
        <DigitalHumanCanvas key={renderKey} profile={avatarProfile} />
      ) : (
        <Live2DCanvas key={renderKey} />
      )}
    </div>
  );
};

export default AvatarCanvas;
