"""
Ollama LLM 适配器 — 复用 OpenAIAdapter 的流式逻辑。

Ollama 暴露 OpenAI 兼容的 /v1/chat/completions 端点，
因此直接继承 OpenAIAdapter，仅覆盖构造函数默认值。

容器内通过 OLLAMA_HOST 环境变量指定 Ollama 地址（docker-compose 自动注入），
本地开发使用 config.default.yaml 中的 llm.ollama.base_url (localhost)。
"""

import os

from backend.llm.openai_adapter import OpenAIAdapter
from backend.config import config


class OllamaAdapter(OpenAIAdapter):
    def __init__(self):
        # 优先使用 OLLAMA_HOST 环境变量（Docker 场景），fallback 到 config
        base_url = os.getenv("OLLAMA_HOST") or config.get("llm.ollama.base_url", "http://localhost:11434")
        super().__init__(
            model=config.get("llm.ollama.model", "qwen2.5:7b"),
            base_url=f"{base_url.rstrip('/')}/v1",
            api_key="ollama",       # Ollama 不需要 API key，但 openai 库要求非空
            temperature=config.get("llm.ollama.temperature", 0.7),
            max_tokens=config.get("llm.openai.max_tokens", 1024),
        )
