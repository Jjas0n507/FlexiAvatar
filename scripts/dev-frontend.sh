#!/usr/bin/env bash
# FlexiAvatar 前端启动脚本（连接 Docker 后端）。
#
# 必须用它（或任何非 snap 终端）启动：snap 版 VSCode 的集成终端会向环境
# 泄漏 core20 旧库路径，Electron 的 GPU 进程加载到旧 libstdc++/gio 后
# GPU 加速随机起不来（GPU 特性表全 disabled_software → FPS 掷骰子）。
set -e
cd "$(dirname "$0")/../frontend"

unset ELECTRON_RUN_AS_NODE
unset GTK_PATH GIO_MODULE_DIR GIO_EXTRA_MODULES
unset LD_LIBRARY_PATH LOCPATH GSETTINGS_SCHEMA_DIR

export FLEXIAVATAR_DOCKER=1
exec npm run electron:dev
