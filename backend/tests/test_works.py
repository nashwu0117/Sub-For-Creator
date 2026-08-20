"""Integration tests for the works collection + job ownership enforcement."""

from __future__ import annotations

import uuid

from app.database import SessionLocal
from app.models.db import Job

COOKIE = "sfc_session"


def _register_and_login(client, email: str) -> None:
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": "Tester"},
    )
    resp = client.post(
        "/api/auth/login", json={"email": email, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text


def _seed_job(token: str = "seed-token", status: str = "done") -> str:
    db = SessionLocal()
    job = Job(
        id=uuid.uuid4().hex,
        session_token=token,
        status=status,
        filename="seed.mp4",
        language="zh",
        model_size="large-v3",
        duration=2.0,
    )
    db.add(job)
    db.commit()
    db.close()
    return job.id


# ------------------------------------------------------------------ works


def test_claim_requires_auth(client):
    job_id = _seed_job()
    resp = client.post(f"/api/works/{job_id}", headers={"X-Session-Token": "seed-token"})
    assert resp.status_code == 401


def test_claim_requires_matching_session(client):
    _register_and_login(client, "alice@example.com")
    job_id = _seed_job(token="other-token")
    resp = client.post(
        f"/api/works/{job_id}", headers={"X-Session-Token": "not-mine-token"}
    )
    assert resp.status_code == 403


def test_claim_and_list(client):
    _register_and_login(client, "bob@example.com")
    job_id = _seed_job()
    resp = client.post(f"/api/works/{job_id}", headers={"X-Session-Token": "seed-token"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["job_id"] == job_id
    assert body["title"] == "seed"
    assert body["job"]["status"] == "done"

    resp = client.get("/api/works")
    assert resp.status_code == 200
    works = resp.json()
    assert [w["job_id"] for w in works] == [job_id]


def test_claim_is_idempotent(client):
    _register_and_login(client, "carol@example.com")
    job_id = _seed_job()
    headers = {"X-Session-Token": "seed-token"}
    first = client.post(f"/api/works/{job_id}", headers=headers)
    second = client.post(f"/api/works/{job_id}", headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_claim_foreign_claimed_job_forbidden(client):
    _register_and_login(client, "dave@example.com")
    job_id = _seed_job()
    client.post(f"/api/works/{job_id}", headers={"X-Session-Token": "seed-token"})
    # a second user cannot claim the same job
    _register_and_login(client, "erin@example.com")
    resp = client.post(f"/api/works/{job_id}", headers={"X-Session-Token": "seed-token"})
    assert resp.status_code == 403


def test_get_work_ownership(client):
    _register_and_login(client, "frank@example.com")
    job_id = _seed_job()
    work = client.post(f"/api/works/{job_id}", headers={"X-Session-Token": "seed-token"}).json()

    resp = client.get(f"/api/works/{work['id']}")
    assert resp.status_code == 200
    assert resp.json()["job_id"] == job_id

    # another user cannot read the work
    _register_and_login(client, "grace@example.com")
    resp = client.get(f"/api/works/{work['id']}")
    assert resp.status_code == 403


def test_delete_work(client):
    _register_and_login(client, "heidi@example.com")
    job_id = _seed_job()
    work = client.post(f"/api/works/{job_id}", headers={"X-Session-Token": "seed-token"}).json()
    resp = client.delete(f"/api/works/{work['id']}")
    assert resp.status_code == 200
    assert client.get("/api/works").json() == []


def test_work_after_job_expired_reports_expired(client):
    _register_and_login(client, "ivan@example.com")
    job_id = _seed_job(status="expired")
    work = client.post(f"/api/works/{job_id}", headers={"X-Session-Token": "seed-token"}).json()
    assert work["job"]["status"] == "expired"


# ------------------------------------------- ownership enforcement (403s)


def test_claimed_job_denies_raw_session_token(client):
    """Once claimed, the job must NOT be accessible via the raw session token."""
    _register_and_login(client, "jane@example.com")
    job_id = _seed_job()
    client.post(f"/api/works/{job_id}", headers={"X-Session-Token": "seed-token"})
    client.cookies.clear()  # drop the owner's auth cookie — raw token only

    resp = client.get(f"/api/jobs/{job_id}", headers={"X-Session-Token": "seed-token"})
    assert resp.status_code == 403


def test_claimed_job_allows_owner_cookie(client):
    _register_and_login(client, "kate@example.com")
    job_id = _seed_job()
    client.post(f"/api/works/{job_id}", headers={"X-Session-Token": "seed-token"})

    resp = client.get(f"/api/jobs/{job_id}", headers={"X-Session-Token": "seed-token"})
    assert resp.status_code == 200
    assert resp.json()["job_id"] == job_id


def test_claimed_job_denies_other_user_cookie(client):
    _register_and_login(client, "lisa@example.com")
    job_id = _seed_job()
    client.post(f"/api/works/{job_id}", headers={"X-Session-Token": "seed-token"})

    _register_and_login(client, "mike@example.com")
    resp = client.get(f"/api/jobs/{job_id}", headers={"X-Session-Token": "seed-token"})
    assert resp.status_code == 403


def test_unclaimed_job_accessible_by_session_token(client):
    """The anonymous flow is unchanged: unclaimed jobs follow the session token."""
    job_id = _seed_job(token="anon-token")
    resp = client.get(f"/api/jobs/{job_id}", headers={"X-Session-Token": "anon-token"})
    assert resp.status_code == 200


def test_claimed_job_denies_subtitles_via_token(client):
    _register_and_login(client, "nina@example.com")
    job_id = _seed_job()
    client.post(f"/api/works/{job_id}", headers={"X-Session-Token": "seed-token"})
    client.cookies.clear()

    resp = client.get(
        f"/api/jobs/{job_id}/subtitles", headers={"X-Session-Token": "seed-token"}
    )
    assert resp.status_code == 403


def test_claimed_job_denies_media_via_token(client):
    _register_and_login(client, "oscar@example.com")
    job_id = _seed_job()
    client.post(f"/api/works/{job_id}", headers={"X-Session-Token": "seed-token"})
    client.cookies.clear()

    resp = client.get(f"/api/jobs/{job_id}/media", headers={"X-Session-Token": "seed-token"})
    assert resp.status_code == 403
