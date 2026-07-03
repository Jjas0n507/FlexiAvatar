# 下一步行动

> ⚠️ 此文件记录**短期**待办，完成后划掉或删除。
> 最后更新：2026-07-03

## 当前优先级

### Phase 3 收尾
- [ ] 流式 ASR 嘈杂环境准确率验证
- [ ] LLM 流式输出 + 工具调用集成测试
- [ ] TTS 逐句播放与前端音画同步调优
- [ ] 中断恢复后上下文连贯性测试

### 技术债
- [ ] 安装 ffmpeg（`winget install ffmpeg`），修复 `test_tts.py`
- [ ] 创建 `.env.example` 模板
- [ ] LLM 适配器从硬编码改为配置驱动

### 下一阶段（Phase 4 — Live2D）
- [ ] 前端集成 Cubism SDK + 加载模型
- [ ] 口型同步引擎（对接 `motion_controller.py`）
- [ ] 表情与身体动作系统

> Phase 4 完整任务见 `DESIGN_AND_PLAN.md` 第 1543-1624 行。
