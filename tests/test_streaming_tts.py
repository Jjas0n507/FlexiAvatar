"""Phase B: 增量分句器 + 流式 TTS 测试"""

import pytest
from backend.audio.segmenter import Segmenter


class TestSegmenter:
    """增量分句器测试"""

    def test_basic_sentence_split(self):
        """基本：句末标点切分"""
        s = Segmenter(min_segment_length=3)
        sentences = s.feed("你好。今天天气不错！")
        assert len(sentences) == 2
        assert sentences[0] == "你好。"
        assert sentences[1] == "今天天气不错！"

    def test_first_sentence_comma_split(self):
        """首句逗号切分（压低首句延迟）"""
        s = Segmenter(min_segment_length=5)
        # 首句用逗号切分
        sentences = s.feed("你好，我是小助手。很高兴认识你！")
        # "你好，" 只有3个有效字符，不够 min_length=5
        # "你好，我是小助手。" >= 5 → 切出
        assert len(sentences) >= 1
        assert "小助手" in sentences[0]

    def test_incremental_feed(self):
        """增量喂入：分块到达"""
        s = Segmenter(min_segment_length=5)
        # 第一块：不够长
        s1 = s.feed("今天天")
        assert s1 == []

        # 第二块：补全句子
        s2 = s.feed("气不错。明天呢？")
        assert len(s2) >= 1
        assert "今天天气不错。" in s2

    def test_flush_remaining(self):
        """flush 返回未完成文本"""
        s = Segmenter(min_segment_length=10)
        sentences = s.feed("短句。")
        # "短句。" 只有2个有效字符，不够 min_length
        assert sentences == []

        remaining = s.flush()
        assert remaining == "短句。"

    def test_no_punctuation_long_text(self):
        """无标点长文本：flush 返回全部"""
        s = Segmenter(min_segment_length=5)
        sentences = s.feed("这是一段没有标点的很长文本一直在继续")
        assert sentences == []

        remaining = s.flush()
        assert "很长文本" in remaining

    def test_mixed_punctuation(self):
        """混合中英文标点"""
        s = Segmenter(min_segment_length=5)
        sentences = s.feed("Hello world! 你好世界。")
        assert len(sentences) == 2
        assert "Hello world!" in sentences[0]
        assert "你好世界。" in sentences[1]

    def test_sentence_count_tracking(self):
        """sentence_count 跟踪"""
        s = Segmenter(min_segment_length=5)
        assert s.sentence_count == 0

        s.feed("这是第一句话。这是第二句话。")
        assert s.sentence_count == 2

        remaining = s.flush()
        if remaining:
            assert s.sentence_count == 3
        else:
            assert s.sentence_count == 2

    def test_short_segments_merged(self):
        """过短片段合并到下一个标点"""
        s = Segmenter(min_segment_length=15)
        sentences = s.feed("好。今天天气真不错啊！")
        # "好。" 太短，与后续合并
        assert len(sentences) >= 1
        combined = "".join(sentences)
        assert "好" in combined
        assert "今天天气真不错啊" in combined

    def test_buffer_after_multiple_feeds(self):
        """多次 feed 后 buffer 状态正确"""
        s = Segmenter(min_segment_length=3)
        sentences = s.feed("第一句。第二句的")
        # "第一句。" 4 chars >= 3 → 被切出
        assert sentences == ["第一句。"]
        remaining = s.flush()
        assert remaining == "第二句的"


class TestSegmenterIntegration:
    """模拟真实 LLM 流式场景"""

    def test_simulated_streaming(self):
        """模拟 LLM 逐 chunk 输出"""
        chunks = [
            "你好",
            "！我是",
            "AI助手。",
            "今天天",
            "气不错，",
            "适合出门。",
        ]
        s = Segmenter(min_segment_length=5)
        all_sentences = []

        for chunk in chunks:
            sentences = s.feed(chunk)
            all_sentences.extend(sentences)

        remaining = s.flush()
        if remaining:
            all_sentences.append(remaining)

        assert len(all_sentences) >= 2
        assert any("AI助手" in sent for sent in all_sentences)
        assert any("适合出门" in sent for sent in all_sentences)
