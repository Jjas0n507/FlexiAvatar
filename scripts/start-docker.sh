#!/bin/bash
set -e
cd "$(dirname "$0")/.."

echo "=== Pulling Docker images ==="
docker compose --profile gpu pull

echo "=== Starting services ==="
docker compose --profile gpu up -d

echo "=== Pulling Ollama model (qwen2.5:7b) ==="
docker compose exec ollama ollama pull qwen2.5:7b 2>/dev/null || true

echo "=== Waiting for backend ==="
for i in $(seq 1 30); do
  if curl -s http://127.0.0.1:8765/health >/dev/null 2>&1; then
    echo "Backend ready!"
    break
  fi
  echo "  Waiting... ($i/30)"
  sleep 2
done

echo "=== Starting Electron ==="
cd frontend
# 避免 VS Code 环境的 ELECTRON_RUN_AS_NODE 导致 Electron 降级运行
unset ELECTRON_RUN_AS_NODE
FLEXIAVATAR_DOCKER=1 npm run electron:dev
