"""LLM-based transcript correction (homophone errors, glossary unification).

Graceful degradation: any failure (network, parse, validation) logs a warning
and returns the input segments unchanged — this feature must never break a job.
httpx is imported lazily so the module (and the test suite) never needs network
or an LLM server at import time.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
from dataclasses import dataclass

from .models import Segment

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "你是字幕校正助手。只修正同音錯字，並統一專有名詞的寫法。"
    "不改變語意、不增刪句子、不做摘要。"
    "逐字稿中若出現與詞彙表相同的概念，請統一使用詞彙表的寫法。"
)


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "ollama"  # "ollama" | "openai"
    model: str = "qwen2.5:7b"
    url: str = "http://localhost:11434"
    api_key: str | None = None
    timeout_seconds: float = 120.0


def _build_messages(
    segments: list[Segment], dictionary_terms: list[str] | None
) -> list[dict[str, str]]:
    system = SYSTEM_PROMPT
    if dictionary_terms:
        system += "\n詞彙表：" + ", ".join(dictionary_terms)
    user = json.dumps(
        [{"id": seg.id, "text": seg.text} for seg in segments],
        ensure_ascii=False,
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _extract_json(text: str) -> dict | None:
    """Parse a JSON object from LLM output, tolerating markdown fences and noise."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(cleaned[start : end + 1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return None


def _apply_corrections(
    segments: list[Segment], corrections: dict[int, str]
) -> list[Segment]:
    """Return a NEW list of segments; only ``text`` may change."""
    result: list[Segment] = []
    for seg in segments:
        corrected = corrections.get(seg.id)
        if corrected is None or not corrected or len(corrected) > len(seg.text) * 3:
            result.append(dataclasses.replace(seg, text=seg.text))
        else:
            result.append(dataclasses.replace(seg, text=corrected))
    return result


def correct_transcript(
    segments: list[Segment],
    *,
    config: LLMConfig,
    dictionary_terms: list[str] | None = None,
) -> list[Segment]:
    """Correct homophone errors via an LLM; original segments on any failure."""
    if not segments:
        return segments
    try:
        import httpx

        messages = _build_messages(segments, dictionary_terms)
        if config.provider == "ollama":
            url = config.url.rstrip("/") + "/api/chat"
            payload: dict[str, object] = {
                "model": config.model,
                "messages": messages,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0},
            }
            headers = None
        elif config.provider == "openai":
            if config.api_key is None:
                raise ValueError("LLMConfig.api_key is required for the openai provider")
            url = config.url
            if not url.endswith("/chat/completions"):
                url = url.rstrip("/") + "/chat/completions"
            payload = {
                "model": config.model,
                "messages": messages,
                "temperature": 0,
                "response_format": {"type": "json_object"},
            }
            headers = {"Authorization": f"Bearer {config.api_key}"}
        else:
            raise ValueError(
                f"unknown LLM provider {config.provider!r}; expected 'ollama' or 'openai'"
            )

        with httpx.Client(timeout=config.timeout_seconds) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        if config.provider == "ollama":
            content = data.get("message", {}).get("content")
        else:
            choices = data.get("choices") or []
            content = choices[0].get("message", {}).get("content") if choices else None
        if not content:
            raise ValueError("LLM response contained no assistant content")

        parsed = _extract_json(content)
        if parsed is None:
            raise ValueError("could not parse LLM JSON output")
        items = parsed.get("segments")
        if not isinstance(items, list):
            raise ValueError("LLM output missing 'segments' list")

        corrections: dict[int, str] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            text = item.get("text")
            if isinstance(item_id, bool) or not isinstance(item_id, int):
                continue
            if not isinstance(text, str):
                continue
            corrections[item_id] = text
        return _apply_corrections(segments, corrections)
    except Exception as exc:  # noqa: BLE001 - graceful degradation is the contract
        logger.warning("LLM correction failed, keeping original transcript: %s", exc)
        return segments
