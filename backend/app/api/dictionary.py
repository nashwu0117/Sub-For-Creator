"""GET/POST/DELETE /api/dictionary — manage the custom-terms dictionary.

The dictionary is a plain text file (one term per line) consumed by the worker
to build the ASR ``initial_prompt`` and to bias LLM correction.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import session_token
from app.config import Settings, get_settings
from app.core import add_terms, load_terms, remove_term
from app.schemas import DictionaryAdd, DictionaryRemove

router = APIRouter()


def _clean_term(term: str) -> str:
    """Strip and validate a single dictionary term (1..100 chars, no control chars)."""
    cleaned = term.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail="term must not be empty")
    if len(cleaned) > 100:
        raise HTTPException(status_code=422, detail="term must be at most 100 characters")
    if any(ord(ch) < 32 or ch in "\n\r\t" for ch in cleaned):
        raise HTTPException(
            status_code=422, detail="term must not contain control characters or newlines"
        )
    return cleaned


@router.get("/dictionary")
def get_dictionary(
    token: str = Depends(session_token),
    settings: Settings = Depends(get_settings),
) -> dict:
    return {"terms": load_terms(settings.dictionary_path)}


@router.post("/dictionary")
def post_dictionary(
    payload: DictionaryAdd,
    token: str = Depends(session_token),
    settings: Settings = Depends(get_settings),
) -> dict:
    if not payload.terms:
        raise HTTPException(status_code=422, detail="terms must be a non-empty list")
    cleaned = [_clean_term(term) for term in payload.terms]
    added = add_terms(settings.dictionary_path, cleaned)
    return {"terms": load_terms(settings.dictionary_path), "added": added}


@router.delete("/dictionary")
def delete_dictionary(
    payload: DictionaryRemove,
    token: str = Depends(session_token),
    settings: Settings = Depends(get_settings),
) -> dict:
    term = _clean_term(payload.term)
    remove_term(settings.dictionary_path, term)
    return {"ok": True}
