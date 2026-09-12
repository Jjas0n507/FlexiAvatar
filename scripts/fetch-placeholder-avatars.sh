#!/usr/bin/env bash
# 下载「占位/验证用」形象素材到 frontend/public/avatar/_placeholder/。
#
# 用途：在真实数字人素材（ReadyPlayerMe / VRoid / 自建）就位前，
#       用公开可得的 GLB 把数字人链路端到端跑通。真实素材到位后只改
#       avatar_profile.yaml，不改代码。
#
# 素材来源：three.js 官方示例仓库（MIT），本机实测可达。
# 目录已被 .gitignore 忽略（frontend/public/avatar/_placeholder/），不入库。
#
# 用法：
#   bash scripts/fetch-placeholder-avatars.sh          # 缺什么下什么（幂等）
#   bash scripts/fetch-placeholder-avatars.sh -f       # 强制重新下载
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$REPO_ROOT/frontend/public/avatar/_placeholder"
BASE="https://raw.githubusercontent.com/mrdoob/three.js/dev/examples/models/gltf"

FORCE=0
[[ "${1:-}" == "-f" || "${1:-}" == "--force" ]] && FORCE=1

mkdir -p "$DEST"

# ── 素材与用途（实测 morph 能力，勿凭印象改）────────────────────
# facecap.glb        : 完整 ARKit 52 blendshape（jawOpen / eyeBlink_L,R / mouthSmile_L,R ...）
#                      → 验证 RMS 口型 + 眨眼 + 情绪 blendshape
# RobotExpressive.glb: 仅 3 个整脸 morph（Angry / Surprised / Sad）+ 14 条骨骼动画
#                      → 验证「整脸 morph」第二类 schema + AnimationMixer + 无口型 morph 的降级
fetch() {
  local rel="$1" out="$2" why="$3"
  local dest_file="$DEST/$out"

  if [[ -s "$dest_file" && $FORCE -eq 0 ]]; then
    echo "  [skip] $out 已存在 ($(du -h "$dest_file" | cut -f1))"
    return 0
  fi

  echo "  [get ] $out  ← $rel"
  echo "         $why"
  if ! curl -fsSL --retry 2 --connect-timeout 20 -o "$dest_file.part" "$BASE/$rel"; then
    rm -f "$dest_file.part"
    echo "  [FAIL] $out 下载失败（网络不通？可手动下载后放入 $DEST/）" >&2
    return 1
  fi
  mv "$dest_file.part" "$dest_file"
  echo "  [ ok ] $out $(du -h "$dest_file" | cut -f1)"
}

echo "占位形象素材 → $DEST"
fetch "facecap.glb" "facecap.glb" "ARKit 52 blendshape：口型/眨眼/情绪"
fetch "RobotExpressive/RobotExpressive.glb" "RobotExpressive.glb" "整脸 morph + 骨骼动画：第二类 schema"

echo
echo "完成。可用素材："
ls -la "$DEST"/*.glb 2>/dev/null || echo "  (无)"
echo
echo "提示：这两个素材仅用于验证链路，外观不代表最终数字人效果。"
