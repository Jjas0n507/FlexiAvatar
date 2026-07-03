# 当前开发状态

> ⚠️ 此文件记录**动态**信息，每次切换工作内容时更新。
> 最后更新：2026-07-03

## 当前位置

- **分支**: `phase3-streaming-pipeline`（从 `master` 切出）
- **阶段**: Phase 3 — 流式管线（ASR → LLM → TTS 全链路流式化）
- **进度**: 核心功能已完成，待做集成测试和端到端验证

## 最近提交

```
35f1179 docs: add TODO.md tracking gaps across Phases 1-3
02f2797 fix(config): load .env from project root, read OPENAI_API_KEY/BASE_URL from env
b9f4e6f feat(tts): add streaming synthesis (sentence-by-sentence)
a3987ea feat(asr): add streaming transcription support
77dd4a4 feat(llm): implement OpenAI streaming adapter with pipeline integration
```

## 架构决策（Phase 3 期间确定）

1. LLM 适配器使用 OpenAI 兼容 SSE 流式 API
2. TTS 按句子分割（Edge-TTS v7 仅支持 SentenceBoundary）
3. 中断响应通过 `cancel_event` 贯穿全链路，延迟 < 300ms
4. `.env` 从项目根目录加载，环境变量注入 API key

## 已知问题

- `pydub` 需要 ffmpeg 转 MP3→WAV，Windows 环境未安装 → `test_tts.py` 会失败
- ASR 模型 warmup 需要约 22 秒，启动时无进度提示
- 当前 LLM 适配器在 pipeline 中硬编码，切换后端需改代码

详见 `TODO.md`。
