#!/usr/bin/env bash
# 下载「占位/验证用」形象素材到 frontend/public/avatar/_placeholder/。
#
# 用途：在真实数字人素材（ReadyPlayerMe / VRoid / 自建）就位前，
#       用公开可得的 GLB 把数字人链路端到端跑通。真实素材到位后只改
#       avatar_profile.yaml，不改代码。
#
# 素材来源：three.js 官方示例仓库（MIT），本机实测可达。
# 目录 frontend/public/avatar/_placeholder/ 已被 .gitignore 忽略，不入库。
#
# 用法：
#   bash scripts/fetch-placeholder-avatars.sh            # 缺什么下什么（幂等，跳过 VRM）
#   bash scripts/fetch-placeholder-avatars.sh --with-vrm # 额外下 VRoid 示例 VRM（10.7MB）
#   bash scripts/fetch-placeholder-avatars.sh -f         # 强制重新下载
#
# 网络：若已配置系统代理（如 Clash 127.0.0.1:7897），shell 里通常没有 *_proxy 变量，
#       curl/git 不会自动走代理。本脚本会尝试自动探测常见代理端口并附上。
#       也可自行 `export https_proxy=http://127.0.0.1:7897`。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$REPO_ROOT/frontend/public/avatar/_placeholder"
BASE="https://raw.githubusercontent.com/mrdoob/three.js/dev/examples/models/gltf"

FORCE=0
WITH_VRM=0
for arg in "$@"; do
  case "$arg" in
    -f|--force) FORCE=1 ;;
    --with-vrm) WITH_VRM=1 ;;
  esac
done

# 代理自动探测：系统代理（gsettings）常与 shell 环境变量脱节
detect_proxy() {
  [[ -n "${https_proxy:-}${HTTPS_PROXY:-}" ]] && return 0
  local host port
  host=$(timeout 5 gsettings get org.gnome.system.proxy.http host 2>/dev/null | tr -d "'")
  port=$(timeout 5 gsettings get org.gnome.system.proxy.http port 2>/dev/null)
  if [[ -n "$host" && -n "$port" ]] && timeout 3 bash -c "echo > /dev/tcp/$host/$port" 2>/dev/null; then
    export https_proxy="http://$host:$port" http_proxy="http://$host:$port"
    echo "  [info] 检测到系统代理 $host:$port，已用于本次下载"
  fi
}
detect_proxy

mkdir -p "$DEST/facecap" "$DEST/robot"

# ── 素材与用途（morph 能力由实测得出，勿凭印象改）──────────────
# facecap.glb        : 完整 ARKit 52 blendshape（jawOpen / eyeBlink_L,R / mouthSmile_L,R ...）
#                      → 验证 RMS 口型 + 眨眼 + 情绪 blendshape（逐 blendshape 类模型）
# RobotExpressive.glb: 仅 3 个整脸 morph（Angry / Surprised / Sad）+ 14 条骨骼动画，无嘴部 morph
#                      → 验证「整脸 morph」schema + AnimationMixer + 缺 morph 时的降级
fetch() {
  local rel="$1" out="$2" why="$3"
  local dest_file="$DEST/$out"

  if [[ -s "$dest_file" && $FORCE -eq 0 ]]; then
    echo "  [skip] $out 已存在 ($(du -h "$dest_file" | cut -f1))"
    return 0
  fi

  echo "  [get ] $out  ← $rel"
  echo "         $why"
  # --http1.1: GitHub raw 偶发 HTTP/2 PROTOCOL_ERROR（实测），降级协议更稳
  if ! curl -fsSL --http1.1 --retry 3 --retry-delay 1 --connect-timeout 20 \
       -o "$dest_file.part" "$BASE/$rel"; then
    rm -f "$dest_file.part"
    echo "  [FAIL] $out 下载失败（网络不通？可手动下载后放入 $DEST/）" >&2
    return 1
  fi
  mv "$dest_file.part" "$dest_file"
  echo "  [ ok ] $out $(du -h "$dest_file" | cut -f1)"
}

echo "占位形象素材 → $DEST"
fetch "facecap.glb" "facecap/facecap.glb" "ARKit 52 blendshape：口型/眨眼/情绪"
fetch "RobotExpressive/RobotExpressive.glb" "robot/robot.glb" "整脸 morph + 骨骼动画：第二类 schema"

# ── 生成 profile（与素材同目录；本目录 gitignore，故 profile 由脚本生成）──
write_profile() {
  local out="$1"; shift
  if [[ -s "$DEST/$out" && $FORCE -eq 0 ]]; then
    echo "  [skip] $out 已存在"
    return 0
  fi
  cat > "$DEST/$out"
  echo "  [ ok ] $out (profile)"
}

write_profile "facecap/avatar_profile.yaml" <<'YAML'
# 占位数字人 — facecap.glb（three.js 官方示例，MIT）。外观是人脸扫描头，非最终效果。
# morph 清单由 GLB extras.targetNames 实测得出；_L/_R 后缀是 ARKit 52 的变体，
# ReadyPlayerMe 用 Left/Right —— 命名不统一，故此处逐项显式映射。
name: "占位 · 人脸扫描头"
model_path: "facecap.glb"

persona_id: ""   # 预留关联字段（本版只解析/透传/显示，不消费）
voice_id: ""

camera:
  position: [0.0, 0.06, 0.42]
  target: [0.0, 0.0, 0.0]
  fov: 30.0

morphs:
  mouth_open: "jawOpen"
  blink_left: "eyeBlink_L"
  blink_right: "eyeBlink_R"

# 3D 的 jawOpen 灵敏度与 Live2D ParamMouthOpenY 不同，gain 需按模型标定
lip_sync:
  gain: 6.0
  smoothing: 0.5

expressions:
  neutral: { type: "blendshapes", params: {} }
  happy:
    type: "blendshapes"
    params: { mouthSmile_L: 0.7, mouthSmile_R: 0.7, cheekSquint_L: 0.45, cheekSquint_R: 0.45, eyeSquint_L: 0.3, eyeSquint_R: 0.3 }
  sad:
    type: "blendshapes"
    params: { browInnerUp: 0.6, mouthFrown_L: 0.45, mouthFrown_R: 0.45, eyeSquint_L: 0.25, eyeSquint_R: 0.25 }
  surprised:
    type: "blendshapes"
    params: { browInnerUp: 0.75, browOuterUp_L: 0.5, browOuterUp_R: 0.5, eyeWide_L: 0.7, eyeWide_R: 0.7, jawOpen: 0.3 }
  thinking:
    type: "blendshapes"
    params: { browDown_L: 0.45, browDown_R: 0.45, mouthPress_L: 0.3, mouthPress_R: 0.3, eyeLookUp_L: 0.25, eyeLookUp_R: 0.25 }

idle:
  blink_interval: [2.5, 6.0]
  expression_cycle: ["neutral", "happy", "thinking", "surprised"]
  expression_interval: [6.0, 14.0]
  look_at_range: 0.6
YAML

write_profile "robot/avatar_profile.yaml" <<'YAML'
# 占位数字人 — RobotExpressive.glb（three.js 官方示例，MIT）。
# 这个模型**只有 3 个整脸 morph**（Angry/Surprised/Sad），没有逐 blendshape，
# 用来验证 schema 的第二类写法（type: morph）与「缺 morph 降级」路径。
name: "占位 · 机器人（整脸 morph）"
model_path: "robot.glb"

persona_id: ""
voice_id: ""

camera:
  position: [0.0, 1.05, 3.4]
  target: [0.0, 0.95, 0.0]
  fov: 35.0

# 没有嘴部 morph → 用「发声时整体加偏置」的发声代理，验证 add 分支与降级
morphs:
  mouth_open: { add: "Surprised", amount: 0.45 }
  # 没有眨眼 morph：留空即整条通道跳过（渲染器 warn 后继续跑）
  blink_left: ""
  blink_right: ""

lip_sync:
  gain: 5.0
  smoothing: 0.5

expressions:
  neutral:   { type: "blendshapes", params: {} }
  happy:     { type: "morph", name: "Angry" }       # 该模型没有正向情绪 morph，占位映射
  sad:       { type: "morph", name: "Sad" }
  surprised: { type: "morph", name: "Surprised" }
  thinking:  { type: "morph", name: "Angry" }

idle:
  blink_interval: [3.0, 7.0]
  expression_cycle: ["neutral", "surprised", "sad"]
  expression_interval: [6.0, 14.0]
  look_at_range: 0.5
YAML

# ── 解码器（KTX2 / meshopt）：GLTFLoader 需要，随占位素材一起准备 ──
# 真实素材同样常用这两种压缩，所以这不是占位专用件。
FRONTEND_NM="$REPO_ROOT/frontend/node_modules/three/examples/jsm/libs"
DEC="$REPO_ROOT/frontend/public/decoders"
mkdir -p "$DEC/basis"
copy_decoder() {
  local src="$1" dst="$2"
  if [[ -s "$dst" && $FORCE -eq 0 ]]; then
    echo "  [skip] ${dst##*/}"
    return 0
  fi
  if [[ ! -f "$src" ]]; then
    echo "  [warn] 源文件不存在，跳过: $src" >&2
    return 0
  fi
  cp "$src" "$dst"
  echo "  [ ok ] ${dst##*/} ($(du -h "$dst" | cut -f1))"
}
echo "解码器 → $DEC"
copy_decoder "$FRONTEND_NM/basis/basis_transcoder.js"   "$DEC/basis/basis_transcoder.js"
copy_decoder "$FRONTEND_NM/basis/basis_transcoder.wasm" "$DEC/basis/basis_transcoder.wasm"
copy_decoder "$FRONTEND_NM/meshopt_decoder.module.js"   "$DEC/meshopt_decoder.module.js"

# ── 可选：VRoid 示例 VRM（真实二次元素材，需 --with-vrm）──
# VRM 命名体系与 RPM/facecap 都不同（`Face_Blendshape.Fcl_MTH_A` 等），
# 是验证"第三类素材"的好样本；同时它的口型是 A/I/U/E/O（viseme 级，后续升级用）。
VRM_DEST="$REPO_ROOT/frontend/public/avatar/vroid"
if [[ $WITH_VRM -eq 1 ]]; then
  mkdir -p "$VRM_DEST"
  if [[ -s "$VRM_DEST/model.vrm" && $FORCE -eq 0 ]]; then
    echo "  [skip] model.vrm 已存在 ($(du -h "$VRM_DEST/model.vrm" | cut -f1))"
  else
    echo "  [get ] model.vrm ← three-vrm 官方 VRM1 示例 (~10.7MB，需 --with-vrm)"
    if timeout 300 curl -fsSL --retry 2 --connect-timeout 20 \
         -o "$VRM_DEST/model.vrm.part" \
         "https://raw.githubusercontent.com/pixiv/three-vrm/dev/packages/three-vrm/examples/models/VRM1_Constraint_Twist_Sample.vrm"; then
      mv "$VRM_DEST/model.vrm.part" "$VRM_DEST/model.vrm"
      echo "  [ ok ] model.vrm $(du -h "$VRM_DEST/model.vrm" | cut -f1)"
    else
      rm -f "$VRM_DEST/model.vrm.part"
      echo "  [FAIL] VRM 下载失败（网络/代理不通）" >&2
    fi
  fi
else
  echo "  [skip] VRoid 示例 VRM（未指定 --with-vrm）"
fi

echo
echo "完成。可用素材："
find "$DEST" -name '*.glb' -o -name 'avatar_profile.yaml' | sort | sed 's|^|  |' || true
echo
echo "提示：这些素材仅用于验证链路，外观不代表最终数字人效果。"
echo "      真实素材到位后：放入 frontend/public/avatar/<名字>/ 并写 avatar_profile.yaml，"
echo "      代码无需改动（详见 docs/digital-human-avatar-plan.md §3.9）。"
echo
echo "注意：Ready Player Me（readyplayer.me / models.readyplayer.me）当前 DNS 已无记录，"
echo "      官方通道不可用（2026-09 实测；第三方监测显示站点持续 Down）。"
echo "      替代：VRoid（本脚本 --with-vrm / VRoid Studio 自建）、自建 GLB、Sketchfab 商用授权模型。"
