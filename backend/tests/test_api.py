"""Integration tests for the public API: upload -> process -> edit -> export."""

from __future__ import annotations

import io
import json
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile
from datetime import timedelta

import pytest

from app.database import SessionLocal, utcnow
from app.models.db import Job
from tests.helpers import make_video, make_wav, upload, wait_done

TOKEN = "test-token"

pytestmark = pytest.mark.usefixtures("mock_asr")


def _seed_job(
    status: str = "done",
    expires_at=None,
    token: str = "seed-token",
    segments_json: str | None = None,
) -> str:
    db = SessionLocal()
    job = Job(
        id=uuid.uuid4().hex,
        session_token=token,
        status=status,
        filename="seed.mp4",
        language="zh",
        model_size="large-v3",
        duration=2.0,
        segments_json=segments_json,
        expires_at=expires_at,
    )
    db.add(job)
    db.commit()
    db.close()
    return job.id


def _segments_json() -> str:
    return json.dumps(
        [
            {
                "id": 0,
                "start": 0.1,
                "end": 0.6,
                "text": "今天天氣真好",
                "words": [
                    {"text": "今天", "start": 0.1, "end": 0.3},
                    {"text": "天氣", "start": 0.3, "end": 0.5},
                ],
            }
        ],
        ensure_ascii=False,
    )


# ---------------------------------------------------------------- basics


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"


def test_config_endpoint(client):
    resp = client.get("/api/config", headers={"X-Session-Token": TOKEN})
    assert resp.status_code == 200
    body = resp.json()
    assert body["max_upload_mb"] == 10
    assert body["max_duration_min"] == 60
    assert body["max_queue"] == 50
    assert "zh" in body["supported_languages"]
    assert body["tiers"] == ["lite", "standard", "pro"]
    assert body["llm_available"] is True
    assert body["default_options"] == {
        "max_line_chars": 16,
        "model_size": "medium",
        "tier": "standard",
        "denoise_enabled": True,
        "loudnorm_enabled": True,
        "llm_correction_enabled": False,
    }


def test_config_requires_token(client):
    resp = client.get("/api/config")
    assert resp.status_code == 400
    assert "X-Session-Token" in resp.json()["detail"]


def test_upload_requires_token(client, tmp_path):
    wav = make_wav(tmp_path / "a.wav")
    with open(wav, "rb") as fh:
        resp = client.post(
            "/api/jobs",
            files={"file": ("a.wav", fh, "audio/wav")},
        )
    assert resp.status_code == 400
    assert "X-Session-Token" in resp.json()["detail"]


# ---------------------------------------------------------------- happy path


def test_happy_path_wav(client, tmp_path):
    wav = make_wav(tmp_path / "sample.wav")
    resp = upload(client, wav, token=TOKEN, language="zh")
    assert resp.status_code == 202
    body = resp.json()
    assert body["job_id"]
    assert body["status"] in ("queued", "processing", "done")
    job_id = body["job_id"]

    done = wait_done(client, job_id, token=TOKEN)
    assert done["status"] == "done"
    assert done["progress"] == 100
    assert done["stage"] is None
    assert done["expires_at"] is not None
    assert done["meta"]["language"] == "zh"
    assert done["meta"]["filename"] == "sample.wav"
    assert done["meta"]["model_size"] == "medium"
    assert done["meta"]["duration"] > 0

    # subtitles: segments with words
    resp = client.get(f"/api/jobs/{job_id}/subtitles", headers={"X-Session-Token": TOKEN})
    assert resp.status_code == 200
    subs = resp.json()
    assert subs["job_id"] == job_id
    assert subs["language"] == "zh"
    assert subs["meta"] == {"model_size": "medium", "max_line_chars": 16}
    assert len(subs["segments"]) >= 1
    seg = subs["segments"][0]
    assert set(seg) >= {"id", "start", "end", "text", "words"}
    assert seg["start"] < seg["end"]
    assert seg["words"], "mock ASR must produce word timestamps"

    # edit: PUT replaces segments, keeps words for ids not re-sent
    edited = {"segments": [{"id": 0, "start": 0.1, "end": 0.6, "text": "編輯後的字幕"}]}
    resp = client.put(
        f"/api/jobs/{job_id}/subtitles", json=edited, headers={"X-Session-Token": TOKEN}
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    resp = client.get(f"/api/jobs/{job_id}/subtitles", headers={"X-Session-Token": TOKEN})
    assert resp.status_code == 200
    subs = resp.json()
    assert len(subs["segments"]) == 1
    assert subs["segments"][0]["text"] == "編輯後的字幕"
    assert subs["segments"][0]["words"], "words must be preserved when omitted"

    # text exports
    resp = client.get(f"/api/jobs/{job_id}/export/srt", headers={"X-Session-Token": TOKEN})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "attachment" in resp.headers["content-disposition"]
    assert "編輯後的字幕" in resp.text
    assert "-->" in resp.text

    resp = client.get(f"/api/jobs/{job_id}/export/vtt", headers={"X-Session-Token": TOKEN})
    assert resp.status_code == 200
    assert resp.text.startswith("WEBVTT")

    resp = client.get(f"/api/jobs/{job_id}/export/txt", headers={"X-Session-Token": TOKEN})
    assert resp.status_code == 200
    assert "編輯後的字幕" in resp.text

    resp = client.get(
        f"/api/jobs/{job_id}/export/txt?include_punctuation=false",
        headers={"X-Session-Token": TOKEN},
    )
    assert resp.status_code == 200

    resp = client.get(
        f"/api/jobs/{job_id}/export/ass?font_size=48&font_color=%23FF0000&karaoke=1&position=top",
        headers={"X-Session-Token": TOKEN},
    )
    assert resp.status_code == 200
    assert "[Script Info]" in resp.text
    assert "Dialogue:" in resp.text

    resp = client.get(f"/api/jobs/{job_id}/export/fcpxml", headers={"X-Session-Token": TOKEN})
    assert resp.status_code == 200
    root = ET.fromstring(resp.text)
    assert root.tag == "fcpxml"

    resp = client.get(f"/api/jobs/{job_id}/export/capcut", headers={"X-Session-Token": TOKEN})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert "attachment" in resp.headers["content-disposition"]
    assert "capcut_draft.zip" in resp.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        assert set(zf.namelist()) == {
            "sample/draft_content.json",
            "sample/draft_info.json",
            "sample/draft_meta_info.json",
        }
        content = json.loads(zf.read("sample/draft_content.json"))
        assert content["tracks"][0]["type"] == "text"
        assert content["tracks"][0]["segments"][0]["target_timerange"]["start"] == 100_000


def test_export_mp4_and_webm_alpha(client, tmp_path):
    video = make_video(tmp_path / "sample.mp4")
    resp = upload(client, video, token=TOKEN, language="zh")
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    wait_done(client, job_id, token=TOKEN)
    headers = {"X-Session-Token": TOKEN}

    # not rendered yet -> 409 on download, then start the async render
    resp = client.get(f"/api/jobs/{job_id}/export/mp4", headers=headers)
    assert resp.status_code == 409

    resp = client.post(f"/api/jobs/{job_id}/export/mp4/render", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] in ("rendering", "ready")

    # polling the same render must not restart it
    resp = client.post(f"/api/jobs/{job_id}/export/mp4/render", headers=headers)
    assert resp.json()["status"] in ("rendering", "ready")

    for _ in range(300):
        status = client.get(f"/api/jobs/{job_id}/export/mp4/status", headers=headers).json()
        assert status["status"] != "failed", status.get("error")
        if status["status"] == "ready":
            break
        time.sleep(0.05)
    else:
        pytest.fail("mp4 render did not finish in time")

    resp = client.get(f"/api/jobs/{job_id}/export/mp4", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "video/mp4"
    assert b"ftyp" in resp.content[:16]

    # second request serves the cached render
    resp = client.get(f"/api/jobs/{job_id}/export/mp4", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "video/mp4"

    resp = client.post(f"/api/jobs/{job_id}/export/webm_alpha/render", headers=headers)
    assert resp.status_code == 200
    for _ in range(300):
        status = client.get(f"/api/jobs/{job_id}/export/webm_alpha/status", headers=headers).json()
        assert status["status"] != "failed", status.get("error")
        if status["status"] == "ready":
            break
        time.sleep(0.05)
    else:
        pytest.fail("webm_alpha render did not finish in time")

    resp = client.get(f"/api/jobs/{job_id}/export/webm_alpha", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "video/webm"
    assert resp.content[:4] == b"\x1aE\xdf\xa3"


def test_export_render_requires_done_job(client, tmp_path):
    job_id = _seed_job(status="processing")
    resp = client.post(f"/api/jobs/{job_id}/export/mp4/render", headers={"X-Session-Token": TOKEN})
    assert resp.status_code == 409
    resp = client.get(f"/api/jobs/{job_id}/export/mp4/status", headers={"X-Session-Token": TOKEN})
    assert resp.status_code == 409


def test_fonts_system_list_and_download(client):
    headers = {"X-Session-Token": TOKEN}
    resp = client.get("/api/fonts", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "system_fonts" in body
    lxgw = next((f for f in body["system_fonts"] if f["family"] == "LXGW WenKai"), None)
    assert lxgw is not None
    assert lxgw["available"] is True
    assert lxgw["size"] > 0
    assert lxgw["license"]

    resp = client.get("/api/fonts/system/LXGWWenKai-Regular.ttf", headers=headers)
    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]

    assert client.get("/api/fonts/system/nope.ttf", headers=headers).status_code == 404
    # path traversal is neutralized by URL normalization (route never matches)
    traversal = "/api/fonts/system/..%2F..%2Fetc%2Fpasswd"
    assert client.get(traversal, headers=headers).status_code == 404


def test_font_upload_download(client, tmp_path):
    headers = {"X-Session-Token": TOKEN}
    fake_font = tmp_path / "MyFont.ttf"
    fake_font.write_bytes(b"fakettfdata")
    with open(fake_font, "rb") as fh:
        resp = client.post(
            "/api/fonts",
            files={"file": ("MyFont.ttf", fh, "application/octet-stream")},
            headers=headers,
        )
    assert resp.status_code == 201
    name = resp.json()["filename"]

    resp = client.get(f"/api/fonts/{name}", headers=headers)
    assert resp.status_code == 200
    assert resp.content == b"fakettfdata"
    assert "attachment" in resp.headers["content-disposition"]

    assert client.get("/api/fonts/../MyFont.ttf", headers=headers).status_code == 404
    assert client.get("/api/fonts/not-there.ttf", headers=headers).status_code == 404


def test_export_ass_param_validation(client, tmp_path):
    wav = make_wav(tmp_path / "v.wav")
    resp = upload(client, wav, token=TOKEN)
    job_id = resp.json()["job_id"]
    wait_done(client, job_id, token=TOKEN)
    headers = {"X-Session-Token": TOKEN}

    base = f"/api/jobs/{job_id}/export/ass"
    assert client.get(f"{base}?font_color=red", headers=headers).status_code == 422
    assert client.get(f"{base}?outline_color=zzz", headers=headers).status_code == 422
    assert client.get(f"{base}?karaoke=2", headers=headers).status_code == 422
    assert client.get(f"{base}?position=left", headers=headers).status_code == 422
    assert client.get(f"{base}?font_size=0", headers=headers).status_code == 422
    assert client.get(f"/api/jobs/{job_id}/export/unknown", headers=headers).status_code == 422


# ---------------------------------------------------------------- media


def test_media_and_audio_endpoints(client, tmp_path):
    wav = make_wav(tmp_path / "m.wav")
    resp = upload(client, wav, token=TOKEN)
    job_id = resp.json()["job_id"]
    wait_done(client, job_id, token=TOKEN)
    headers = {"X-Session-Token": TOKEN}

    resp = client.get(f"/api/jobs/{job_id}/media", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("audio/")
    assert resp.content[:4] == b"RIFF"

    resp = client.get(f"/api/jobs/{job_id}/audio", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"
    assert resp.content[:4] == b"RIFF"


# ---------------------------------------------------------------- validation / limits


def test_oversized_file_413(client, tmp_path, override_settings):
    override_settings(max_upload_mb=0.001)  # ~1KB cap
    wav = make_wav(tmp_path / "big.wav")
    resp = upload(client, wav, token=TOKEN)
    assert resp.status_code == 413
    assert "detail" in resp.json()


def test_duration_over_limit_400(client, tmp_path, override_settings):
    override_settings(max_duration_min=0.02)  # 1.2s cap
    wav = make_wav(tmp_path / "long.wav", seconds=2.0)
    resp = upload(client, wav, token=TOKEN)
    assert resp.status_code == 400
    assert "duration" in resp.json()["detail"]


def test_daily_quota_removed(client, tmp_path, override_settings):
    override_settings(max_upload_mb=10, max_duration_min=60)
    wav = make_wav(tmp_path / "q.wav", seconds=2.0)
    assert upload(client, wav, token="quota-tok").status_code == 202
    assert upload(client, wav, token="quota-tok").status_code == 202
    assert upload(client, wav, token="quota-tok").status_code == 202


def test_queue_full_429(client, tmp_path, override_settings, monkeypatch):
    override_settings(max_queue=1)
    # pin queue_length so the test is deterministic (inline queue may drain fast)
    monkeypatch.setattr("app.api.limits.queue_length", lambda db: 1)
    wav = make_wav(tmp_path / "qf.wav")
    resp = upload(client, wav, token=TOKEN)
    assert resp.status_code == 429
    assert "retry_after_seconds" in resp.json()


def test_upload_rate_limit_429(client, tmp_path, override_settings):
    override_settings(upload_rate_limit=2)
    wav = make_wav(tmp_path / "r.wav")
    assert upload(client, wav, token="rate-tok").status_code == 202
    assert upload(client, wav, token="rate-tok").status_code == 202
    resp = upload(client, wav, token="rate-tok")
    assert resp.status_code == 429
    body = resp.json()
    assert body["retry_after_seconds"] >= 1


def test_chunked_upload_flow(client, tmp_path):
    """start -> chunks -> complete must produce a normal job that reaches done."""
    with open(make_wav(tmp_path / "chunked.wav", seconds=0.5), "rb") as fh:
        data = fh.read()
    headers = {"X-Session-Token": "chunk-tok"}

    resp = client.post(
        "/api/jobs/uploads",
        headers=headers,
        data={"filename": "chunked.wav", "language": "en"},
    )
    assert resp.status_code == 200
    upload_id = resp.json()["upload_id"]

    half = len(data) // 2
    for index, part in ((0, data[:half]), (1, data[half:])):
        resp = client.post(
            f"/api/jobs/uploads/{upload_id}/chunks",
            headers=headers,
            data={"index": str(index)},
            files={"data": ("part.bin", part, "application/octet-stream")},
        )
        assert resp.status_code == 200

    resp = client.post(f"/api/jobs/uploads/{upload_id}/complete", headers=headers)
    assert resp.status_code == 202
    body = resp.json()
    assert body["job_id"]
    wait_done(client, body["job_id"], "chunk-tok")


def test_chunked_upload_requires_owner(client, tmp_path):
    headers = {"X-Session-Token": "owner-tok"}
    resp = client.post(
        "/api/jobs/uploads", headers=headers, data={"filename": "owner.wav"}
    )
    upload_id = resp.json()["upload_id"]

    foreign = {"X-Session-Token": "other-tok"}
    resp = client.post(
        f"/api/jobs/uploads/{upload_id}/chunks",
        headers=foreign,
        data={"index": "0"},
        files={"data": ("p.bin", b"x", "application/octet-stream")},
    )
    assert resp.status_code == 403

    resp = client.post(f"/api/jobs/uploads/{upload_id}/complete", headers=foreign)
    assert resp.status_code == 403

    resp = client.post(f"/api/jobs/uploads/{upload_id}/complete", headers=headers)
    assert resp.status_code == 422  # no chunks uploaded yet


def test_chunked_upload_unlimited_size(client, tmp_path, override_settings):
    """With max_upload_mb=0 (default) a chunked file larger than the old cap lands."""
    override_settings(max_upload_mb=0)
    with open(make_wav(tmp_path / "big.wav", seconds=0.5), "rb") as fh:
        data = fh.read()
    headers = {"X-Session-Token": "big-tok"}
    resp = client.post(
        "/api/jobs/uploads", headers=headers, data={"filename": "big.wav"}
    )
    upload_id = resp.json()["upload_id"]
    resp = client.post(
        f"/api/jobs/uploads/{upload_id}/chunks",
        headers=headers,
        data={"index": "0"},
        files={"data": ("p.bin", data, "application/octet-stream")},
    )
    assert resp.status_code == 200
    resp = client.post(f"/api/jobs/uploads/{upload_id}/complete", headers=headers)
    assert resp.status_code == 202


def test_unsupported_format_400(client, tmp_path):
    fake = tmp_path / "fake.mp4"
    fake.write_text("this is not media", encoding="utf-8")
    resp = upload(client, str(fake), token=TOKEN)
    assert resp.status_code == 400


def test_invalid_language_422(client, tmp_path):
    wav = make_wav(tmp_path / "l.wav")
    resp = upload(client, wav, token=TOKEN, language="xx")
    assert resp.status_code == 422


def test_invalid_options_422(client, tmp_path):
    wav = make_wav(tmp_path / "o.wav")
    resp = upload(client, wav, token=TOKEN, options="not-json")
    assert resp.status_code == 422


def test_config_no_remaining_seconds(client, tmp_path):
    wav = make_wav(tmp_path / "c.wav", seconds=2.0)
    assert upload(client, wav, token="cfg-tok").status_code == 202
    resp = client.get("/api/config", headers={"X-Session-Token": "cfg-tok"})
    assert resp.status_code == 200
    # session_remaining_seconds removed with daily quota
    assert "session_remaining_seconds" not in resp.json()


# ---------------------------------------------------------------- job lifecycle errors


def test_unknown_job_404(client):
    headers = {"X-Session-Token": TOKEN}
    assert client.get("/api/jobs/nope", headers=headers).status_code == 404
    assert client.get("/api/jobs/nope/subtitles", headers=headers).status_code == 404
    assert client.get("/api/jobs/nope/media", headers=headers).status_code == 404
    assert client.get("/api/jobs/nope/audio", headers=headers).status_code == 404
    assert client.get("/api/jobs/nope/export/srt", headers=headers).status_code == 404


def test_expired_job_410(client):
    job_id = _seed_job(expires_at=utcnow() - timedelta(hours=1), segments_json=_segments_json())
    headers = {"X-Session-Token": "seed-token"}
    resp = client.get(f"/api/jobs/{job_id}", headers=headers)
    assert resp.status_code == 410
    assert resp.json()["detail"] == "Job expired"
    assert client.get(f"/api/jobs/{job_id}/subtitles", headers=headers).status_code == 410
    assert client.get(f"/api/jobs/{job_id}/media", headers=headers).status_code == 410
    assert client.get(f"/api/jobs/{job_id}/export/srt", headers=headers).status_code == 410


def test_subtitles_409_when_not_done(client):
    job_id = _seed_job(status="queued")
    headers = {"X-Session-Token": "seed-token"}
    assert client.get(f"/api/jobs/{job_id}/subtitles", headers=headers).status_code == 409
    put = client.put(f"/api/jobs/{job_id}/subtitles", json={"segments": []}, headers=headers)
    assert put.status_code == 409
    assert client.get(f"/api/jobs/{job_id}/export/srt", headers=headers).status_code == 409


def test_put_subtitles_validation(client, tmp_path):
    wav = make_wav(tmp_path / "p.wav")
    resp = upload(client, wav, token=TOKEN)
    job_id = resp.json()["job_id"]
    wait_done(client, job_id, token=TOKEN)
    headers = {"X-Session-Token": TOKEN}

    # start >= end
    bad = {"segments": [{"id": 0, "start": 0.6, "end": 0.1, "text": "x"}]}
    assert client.put(f"/api/jobs/{job_id}/subtitles", json=bad, headers=headers).status_code == 422

    # duplicate ids
    dup = {"segments": [
        {"id": 0, "start": 0.1, "end": 0.2, "text": "a"},
        {"id": 0, "start": 0.3, "end": 0.4, "text": "b"},
    ]}
    assert client.put(f"/api/jobs/{job_id}/subtitles", json=dup, headers=headers).status_code == 422

    # missing text
    missing = {"segments": [{"id": 0, "start": 0.1, "end": 0.2}]}
    resp = client.put(f"/api/jobs/{job_id}/subtitles", json=missing, headers=headers)
    assert resp.status_code == 422


def test_put_subtitles_accepts_word_alias(client, tmp_path):
    wav = make_wav(tmp_path / "w.wav")
    resp = upload(client, wav, token=TOKEN)
    job_id = resp.json()["job_id"]
    wait_done(client, job_id, token=TOKEN)
    headers = {"X-Session-Token": TOKEN}

    payload = {
        "segments": [
            {
                "id": 0,
                "start": 0.1,
                "end": 0.6,
                "text": "新文字",
                "words": [
                    {"word": "新", "start": 0.1, "end": 0.3},
                    {"word": "文字", "start": 0.3, "end": 0.6},
                ],
            }
        ]
    }
    put = client.put(f"/api/jobs/{job_id}/subtitles", json=payload, headers=headers)
    assert put.status_code == 200
    resp = client.get(f"/api/jobs/{job_id}/subtitles", headers=headers)
    words = resp.json()["segments"][0]["words"]
    assert [w["text"] for w in words] == ["新", "文字"]
