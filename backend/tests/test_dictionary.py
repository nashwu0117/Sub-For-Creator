"""Tests for the user dictionary: persistence, normalization, initial_prompt.

All tests operate on real JSON files under ``tmp_path`` — no network, no
external services.
"""

from __future__ import annotations

import json

from app.core.dictionary import (
    MAX_TERM_LENGTH,
    add_terms,
    build_initial_prompt,
    load_terms,
    remove_term,
    save_terms,
)


def _write(path, terms) -> str:
    path.write_text(json.dumps({"terms": terms}, ensure_ascii=False), encoding="utf-8")
    return str(path)


# --- load_terms ------------------------------------------------------------


def test_load_terms_roundtrip(tmp_path):
    path = tmp_path / "dict.json"
    save_terms(str(path), ["OpenAI", "WhisperX"])
    assert load_terms(str(path)) == ["OpenAI", "WhisperX"]


def test_load_terms_missing_file_returns_empty(tmp_path):
    assert load_terms(str(tmp_path / "nope.json")) == []


def test_load_terms_invalid_json_returns_empty(tmp_path):
    path = tmp_path / "dict.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_terms(str(path)) == []


def test_load_terms_wrong_shape_returns_empty(tmp_path):
    path = tmp_path / "dict.json"
    path.write_text(json.dumps({"foo": 1}), encoding="utf-8")
    assert load_terms(str(path)) == []
    path.write_text(json.dumps(["a", "b"]), encoding="utf-8")
    assert load_terms(str(path)) == []


def test_load_terms_filters_non_strings(tmp_path):
    path = tmp_path / "dict.json"
    path.write_text(json.dumps({"terms": ["ok", 42, None, {"x": 1}]}), encoding="utf-8")
    assert load_terms(str(path)) == ["ok"]


# --- save_terms ------------------------------------------------------------


def test_save_terms_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "dir" / "dict.json"
    save_terms(str(path), ["術語"])
    assert path.exists()
    assert load_terms(str(path)) == ["術語"]


def test_save_terms_writes_utf8_indented(tmp_path):
    path = tmp_path / "dict.json"
    save_terms(str(path), ["術語"])
    content = path.read_text(encoding="utf-8")
    assert "術語" in content  # ensure_ascii=False keeps CJK readable
    assert '"terms"' in content
    assert content.endswith("\n")


# --- add_terms -------------------------------------------------------------


def test_add_terms_returns_only_new_terms(tmp_path):
    path = _write(tmp_path / "dict.json", ["existing"])
    added = add_terms(path, ["new-one", "existing", "another"])
    assert added == ["new-one", "another"]
    assert load_terms(path) == ["existing", "new-one", "another"]


def test_add_terms_dedupes_case_insensitively(tmp_path):
    path = _write(tmp_path / "dict.json", ["OpenAI"])
    assert add_terms(path, ["openai", "OPENAI"]) == []
    assert load_terms(path) == ["OpenAI"]


def test_add_terms_normalizes_terms(tmp_path):
    path = _write(tmp_path / "dict.json", [])
    added = add_terms(path, ["  spaced  ", "\t", "ctrl\x01char", "x" * 200])
    assert added == ["spaced", "x" * MAX_TERM_LENGTH]
    assert load_terms(path) == ["spaced", "x" * MAX_TERM_LENGTH]


def test_add_terms_skips_save_when_nothing_added(monkeypatch, tmp_path):
    path = _write(tmp_path / "dict.json", ["existing"])
    saved: list = []
    monkeypatch.setattr(
        "app.core.dictionary.save_terms", lambda p, terms: saved.append((p, terms))
    )
    assert add_terms(path, ["existing", "  "]) == []
    assert saved == []


# --- remove_term -----------------------------------------------------------


def test_remove_term_removes_case_insensitively(tmp_path):
    path = _write(tmp_path / "dict.json", ["OpenAI", "WhisperX"])
    assert remove_term(path, "openai") is True
    assert load_terms(path) == ["WhisperX"]


def test_remove_term_absent_returns_false(tmp_path):
    path = _write(tmp_path / "dict.json", ["OpenAI"])
    assert remove_term(path, "nope") is False
    assert load_terms(path) == ["OpenAI"]


# --- build_initial_prompt --------------------------------------------------


def test_build_initial_prompt_joins_terms():
    assert build_initial_prompt(["OpenAI", "WhisperX"]) == "OpenAI, WhisperX"


def test_build_initial_prompt_none_when_empty():
    assert build_initial_prompt([]) is None
    assert build_initial_prompt(["  ", ""]) is None


def test_build_initial_prompt_respects_max_chars():
    prompt = build_initial_prompt(["aaaa", "bbbb", "cccc"], max_chars=11)
    # "aaaa, bbbb" = 9 chars; adding ", cccc" would exceed 11
    assert prompt == "aaaa, bbbb"


def test_build_initial_prompt_skips_blank_terms():
    assert build_initial_prompt(["OpenAI", "  ", "WhisperX"]) == "OpenAI, WhisperX"
