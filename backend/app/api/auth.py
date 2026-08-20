"""Optional account system: register / login / logout / me.

Auth mechanism: an HTTP-only cookie (``SameSite=Lax``, ``Secure`` behind
``SFC_AUTH_COOKIE_SECURE``) holding a stateless HMAC-SHA256-signed
``{user_id}.{expiry}.{digest}`` value. Cookies are chosen over Bearer tokens
because the browser sends them automatically on every request (including the
``<video>``/wavesurfer fetches that cannot set headers), and the value never
touches ``localStorage``, which is XSS-readable. Passwords are hashed with
stdlib ``hashlib.pbkdf2_hmac`` + a per-user random salt — zero new
dependencies.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import _sign_session_cookie, current_user
from app.config import Settings, get_settings
from app.database import get_db
from app.models.db import User

router = APIRouter()

#: PBKDF2-HMAC-SHA256 iterations (OWASP recommendation for 2023+)
PBKDF2_ITERATIONS = 600_000

#: deliberately simple: local-part@domain.tld, no exotic addresses
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MAX_EMAIL_LEN = 255
MAX_PASSWORD_LEN = 128
MIN_PASSWORD_LEN = 8
MAX_DISPLAY_NAME_LEN = 64


class RegisterIn(BaseModel):
    """POST /api/auth/register body."""

    email: str
    password: str
    display_name: str | None = None


class LoginIn(BaseModel):
    """POST /api/auth/login body."""

    email: str
    password: str


def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 with a fresh 16-byte salt; format ``algo$iter$salt$hash``."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of ``password`` against a stored hash string."""
    try:
        algo, iterations, salt_hex, digest_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, AttributeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations))
    return hmac.compare_digest(actual, expected)


def _user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _set_auth_cookie(response: Response, user_id: int, settings: Settings) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=_sign_session_cookie(user_id, settings),
        max_age=settings.auth_session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.auth_cookie_secure,
        path="/",
    )


@router.post("/auth/register", status_code=201)
def register(payload: RegisterIn, db: Session = Depends(get_db)) -> dict:
    """Create an account. Email is trimmed/lowercased; duplicates get 409."""
    email = payload.email.strip().lower()
    if not email or len(email) > MAX_EMAIL_LEN or not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="invalid email address")
    if not MIN_PASSWORD_LEN <= len(payload.password) <= MAX_PASSWORD_LEN:
        raise HTTPException(
            status_code=422,
            detail=f"password must be {MIN_PASSWORD_LEN}-{MAX_PASSWORD_LEN} characters",
        )
    display_name = (payload.display_name or "").strip() or email.split("@")[0]
    if len(display_name) > MAX_DISPLAY_NAME_LEN:
        raise HTTPException(
            status_code=422, detail="display name must be at most 64 characters"
        )
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="email already registered")
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        display_name=display_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_payload(user)


@router.post("/auth/login")
def login(payload: LoginIn, response: Response, db: Session = Depends(get_db)) -> dict:
    """Verify credentials and set the HTTP-only session cookie."""
    email = payload.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid email or password")
    _set_auth_cookie(response, user.id, get_settings())
    return _user_payload(user)


@router.post("/auth/logout")
def logout(
    response: Response,
    settings: Settings = Depends(get_settings),
) -> dict:
    """Clear the session cookie (idempotent; works without being logged in)."""
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.auth_cookie_secure,
    )
    return {"ok": True}


@router.get("/auth/me")
def me(user: User | None = Depends(current_user)) -> dict:
    """Return the current user, or 401 when not authenticated."""
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return _user_payload(user)
