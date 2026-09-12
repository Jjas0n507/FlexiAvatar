/**
 * 数字人渲染画布（Three.js）。
 *
 * 本版范围见 docs/digital-human-avatar-plan.md §4 Stage 5：
 *   GLB 加载 → morph 权重表 → RMS 口型 → 情绪表情(lerp) → 打断停止 → 资源释放
 *
 * 与 Live2D 渲染器的共同约束（保证后续加"选择页预览"不冲突）：
 * - 只消费 profile 解析出的「最终 morph 权重表」，不关心来源
 *   （type:"blendshapes" 与 type:"morph" 走同一路径）
 * - owner token 归属自己的桥（切形象时不会被旧实例踢掉）
 * - preview 模式（后续）不注册音频桥、不做交互
 *
 * TODO(Stage 5): 接入 Three.js 渲染器主体。
 */

import React from "react";
import { useAgentStore } from "../stores/agent-store";
import type { DigitalHumanProfile } from "../types";

interface DigitalHumanCanvasProps {
  profile: DigitalHumanProfile;
}

const DigitalHumanCanvas: React.FC<DigitalHumanCanvasProps> = ({ profile }) => {
  const appPhase = useAgentStore((s) => s.appPhase);
  const morphCount = Object.keys(profile.expressions ?? {}).length;

  return (
    <div className="live2d-canvas-container">
      <div className="live2d-status-overlay">
        <p className="live2d-status-text">
          数字人渲染器待接入（Stage 5）
          <br />
          <span style={{ fontSize: 12, opacity: 0.7 }}>
            {profile.name} · {profile.model_path} · {morphCount} 个情绪 · phase={appPhase}
          </span>
        </p>
      </div>
    </div>
  );
};

export default DigitalHumanCanvas;
