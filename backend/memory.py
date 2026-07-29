"""
长期记忆管理器。

JSON 文件存储，会话结束时由 LLM 提取关键信息，
下次会话开始时注入 system prompt。

设计约束：
- 纯内存操作，不引入数据库/向量存储
- 提取失败静默丢弃，不抛异常
- _save() 原子写入（tmp + rename），防止进程被杀时文件损坏
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger("memory")

# ── 数据模型 ────────────────────────────────────


@dataclass
class MemoryEntry:
    """单条长期记忆"""
    id: str
    content: str
    category: str          # fact | preference | event | other
    created_at: float
    session_id: str


# ── LLM 提取 prompt ────────────────────────────

_EXTRACT_PROMPT = """你是一个信息提取助手。分析以下对话，提取关于用户的重要信息。
只提取以下类型的信息：
- fact: 用户提到的事实信息（姓名、职业、地点、技能等）
- preference: 用户的偏好或习惯（喜欢/不喜欢什么、希望如何被回复等）
- event: 用户提到的重要事件（计划、日期、待办等）

要求：
1. 只提取当前对话中出现的、值得长期记住的信息
2. 每条内容简洁明了，一句话以内
3. 不要提取礼貌用语、确认回复、闲聊内容
4. 如果对话中没有值得长期记录的信息，返回空数组 []
5. 严格返回 JSON 数组，不要包含任何其他文字

返回格式：
[{"content": "用户叫张三", "category": "fact"}, {"content": "用户喜欢简短回复", "category": "preference"}]

正面例子（应该提取）：
- 用户说"我叫小明" → [{"content": "用户叫小明", "category": "fact"}]
- 用户说"我是个后端开发" → [{"content": "用户是后端开发", "category": "fact"}]
- 用户说"下周三有个面试" → [{"content": "用户下周三有面试", "category": "event"}]
- 用户说"我不喜欢太啰嗦的回答" → [{"content": "用户不喜欢啰嗦的回答", "category": "preference"}]

反面例子（不要提取）：
- 用户说"你好" / "谢谢" / "好的我知道了" → []
- 用户说"今天天气不错" → []（除非是特定事件）
- 助手说了什么 → []（只提取用户的信息）"""


# ── MemoryManager ──────────────────────────────


class MemoryManager:
    """长期记忆的读/写管理器"""

    def __init__(self, storage_dir: str = "data"):
        self._storage_dir = storage_dir
        self._file_path = os.path.join(storage_dir, "long_term_memory.json")
        self._max_entries = 100

    # ── 公开 API ────────────────────────────────

    def get_context(self) -> str:
        """获取所有长期记忆的文本表示，供 system prompt 注入"""
        entries = self._load()
        if not entries:
            return ""
        lines = [f"- [{e.category}] {e.content}" for e in entries]
        return "\n".join(lines)

    async def extract_and_save(
        self, history: list, llm, session_id: str,
    ) -> None:
        """
        从对话历史中提取长期记忆并持久化。

        history: list[Message]
        llm: BaseLLM 实例（需有 chat() 方法）
        session_id: 当前会话 ID
        """
        try:
            formatted = self._format_history(history)
            if not formatted.strip():
                return

            response = await llm.chat(
                messages=[
                    {"role": "system", "content": _EXTRACT_PROMPT},
                    {"role": "user", "content": f"请分析以下对话并提取信息：\n\n{formatted}"},
                ],
            )
            items = self._parse_response(response)
            if items:
                self._save(items, session_id)
                logger.info(f"提取了 {len(items)} 条长期记忆")
            else:
                logger.info("未提取到值得记录的长期记忆")
        except Exception as e:
            logger.warning(f"记忆提取失败（静默丢弃）: {e}")

    # ── 内部方法 ────────────────────────────────

    def _load(self) -> list[MemoryEntry]:
        """从 JSON 文件加载所有记忆"""
        try:
            with open(self._file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            memories = data.get("memories", [])
            return [
                MemoryEntry(
                    id=m["id"],
                    content=m["content"],
                    category=m.get("category", "other"),
                    created_at=m["created_at"],
                    session_id=m.get("session_id", ""),
                )
                for m in memories
            ]
        except FileNotFoundError:
            return []
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"记忆文件解析失败: {e}")
            return []

    def _save(self, new_items: list[dict], session_id: str) -> None:
        """追加新记忆并原子写入文件"""
        existing = self._load()
        now = time.time()

        for item in new_items:
            entry = MemoryEntry(
                id=uuid.uuid4().hex[:8],
                content=item.get("content", ""),
                category=item.get("category", "other"),
                created_at=now,
                session_id=session_id,
            )
            existing.append(entry)

        # FIFO 截断
        if len(existing) > self._max_entries:
            existing = existing[-self._max_entries:]

        data = {
            "version": 1,
            "memories": [
                {
                    "id": e.id,
                    "content": e.content,
                    "category": e.category,
                    "created_at": e.created_at,
                    "session_id": e.session_id,
                }
                for e in existing
            ],
        }

        # 原子写入：先写 tmp，再 rename
        os.makedirs(self._storage_dir, exist_ok=True)
        tmp_path = self._file_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self._file_path)

    @staticmethod
    def _format_history(history: list) -> str:
        """将 Message 列表转为标记文本"""
        role_labels = {
            "user": "用户",
            "assistant": "助手",
            "tool": "工具",
        }
        lines: list[str] = []
        # ponytail: O(n) 全量扫描，50 轮以内无瓶颈。超过再考虑切片
        for i, msg in enumerate(history[-100:]):  # 最多取最近 100 条（50 轮）
            role = getattr(msg, "role", "unknown")
            content = getattr(msg, "content", "") or ""
            label = role_labels.get(role, role)
            # 每条截断到 500 字
            short = content[:500] + "..." if len(content) > 500 else content
            lines.append(f"{label}: {short}")
            if i == 0 and role == "system":
                lines.append("---以上为系统提示，以下为对话---")
        return "\n\n".join(lines)

    @staticmethod
    def _parse_response(text: str) -> list[dict]:
        """从 LLM 输出中稳健提取 JSON 数组"""
        if not text:
            return []
        text = text.strip()
        # 找第一个 [ 和最后一个 ]
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or start >= end:
            return []
        try:
            parsed = json.loads(text[start:end + 1])
            if isinstance(parsed, list):
                return [
                    {"content": item.get("content", ""), "category": item.get("category", "other")}
                    for item in parsed
                    if isinstance(item, dict) and item.get("content", "").strip()
                ]
        except (json.JSONDecodeError, TypeError):
            pass
        return []
