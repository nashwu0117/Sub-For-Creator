"""Integration tests for the optional account system (register/login/logout/me)."""

from __future__ import annotations

from app.database import SessionLocal
from app.models.db import User

COOKIE = "sfc_session"


def _register(client, email: str, password: str = "password123") -> dict:
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "display_name": "Tester"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _login(client, email: str, password: str = "password123") -> dict:
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_register_creates_account(client):
    body = _register(client, "alice@example.com")
    assert body["email"] == "alice@example.com"
    assert body["display_name"] == "Tester"
    assert body["id"] > 0
    assert body["created_at"]
    # password hash is stored, never the plaintext
    db = SessionLocal()
    user = db.get(User, body["id"])
    assert user.password_hash.startswith("pbkdf2_sha256$")
    assert "password123" not in user.password_hash
    db.close()


def test_register_normalizes_email(client):
    body = _register(client, "  CaroL@Example.COM ")
    assert body["email"] == "carol@example.com"


def test_register_duplicate_email_conflict(client):
    _register(client, "bob@example.com")
    resp = client.post(
        "/api/auth/register", json={"email": "BOB@example.com", "password": "password123"}
    )
    assert resp.status_code == 409


def test_register_invalid_email_rejected(client):
    resp = client.post(
        "/api/auth/register", json={"email": "not-an-email", "password": "password123"}
    )
    assert resp.status_code == 422


def test_register_short_password_rejected(client):
    resp = client.post(
        "/api/auth/register", json={"email": "c@example.com", "password": "short"}
    )
    assert resp.status_code == 422


def test_login_sets_http_only_cookie(client):
    _register(client, "dave@example.com")
    resp = client.post(
        "/api/auth/login", json={"email": "dave@example.com", "password": "password123"}
    )
    assert resp.status_code == 200
    assert client.cookies.get(COOKIE)
    set_cookie = resp.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie


def test_login_wrong_password_rejected(client):
    _register(client, "erin@example.com")
    resp = client.post(
        "/api/auth/login", json={"email": "erin@example.com", "password": "wrong-password"}
    )
    assert resp.status_code == 401


def test_login_unknown_email_rejected(client):
    resp = client.post(
        "/api/auth/login", json={"email": "ghost@example.com", "password": "password123"}
    )
    assert resp.status_code == 401


def test_me_requires_auth(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_me_returns_current_user(client):
    _register(client, "frank@example.com")
    _login(client, "frank@example.com")
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == "frank@example.com"


def test_logout_clears_cookie(client):
    _register(client, "grace@example.com")
    _login(client, "grace@example.com")
    assert client.cookies.get(COOKIE)
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200
    assert client.cookies.get(COOKIE) is None
    assert client.get("/api/auth/me").status_code == 401


def test_me_after_user_deleted_returns_401(client):
    """A cookie whose user row no longer exists must not authenticate."""
    _register(client, "henry@example.com")
    _login(client, "henry@example.com")
    db = SessionLocal()
    user = db.query(User).filter_by(email="henry@example.com").first()
    db.delete(user)
    db.commit()
    db.close()
    assert client.get("/api/auth/me").status_code == 401


def test_tampered_cookie_rejected(client):
    _register(client, "ivy@example.com")
    _login(client, "ivy@example.com")
    cookie = client.cookies.get(COOKIE)
    # flip the last hex digit of the digest
    tampered = cookie[:-1] + ("0" if cookie[-1] != "0" else "1")
    client.cookies.set(COOKIE, tampered)
    assert client.get("/api/auth/me").status_code == 401
