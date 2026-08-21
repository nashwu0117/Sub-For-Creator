"""Serialization between Segment/Word dataclasses and the DB ``segments_json``.

Canonical word dict key is ``text`` (per the API contract); ``word`` is
accepted as an input alias for forward-compatibility with clients that send
the docs/API.md example shape.
"""

from __future__ import annotations

import json

from app.core.models import Segment, Word


def segments_to_json(segments: list[Segment]) -> str:
    """Serialize segments (with words) to the JSON string stored on the Job."""
    payload = []
    for seg in segments:
        item: dict = {
            "id": seg.id,
            "start": seg.start,
            "end": seg.end,
            "text": seg.text,
            "words": [{"text": w.text, "start": w.start, "end": w.end} for w in seg.words],
        }
        if seg.x is not None or seg.y is not None:
            item["x"] = seg.x
            item["y"] = seg.y
        payload.append(item)
    return json.dumps(payload, ensure_ascii=False)


def json_to_segments(raw: str) -> list[Segment]:
    """Parse a stored ``segments_json`` string back into Segment objects."""
    payload = json.loads(raw)
    segments: list[Segment] = []
    for item in payload:
        words: list[Word] = []
        for w in item.get("words") or []:
            text = w.get("text") or w.get("word") or ""
            words.append(Word(text=text, start=float(w["start"]), end=float(w["end"])))
        segments.append(
            Segment(
                id=int(item["id"]),
                start=float(item["start"]),
                end=float(item["end"]),
                text=item["text"],
                words=words,
                x=item.get("x"),
                y=item.get("y"),
            )
        )
    return segments
