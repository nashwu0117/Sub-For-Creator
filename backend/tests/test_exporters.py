"""Tests for backend/app/exporters — srt, vtt, txt, ass, fcpxml.

Run from the repo root: ``python -m pytest backend/tests/test_exporters.py``.
"""

from __future__ import annotations

import re
import sys
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

# The `app` package lives under backend/ and is not installed; make it
# importable when pytest runs from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.exceptions import ExportError  # noqa: E402
from app.core.models import Segment, TranscriptionResult, Word  # noqa: E402
from app.exporters import (  # noqa: E402
    AssStyle,
    export_ass,
    export_fcpxml,
    export_srt,
    export_text,
    export_vtt,
)
from app.exporters.ass import ass_color  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_result(
    segments: list[Segment] | None = None,
    media_duration: float | None = None,
    language: str = "zh",
) -> TranscriptionResult:
    return TranscriptionResult(
        segments=segments or [], language=language, media_duration=media_duration
    )


def two_segment_result() -> TranscriptionResult:
    """2-segment fixture with word timestamps (used by most tests)."""
    return make_result(
        segments=[
            Segment(
                id=1,
                start=0.0,
                end=2.5,
                text="你好，世界！",
                words=[
                    Word("你好", 0.0, 1.0),
                    Word("，", 1.0, 1.2),
                    Word("世界", 1.2, 2.2),
                    Word("！", 2.2, 2.5),
                ],
            ),
            Segment(
                id=2,
                start=3.0,
                end=5.0,
                text="Hello world",
                words=[Word("Hello", 3.0, 3.8), Word("world", 3.8, 5.0)],
            ),
        ]
    )


def single_segment(start: float, end: float, text: str) -> TranscriptionResult:
    return make_result([Segment(id=1, start=start, end=end, text=text)])


# ---------------------------------------------------------------------------
# SRT
# ---------------------------------------------------------------------------


def test_srt_golden_two_segments():
    out = export_srt(two_segment_result())
    assert out == (
        "1\n"
        "00:00:00,000 --> 00:00:02,500\n"
        "你好，世界！\n"
        "\n"
        "2\n"
        "00:00:03,000 --> 00:00:05,000\n"
        "Hello world\n"
        "\n"
    )


def test_srt_millisecond_formatting():
    out = export_srt(single_segment(0.4, 3661.2, "x"))
    assert "00:00:00,400 --> 01:01:01,200" in out


def test_srt_rounding_carries_into_next_unit():
    out = export_srt(single_segment(59.9996, 60.0, "x"))
    assert "00:01:00,000 --> 00:01:00,000" in out


def test_srt_newline_collapsed_to_space():
    out = export_srt(single_segment(0.0, 1.0, "line1\nline2"))
    assert "line1 line2" in out


def test_srt_empty_result():
    assert export_srt(make_result()) == ""


# ---------------------------------------------------------------------------
# VTT
# ---------------------------------------------------------------------------


def test_vtt_header_and_blocks():
    out = export_vtt(two_segment_result())
    assert out.startswith("WEBVTT\n\n")
    assert "00:00:00.000 --> 00:00:02.500\n你好，世界！\n\n" in out
    assert "00:00:03.000 --> 00:00:05.000\nHello world\n\n" in out


def test_vtt_dot_milliseconds():
    out = export_vtt(single_segment(0.4, 3661.2, "x"))
    assert "00:00:00.400 --> 01:01:01.200" in out


def test_vtt_no_cue_numbers():
    out = export_vtt(two_segment_result())
    assert not re.search(r"^\d+$", out, flags=re.MULTILINE)


def test_vtt_newline_collapsed_to_space():
    out = export_vtt(single_segment(0.0, 1.0, "a\nb"))
    assert "a b" in out


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------


def test_text_with_punctuation():
    out = export_text(two_segment_result())
    assert out == "你好，世界！\nHello world\n"


def test_text_without_punctuation_strips_cjk_and_latin():
    out = export_text(two_segment_result(), include_punctuation=False)
    assert out == "你好世界\nHello world\n"


def test_text_without_punctuation_strips_interior_and_collapses_spaces():
    out = export_text(
        single_segment(0.0, 1.0, "a。b，c  d…e！f?g"),
        include_punctuation=False,
    )
    assert out == "abc defg\n"


def test_text_trailing_newline():
    out = export_text(single_segment(0.0, 1.0, "x"))
    assert out.endswith("\n")


def test_text_empty_result():
    assert export_text(make_result()) == "\n"


# ---------------------------------------------------------------------------
# ASS
# ---------------------------------------------------------------------------


def test_ass_style_line_fields():
    out = export_ass(two_segment_result())
    style_line = next(line for line in out.splitlines() if line.startswith("Style: "))
    assert style_line == (
        "Style: Default,Noto Sans CJK TC,64,&H00FFFFFF,&H00FFFFFF,"
        "&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,1,2,40,40,40,1"
    )


def test_ass_format_lines():
    out = export_ass(two_segment_result())
    assert "[Script Info]" in out
    assert "ScriptType: v4.00+" in out
    assert "PlayResX: 1920" in out and "PlayResY: 1080" in out
    assert "WrapStyle: 0" in out
    assert "[V4+ Styles]" in out
    assert "[Events]" in out
    assert (
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text" in out
    )


def test_ass_color_conversion():
    assert ass_color("#FFFFFF") == "&H00FFFFFF"
    assert ass_color("#FF8800") == "&H000088FF"  # BGR byte order
    assert ass_color("#000000") == "&H00000000"
    assert ass_color("#a1b2c3") == "&H00C3B2A1"  # lowercase input


@pytest.mark.parametrize("bad", ["", "FFFFFF", "#FFF", "#GGGGGG", "#12345", None, 42])
def test_ass_color_rejects_malformed(bad):
    with pytest.raises(ExportError):
        ass_color(bad)


def test_ass_time_format_h_mm_ss_cc():
    out = export_ass(single_segment(0.4, 3661.2, "x"))
    assert "Dialogue: 0,0:00:00.40,1:01:01.20,Default,,0,0,0,,x" in out


def test_ass_karaoke_tags_with_centisecond_durations():
    out = export_ass(two_segment_result(), karaoke=True)
    assert (
        "Dialogue: 0,0:00:00.00,0:00:02.50,Default,,0,0,0,,"
        "{\\k100}你好{\\k20}，{\\k100}世界{\\k30}！" in out
    )
    assert "{\\k80}Hello{\\k120}world" in out


def test_ass_karaoke_min_duration_one():
    result = make_result(
        [
            Segment(
                id=1,
                start=0.0,
                end=1.0,
                text="ab",
                words=[Word("a", 0.0, 0.0), Word("b", 0.5, 1.0)],
            )
        ]
    )
    out = export_ass(result, karaoke=True)
    assert "{\\k1}a{\\k50}b" in out


def test_ass_plain_mode_has_no_karaoke_tags():
    out = export_ass(two_segment_result(), karaoke=False)
    assert "{\\k" not in out
    assert "Dialogue: 0,0:00:00.00,0:00:02.50,Default,,0,0,0,,你好，世界！" in out


def test_ass_karaoke_falls_back_to_plain_without_words():
    result = single_segment(0.0, 1.0, "no words")
    out = export_ass(result, karaoke=True)
    assert "no words" in out and "{\\k" not in out


def test_ass_escapes_braces_and_newlines():
    result = single_segment(0.0, 1.0, "a{b}c\nd")
    out = export_ass(result)
    assert "a\\{b\\}c\\Nd" in out


def test_ass_custom_style():
    style = AssStyle(
        style_name="Top",
        font_name="Arial",
        font_size=48,
        primary_color="#FF8800",
        outline_color="#112233",
        bold=True,
        alignment=8,
    )
    out = export_ass(single_segment(0.0, 1.0, "x"), style=style)
    expected_style = (
        "Style: Top,Arial,48,&H000088FF,&H000088FF,&H00332211,&H00000000,"
        "1,0,0,0,100,100,0,0,1,2,1,8,40,40,40,1"
    )
    assert expected_style in out
    assert "Dialogue: 0,0:00:00.00,0:00:01.00,Top,,0,0,0,,x" in out


def test_ass_default_style_object():
    style = AssStyle()
    assert style.style_name == "Default"
    assert style.font_size == 64
    assert style.alignment == 2


# ---------------------------------------------------------------------------
# FCPXML
# ---------------------------------------------------------------------------


def test_fcpxml_parses_and_has_declaration():
    out = export_fcpxml(two_segment_result())
    assert out.startswith('<?xml version="1.0" encoding="UTF-8"?>\n')
    root = ET.fromstring(out)
    assert root.tag == "fcpxml"
    assert root.get("version") == "1.10"


def test_fcpxml_resources():
    root = ET.fromstring(export_fcpxml(two_segment_result(), media_name="clip.mp4"))
    resources = root.find("resources")
    assert resources is not None
    fmt = resources.find("format")
    assert fmt is not None
    assert fmt.get("id") == "r0"
    assert fmt.get("name") == "FFVideoFormat1080p30"
    assert fmt.get("frameDuration") == "100/3000s"
    assert fmt.get("width") == "1920" and fmt.get("height") == "1080"
    asset = resources.find("asset")
    assert asset is not None
    assert asset.get("id") == "r1"
    assert asset.get("name") == "clip.mp4"
    assert asset.get("src") == "file:///clip.mp4"
    assert asset.get("duration") == "5s"  # last segment end, no media_duration
    assert asset.get("format") == "r0"
    text_def = resources.find("def")
    assert text_def is not None and text_def.get("id") == "r2"
    tsd = text_def.find("text-style-def")
    assert tsd is not None and tsd.get("id") == "r3"
    ts = tsd.find("text-style")
    assert ts is not None
    assert ts.get("font") == "Helvetica"
    assert ts.get("fontSize") == "96"
    assert ts.get("fontColor") == "1 1 1 1"


def test_fcpxml_spine_asset_clip_and_titles():
    root = ET.fromstring(export_fcpxml(two_segment_result()))
    spine = root.find("library/event/project/sequence/spine")
    assert spine is not None
    children = list(spine)
    assert children[0].tag == "asset-clip"
    assert children[0].get("ref") == "r1"
    assert children[0].get("offset") == "0s"
    titles = [c for c in children[1:] if c.tag == "title"]
    assert len(titles) == 2
    for title, seg in zip(titles, two_segment_result().segments, strict=True):
        assert title.get("ref") == "r2"
        assert title.get("start") == "0s"
        text_style = title.find("text/text-style")
        assert text_style is not None
        assert text_style.get("ref") == "r3"
        assert text_style.text == seg.text


def test_fcpxml_title_offsets_and_durations():
    root = ET.fromstring(export_fcpxml(two_segment_result()))
    spine = root.find("library/event/project/sequence/spine")
    titles = [c for c in list(spine) if c.tag == "title"]
    assert titles[0].get("offset") == "0s"
    assert titles[0].get("duration") == "2.5s"
    assert titles[1].get("offset") == "3s"
    assert titles[1].get("duration") == "2s"


def test_fcpxml_durations_are_valid_second_strings():
    result = make_result(two_segment_result().segments, media_duration=12.5)
    out = export_fcpxml(result)
    for value in re.findall(r'(?:duration|offset)="([^"]+)"', out):
        assert re.fullmatch(r"\d+(\.\d+)?s", value), value


def test_fcpxml_uses_media_duration_for_total():
    result = make_result(two_segment_result().segments, media_duration=12.5)
    out = export_fcpxml(result)
    root = ET.fromstring(out)
    assert root.find("resources/asset").get("duration") == "12.5s"
    seq = root.find("library/event/project/sequence")
    assert seq.get("duration") == "12.5s"
    assert root.find("library/event/project/sequence/spine/asset-clip").get("duration") == "12.5s"


def test_fcpxml_min_duration_clamp():
    result = make_result([Segment(id=1, start=0.0, end=0.0, text="x")])
    root = ET.fromstring(export_fcpxml(result))
    title = root.find("library/event/project/sequence/spine/title")
    assert title.get("duration") == "0.04s"


def test_fcpxml_escapes_xml_entities():
    result = single_segment(0.0, 1.0, "a < b & c > d")
    root = ET.fromstring(export_fcpxml(result))
    text_style = root.find("library/event/project/sequence/spine/title/text/text-style")
    assert text_style.text == "a < b & c > d"


def test_fcpxml_frame_rate_adjusts_frame_duration():
    root = ET.fromstring(export_fcpxml(two_segment_result(), frame_rate=25))
    assert root.find("resources/format").get("frameDuration") == "100/2500s"


def test_fcpxml_custom_dimensions_and_font():
    root = ET.fromstring(
        export_fcpxml(two_segment_result(), width=1280, height=720, font_size=48)
    )
    fmt = root.find("resources/format")
    assert fmt.get("width") == "1280" and fmt.get("height") == "720"
    ts = root.find("resources/def/text-style-def/text-style")
    assert ts.get("fontSize") == "48"


@pytest.mark.parametrize(
    "kwargs",
    [{"frame_rate": 0}, {"width": -1}, {"height": 0}, {"font_size": -5}],
)
def test_fcpxml_rejects_non_positive_params(kwargs):
    with pytest.raises(ExportError):
        export_fcpxml(two_segment_result(), **kwargs)


def test_fcpxml_project_uid_is_uuid():
    out = export_fcpxml(two_segment_result())
    uid = ET.fromstring(out).find("library/event/project").get("uid")
    uuid.UUID(uid)  # raises ValueError if malformed


def test_fcpxml_empty_result():
    root = ET.fromstring(export_fcpxml(make_result()))
    spine = root.find("library/event/project/sequence/spine")
    assert [c.tag for c in list(spine)] == ["asset-clip"]
