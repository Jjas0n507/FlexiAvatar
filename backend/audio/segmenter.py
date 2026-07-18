"""
增量分句器。

从 LLM 流式文本中逐 chunk 提取完整句子，支持：
- 首句放宽到逗号切分（压低首句延迟）
- 后续句子按句末标点切分
- 最小句子长度保护（避免过短碎片）
"""

import re
import logging

logger = logging.getLogger("segmenter")


class Segmenter:
    """增量式文本分句器，用于流式 LLM → TTS 管道。"""

    def __init__(
        self,
        min_segment_length: int = 15,
        first_segment_punc: str = "，,。！？!?；;",
        rest_segment_punc: str = "。！？!?；;",
    ):
        self._min_length = min_segment_length
        self._first_punc = first_segment_punc
        self._rest_punc = rest_segment_punc
        self._buffer = ""
        self._is_first = True
        self._sentence_count = 0

    @property
    def sentence_count(self) -> int:
        return self._sentence_count

    def feed(self, chunk: str) -> list[str]:
        """喂入文本块，返回检测到的完整句子列表。"""
        self._buffer += chunk
        sentences: list[str] = []

        punct_set = self._first_punc if self._is_first else self._rest_punc

        while True:
            match = re.search(f"[{re.escape(punct_set)}]", self._buffer)
            if not match:
                break

            end_pos = match.end()
            candidate = self._buffer[:end_pos]
            char_count = len([c for c in candidate if c.strip()])

            if char_count >= self._min_length:
                sentences.append(candidate)
                self._buffer = self._buffer[end_pos:]
                self._is_first = False
                punct_set = self._rest_punc
                self._sentence_count += 1
            else:
                # 候选太短——尝试与下一个标点合并
                rest = self._buffer[end_pos:]
                next_match = re.search(f"[{re.escape(punct_set)}]", rest)
                if next_match:
                    merge_end = end_pos + next_match.end()
                    merged = self._buffer[:merge_end]
                    sentences.append(merged)
                    self._buffer = self._buffer[merge_end:]
                    self._is_first = False
                    punct_set = self._rest_punc
                    self._sentence_count += 1
                else:
                    # 无法合并，等待更多文本
                    break

        return sentences

    def flush(self) -> str:
        """清空缓冲区，返回剩余未完成文本。"""
        remaining = self._buffer.strip()
        self._buffer = ""
        if remaining:
            self._sentence_count += 1
        return remaining
