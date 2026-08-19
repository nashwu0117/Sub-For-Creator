"""Tests for rule-based sentence segmentation."""

import pytest

from app.core.exceptions import SegmentationError
from app.core.models import Word
from app.core.segmenter import segment_words


def w(text: str, start: float, end: float) -> Word:
    return Word(text=text, start=start, end=end)


def zh_words(text: str, step: float = 0.3) -> list[Word]:
    return [w(c, i * step, i * step + step * 0.8) for i, c in enumerate(text)]


def test_punctuation_split():
    words = [
        w("今天", 0.0, 0.5),
        w("天氣", 0.5, 1.0),
        w("真好。", 1.0, 1.5),
        w("我們", 1.5, 2.0),
        w("去", 2.0, 2.5),
    ]
    segs = segment_words(words, lang="zh")
    assert [s.text for s in segs] == ["今天天氣真好。", "我們去"]
    assert [s.id for s in segs] == [0, 1]


def test_pause_split():
    words = [
        w("hello", 0.0, 1.0),
        w("world", 2.0, 3.0),  # 1.0s gap after "hello"
        w("again", 3.0, 4.0),
    ]
    segs = segment_words(words, lang="en")
    assert [s.text for s in segs] == ["hello", "world again"]


def test_pause_threshold_respected():
    words = [
        w("a", 0.0, 1.0),
        w("b", 1.1, 2.0),  # 0.1s gap < 0.3 → no split
    ]
    segs = segment_words(words, lang="en", pause_threshold=0.3)
    assert [s.text for s in segs] == ["a b"]


def test_length_split_soft_boundary_zh():
    pieces = "今天天氣真好，我們一起去公園散步很開心。"
    segs = segment_words(zh_words(pieces), lang="zh", max_chars=16)
    assert [s.text for s in segs] == ["今天天氣真好，", "我們一起去公園散步很開心。"]
    assert all(len(s.text) <= 16 for s in segs)


def test_length_split_hard_boundary_zh():
    # no punctuation at all → pure length split at 16 then 4 chars
    segs = segment_words(zh_words("字" * 20), lang="zh", max_chars=16)
    assert [len(s.text) for s in segs] == [16, 4]
    assert "".join(s.text for s in segs) == "字" * 20


def test_english_word_boundary_integrity():
    pieces = [f"word{i:02d}" for i in range(30)]  # 6 chars each
    words = [w(p, i * 0.2, i * 0.2 + 0.15) for i, p in enumerate(pieces)]
    segs = segment_words(words, lang="en")  # default max_chars=40
    assert len(segs) == 5
    assert all(len(s.text.split()) == 6 for s in segs)
    assert "".join(s.text for s in segs).replace(" ", "") == "".join(pieces)


def test_single_long_word_kept_intact():
    long_word = "supercalifragilisticexpialidocious"
    words = [w(long_word, 0.0, 1.0), w("next", 1.0, 1.5)]
    segs = segment_words(words, lang="en", max_chars=16)
    assert [s.text for s in segs] == [long_word, "next"]


def test_whitespace_words_dropped():
    words = [w("  ", 0.0, 0.1), w("hello", 0.1, 0.4), w(" ", 0.4, 0.5)]
    segs = segment_words(words, lang="en")
    assert [s.text for s in segs] == ["hello"]


def test_punctuation_only_segment_dropped():
    words = [w("…", 0.0, 0.3), w("真的", 0.3, 0.6)]
    segs = segment_words(words, lang="zh")
    assert [s.text for s in segs] == ["真的"]


def test_all_punctuation_returns_empty():
    # every candidate line is punctuation-only → all dropped, empty result
    assert segment_words([w("…", 0.0, 0.3)], lang="zh") == []
    assert segment_words([w("，", 0.0, 0.3), w("。", 0.3, 0.6)], lang="zh") == []


def test_empty_word_list_raises():
    with pytest.raises(SegmentationError):
        segment_words([])


def test_id_continuity():
    words = [w("啊。", 0.0, 0.3), w("啊", 0.3, 0.6), w("。", 0.6, 0.9), w("嘿", 0.9, 1.2)]
    segs = segment_words(words, lang="zh")
    assert [s.id for s in segs] == list(range(len(segs)))


def test_start_end_enforcement():
    words = [w("a", 1.0, 0.5), w("b", 0.6, 0.4)]  # end < start on both words
    segs = segment_words(words, lang="en")
    assert all(s.start < s.end for s in segs)
    assert segs[0].end == pytest.approx(1.0 + 0.1)


def test_timestamps_never_negative():
    words = [w("a", -2.0, -1.0), w("b", -0.5, 0.5)]
    segs = segment_words(words, lang="en")
    assert all(s.start >= 0.0 for s in segs)
    assert all(s.end > 0.0 for s in segs)


def test_short_segment_merged_into_next():
    words = [
        w("好。", 0.0, 0.2),  # 0.2s < min_segment_duration → merged
        w("今天", 0.5, 1.0),
        w("天氣", 1.0, 1.5),
    ]
    segs = segment_words(words, lang="zh", min_segment_duration=0.3)
    assert len(segs) == 1
    assert segs[0].text == "好。今天天氣"
    assert segs[0].start == pytest.approx(0.0)


def test_last_short_segment_kept():
    # second segment (0.1s) is short but it's the last one → kept, not merged
    words = [w("今天", 0.0, 0.5), w("天氣", 1.0, 1.1)]
    segs = segment_words(words, lang="zh", min_segment_duration=0.3)
    assert [s.text for s in segs] == ["今天", "天氣"]
    assert segs[1].end - segs[1].start < 0.3


def test_max_chars_lang_defaults():
    cjk = [w("字", i * 0.2, i * 0.2 + 0.15) for i in range(20)]
    assert [len(s.text) for s in segment_words(cjk, lang="zh")] == [16, 4]
    assert [len(s.text) for s in segment_words(cjk, lang="ja")] == [20]
    assert [len(s.text) for s in segment_words(cjk, lang="ko")] == [20]
    # unknown languages default to 40 chars
    many = [w("x", i * 0.2, i * 0.2 + 0.1) for i in range(45)]
    segs = segment_words(many, lang="fr")
    assert len(segs) == 2
    assert all(len(s.text.replace(" ", "")) <= 40 for s in segs)


def test_deterministic():
    words = zh_words("啊" * 30)
    a = segment_words(words, lang="zh", max_chars=16)
    b = segment_words(words, lang="zh", max_chars=16)
    assert a == b
