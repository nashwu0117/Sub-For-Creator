"""Tests for LLM transcript correction.

httpx is faked via ``sys.modules`` injection so no network connection is ever
attempted. The graceful-degradation contract (any failure returns the input
segments unchanged) is the core behavior under test.
"""

from __future__ import annotations

import json
import sys
import types

from app.core.llm_correction import (
    LLMConfig,
    _apply_corrections,
    _build_messages,
    _extract_json,
    correct_transcript,
)
from app.core.models import Segment


def make_segments() -> list[Segment]:
    return [
        Segment(id=0, start=0.0, end=1.0, text="今天天氣真好"),
        Segment(id=1, start=1.0, end=2.0, text="我們去公園"),
    ]


class _FakeHTTPError(Exception):
    pass


class _FakeResponse:
    def __init__(self, json_data, status=200):
        self._json = json_data
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise _FakeHTTPError(f"HTTP {self.status}")
        return None

    def json(self):
        return self._json


class _FakeClient:
    def __init__(self, responses, captured):
        self.responses = list(responses)
        self.captured = captured

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, json=None, headers=None):
        self.captured["url"] = url
        self.captured["payload"] = json
        self.captured["headers"] = headers
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _install_fake_httpx(monkeypatch, responses, captured):
    httpx_mod = types.ModuleType("httpx")
    httpx_mod.Client = lambda **kwargs: _FakeClient(responses, captured)
    httpx_mod.ConnectError = type("ConnectError", (Exception,), {})
    httpx_mod.HTTPStatusError = _FakeHTTPError
    monkeypatch.setitem(sys.modules, "httpx", httpx_mod)


# --- LLMConfig -------------------------------------------------------------


def test_llm_config_defaults():
    cfg = LLMConfig()
    assert cfg.provider == "ollama"
    assert cfg.model == "qwen2.5:7b"
    assert cfg.url == "http://localhost:11434"
    assert cfg.api_key is None
    assert cfg.timeout_seconds == 120.0


# --- correct_transcript ----------------------------------------------------


def test_correct_transcript_empty_segments_returns_unchanged():
    assert correct_transcript([], config=LLMConfig()) == []


def test_correct_transcript_ollama_applies_corrections(monkeypatch):
    captured: dict = {}
    content = json.dumps({"segments": [{"id": 0, "text": "今天天氣真好（修正）"}]})
    _install_fake_httpx(
        monkeypatch, [_FakeResponse({"message": {"content": content}})], captured
    )

    result = correct_transcript(
        make_segments(),
        config=LLMConfig(),
        dictionary_terms=["OpenAI"],
    )

    assert result[0].text == "今天天氣真好（修正）"
    assert result[1].text == "我們去公園"  # untouched segment
    assert captured["url"] == "http://localhost:11434/api/chat"
    payload = captured["payload"]
    assert payload["model"] == "qwen2.5:7b"
    assert payload["stream"] is False
    assert payload["format"] == "json"
    assert payload["options"] == {"temperature": 0}
    assert payload["messages"][0]["role"] == "system"
    assert "詞彙表" in payload["messages"][0]["content"]
    assert "OpenAI" in payload["messages"][0]["content"]


def test_correct_transcript_openai_provider(monkeypatch):
    captured: dict = {}
    content = json.dumps({"segments": [{"id": 1, "text": "修正後"}]})
    _install_fake_httpx(
        monkeypatch,
        [_FakeResponse({"choices": [{"message": {"content": content}}]})],
        captured,
    )

    result = correct_transcript(
        make_segments(),
        config=LLMConfig(provider="openai", api_key="secret", url="http://llm/v1"),
    )

    assert result[1].text == "修正後"
    assert captured["url"] == "http://llm/v1/chat/completions"
    assert captured["headers"] == {"Authorization": "Bearer secret"}
    payload = captured["payload"]
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["temperature"] == 0


def test_correct_transcript_openai_requires_api_key(monkeypatch):
    captured: dict = {}
    _install_fake_httpx(monkeypatch, [], captured)
    segments = make_segments()

    result = correct_transcript(
        segments, config=LLMConfig(provider="openai", api_key=None)
    )

    assert result == segments  # graceful degradation
    assert captured == {}  # no HTTP call was made


def test_correct_transcript_unknown_provider_degrades(monkeypatch):
    captured: dict = {}
    _install_fake_httpx(monkeypatch, [], captured)
    segments = make_segments()

    result = correct_transcript(segments, config=LLMConfig(provider="gemini"))

    assert result == segments
    assert captured == {}


def test_correct_transcript_connection_failure_degrades(monkeypatch):
    captured: dict = {}
    _install_fake_httpx(monkeypatch, [ConnectionError("refused")], captured)
    segments = make_segments()

    result = correct_transcript(segments, config=LLMConfig())

    assert result == segments
    assert captured["url"] == "http://localhost:11434/api/chat"


def test_correct_transcript_http_error_degrades(monkeypatch):
    captured: dict = {}
    _install_fake_httpx(monkeypatch, [_FakeResponse({}, status=500)], captured)
    segments = make_segments()

    result = correct_transcript(segments, config=LLMConfig())

    assert result == segments


def test_correct_transcript_malformed_json_degrades(monkeypatch):
    captured: dict = {}
    _install_fake_httpx(
        monkeypatch, [_FakeResponse({"message": {"content": "not json at all"}})], captured
    )
    segments = make_segments()

    result = correct_transcript(segments, config=LLMConfig())

    assert result == segments


def test_correct_transcript_missing_segments_list_degrades(monkeypatch):
    captured: dict = {}
    _install_fake_httpx(
        monkeypatch, [_FakeResponse({"message": {"content": '{"foo": 1}'}})], captured
    )
    segments = make_segments()

    result = correct_transcript(segments, config=LLMConfig())

    assert result == segments


def test_correct_transcript_skips_invalid_items(monkeypatch):
    captured: dict = {}
    segments = [
        Segment(id=0, start=0.0, end=1.0, text="今天天氣真好"),
        Segment(id=1, start=1.0, end=2.0, text="我們去公園"),
        Segment(id=2, start=2.0, end=3.0, text="字幕工具真方便"),
        Segment(id=3, start=3.0, end=4.0, text="希望你能喜歡"),
    ]
    content = json.dumps(
        {
            "segments": [
                {"id": 0, "text": "修正A"},
                {"id": True, "text": "bool-id-skipped"},
                {"id": "1", "text": "str-id-skipped"},
                {"id": 2, "text": 123},
                "not-a-dict",
                {"id": 3, "text": "修正B"},
            ]
        }
    )
    _install_fake_httpx(
        monkeypatch, [_FakeResponse({"message": {"content": content}})], captured
    )

    result = correct_transcript(segments, config=LLMConfig())

    assert result[0].text == "修正A"
    assert result[1].text == "我們去公園"  # invalid ids/texts are skipped
    assert result[2].text == "字幕工具真方便"
    assert result[3].text == "修正B"


# --- _build_messages -------------------------------------------------------


def test_build_messages_shape():
    messages = _build_messages(make_segments(), None)
    assert [m["role"] for m in messages] == ["system", "user"]
    user = json.loads(messages[1]["content"])
    assert user == [{"id": 0, "text": "今天天氣真好"}, {"id": 1, "text": "我們去公園"}]


def test_build_messages_includes_dictionary_terms():
    messages = _build_messages(make_segments(), ["OpenAI", "WhisperX"])
    assert "詞彙表：OpenAI, WhisperX" in messages[0]["content"]


# --- _extract_json ---------------------------------------------------------


def test_extract_json_plain():
    assert _extract_json('{"segments": []}') == {"segments": []}


def test_extract_json_markdown_fenced():
    assert _extract_json('```json\n{"segments": []}\n```') == {"segments": []}


def test_extract_json_with_noise():
    assert _extract_json('Here you go: {"segments": []} thanks!') == {"segments": []}


def test_extract_json_garbage_returns_none():
    assert _extract_json("no json here") is None
    assert _extract_json("[1, 2, 3]") is None  # not an object


# --- _apply_corrections ----------------------------------------------------


def test_apply_corrections_returns_new_list():
    segments = make_segments()
    result = _apply_corrections(segments, {0: "新文字"})
    assert result is not segments
    assert result[0].text == "新文字"
    assert segments[0].text == "今天天氣真好"  # original untouched


def test_apply_corrections_guards_bad_values():
    segments = make_segments()
    result = _apply_corrections(segments, {0: "", 1: "x" * 100})
    assert result[0].text == "今天天氣真好"  # empty correction ignored
    assert result[1].text == "我們去公園"  # oversized correction ignored
