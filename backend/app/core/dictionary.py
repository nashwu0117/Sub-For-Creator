"""User dictionary: persistent term list for initial_prompt + LLM correction.

The dictionary is a JSON file shaped ``{"terms": [...]}``. File problems never
raise — they log a warning and degrade to an empty list so the transcription
pipeline keeps running.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

MAX_TERM_LENGTH = 100


def load_terms(path: str) -> list[str]:
    """Read ``{"terms": [...]}`` from ``path``; [] + warning on any file problem."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("could not load dictionary %r: %s", path, exc)
        return []
    if not isinstance(data, dict) or not isinstance(data.get("terms"), list):
        logger.warning(
            "dictionary %r has unexpected shape; expected {\"terms\": [...]}", path
        )
        return []
    return [term for term in data["terms"] if isinstance(term, str)]


def save_terms(path: str, terms: list[str]) -> None:
    """Atomically write ``{"terms": [...]}`` (ensure_ascii=False, indent=2)."""
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".dictionary-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"terms": terms}, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _normalize_term(term: str) -> str | None:
    """Strip, drop empties/control chars, cap at MAX_TERM_LENGTH; None if invalid."""
    term = term.strip()
    if not term:
        return None
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in term):
        return None
    return term[:MAX_TERM_LENGTH]


def add_terms(path: str, terms: list[str]) -> list[str]:
    """Add normalized terms (case-insensitive dedupe) and persist; return new ones."""
    existing = load_terms(path)
    existing_lower = {term.casefold() for term in existing}
    added: list[str] = []
    for term in terms:
        normalized = _normalize_term(term)
        if normalized is None or normalized.casefold() in existing_lower:
            continue
        existing.append(normalized)
        existing_lower.add(normalized.casefold())
        added.append(normalized)
    if added:
        save_terms(path, existing)
    return added


def remove_term(path: str, term: str) -> bool:
    """Remove one term (case-insensitive); persist and return True if present."""
    existing = load_terms(path)
    target = term.strip().casefold()
    remaining = [t for t in existing if t.casefold() != target]
    if len(remaining) == len(existing):
        return False
    save_terms(path, remaining)
    return True


def build_initial_prompt(terms: list[str], max_chars: int = 1500) -> str | None:
    """Join terms with ', ', keeping whole terms while under ``max_chars``.

    Returns None when there are no usable terms.
    """
    parts: list[str] = []
    used = 0
    for term in terms:
        term = term.strip()
        if not term:
            continue
        sep = ", " if parts else ""
        if used + len(sep) + len(term) > max_chars:
            break
        parts.append(term)
        used += len(sep) + len(term)
    if not parts:
        return None
    return ", ".join(parts)
