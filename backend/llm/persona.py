"""
System prompt 组装器 — 从 persona 配置生成结构化 system prompt。

换人设不改代码：用户在 config.user.yaml 覆盖 persona 段，重启即生效。
persona 为空时 fallback 到 llm.system_prompt（向后兼容）。

用法:
    from backend.llm.persona import build_system_prompt
    prompt = build_system_prompt(config.get("persona"))
"""

from backend.config import config


def build_system_prompt(persona_cfg: dict | None = None) -> str:
    """
    从 persona 配置组装 system prompt。

    persona 为空/None/name 为空 → 返回 llm.system_prompt（兜底）。
    否则返回 7 层 XML 结构化 prompt。
    """
    if not persona_cfg or not persona_cfg.get("name"):
        return config.get("llm.system_prompt", "")

    parts: list[str] = []

    # 1. 身份
    identity = persona_cfg.get("identity", "")
    if identity:
        parts.append(f"<Identity>{identity}</Identity>")

    # 2. 性格
    personality = persona_cfg.get("personality", "")
    if personality:
        parts.append(f"<Personality>{personality}</Personality>")

    # 3. 说话风格（含 TTS 约束）
    style = persona_cfg.get("speaking_style", "")
    parts.append(
        f"<SpeakingStyle>\n{style}\n"
        "重要：你的回复会被 TTS 朗读并实时对话，像真人说话。"
        "不要使用 Markdown 格式、列表、表情符号或长段落。\n"
        "</SpeakingStyle>"
    )

    # 4. 语言
    language = persona_cfg.get("language", "中文")
    parts.append(f"<Language>{language}</Language>")

    # 5. 角色背景（可选）
    background = persona_cfg.get("background", "")
    if background:
        parts.append(f"<Background>{background}</Background>")

    # 6. Few-shot 样本（可选）
    examples: list[dict] = persona_cfg.get("few_shot_examples", [])
    if examples:
        lines = ["<Examples>"]
        for ex in examples:
            user = ex.get("user", "")
            assistant = ex.get("assistant", "")
            lines.append(f"<Example>\n用户: {user}\n助手: {assistant}\n</Example>")
        lines.append("</Examples>")
        parts.append("\n".join(lines))

    # 7. ASR 容错（硬编码，每条都要）
    parts.append(
        "<ASRNote>用户输入来自语音识别，可能有同音错字，"
        "按发音合理推断真实意图，不要复述或纠正错字。</ASRNote>"
    )

    return "\n\n".join(parts)
