# Sub for Creator — API Contract (v2)

The shared API contract for the backend and frontend. The backend implements this contract and the frontend consumes it.

## Conventions

- Base path: `/api`
- All responses are JSON except exported files.
- Anonymous sessions: the client generates a UUID v4 on first visit and sends `X-Session-Token: <uuid>` with every request. The token is stored in `localStorage`. The server treats it as an opaque key for rate limiting and job ownership.
- Optional account system: after login the server sets an HttpOnly cookie (default `sfc_session`, `SameSite=Lax`, configurable via `SFC_AUTH_*`). **Job ownership rule**: an unclaimed job is accessed by session token; once claimed by an account, only that account (via cookie) can access it — the original session token gets `403`.
- Time values are floating-point seconds (`start` / `end`).
- Error format: `{ "detail": "human readable message" }`, with the HTTP status conveying the error category.
- Environment variables use the `SFC_` prefix; `.env.example` lists them all.

## Endpoints

### `GET /api/health`

```json
200 { "status": "ok", "version": "0.1.0" }
```

### `GET /api/metrics` — Prometheus metrics (monitoring)

Enabled when `SFC_METRICS_ENABLED=true` (default `false`). Returns Prometheus text format:

- `sfc_http_requests_total{method,path,status}` — HTTP request counts
- `sfc_http_request_duration_seconds{method,path}` — histogram
- `sfc_active_jobs` — currently queued/processing jobs
- `sfc_gpu_utilization_percent{gpu}` / `sfc_gpu_memory_used_bytes{gpu}` — NVIDIA GPU stats (when present)
- `sfc_storage_used_bytes` / `sfc_upload_dir_bytes` — storage usage
- `sfc_font_dir_bytes` — font directory usage

Returns `404` when disabled.

### `GET /api/config`

Returns upload limits and supported languages for the frontend:

```json
200 {
  "max_upload_mb": 1024,
  "max_duration_min": 60,
  "max_queue": 50,
  "supported_languages": ["zh", "en", "ja", "ko", "..."],
  "session_remaining_seconds": 3000,
  "tiers": ["lite", "standard", "pro"],
  "llm_available": true,
  "default_options": {
    "max_line_chars": 16,
    "model_size": "medium",
    "tier": "standard",
    "denoise_enabled": true,
    "loudnorm_enabled": true,
    "llm_correction_enabled": false
  }
}
```

`session_remaining_seconds` is the remaining upload time for the session today. `default_options` holds the resolved ASR options for the current tier (the frontend may omit them when uploading).

### User dictionary

The dictionary is a JSON file shaped `{"terms": [...]}` (default `SFC_DICTIONARY_PATH`, `./data/user_dictionary.json`) used to build the ASR `initial_prompt` and the LLM correction glossary. All requests require `X-Session-Token`.

| Method | Path | Description |
|---|---|---|
| GET | `/api/dictionary` | List all terms → `200 { "terms": ["OpenAI", "WhisperX"] }` |
| POST | `/api/dictionary` | Add terms: body `{ "terms": ["OpenAI"] }` → `200 { "terms": [...], "added": ["OpenAI"] }` (`added` contains only newly added terms; case-insensitive dedupe); `422` for an empty list, control characters, or terms over 100 characters |
| DELETE | `/api/dictionary` | Remove one term: body `{ "term": "OpenAI" }` (case-insensitive) → `200 { "ok": true }` |

### `POST /api/jobs` — Upload video or audio

`multipart/form-data`:

| Field | Description |
|---|---|
| `file` | Video or audio file (required) |
| `language` | Language code; `auto` or omitted means automatic detection |
| `options` | JSON string such as `{ "model_size": "large-v3", "max_line_chars": 16, "tier": "pro", "denoise_enabled": true, "loudnorm_enabled": true, "llm_correction_enabled": false }` (optional; defaults are used when omitted) |

The server validates file size, media duration, the session's daily allowance, and queue capacity.

Success: `202 { "job_id": "...", "status": "queued", "queue_position": 3, "eta_seconds": 120 }`

Possible failures: `413` (file too large), `429` (quota or queue full), `400` (unsupported or unparseable media), `422` (invalid fields).

### `GET /api/jobs/{job_id}` — Job status

```json
200 {
  "job_id": "...",
  "status": "queued" | "processing" | "done" | "failed",
  "stage": null | "extracting" | "preprocessing" | "transcribing" | "segmenting",
  "progress": 0.0,
  "queue_position": 2,
  "error": null | "string",
  "created_at": "ISO8601",
  "expires_at": "ISO8601",
  "meta": {
    "filename": "x.mp4",
    "duration": 123.4,
    "language": "en",
    "model_size": "large-v3",
    "tier": "standard",
    "denoise_enabled": true,
    "loudnorm_enabled": true,
    "llm_correction_enabled": false
  }
}
```

After the job TTL expires (48 hours after completion by default, configurable), the endpoint returns `410 Gone`.

### `GET /api/jobs/{job_id}/subtitles` — Get subtitle data

The job must be `done`; otherwise the API returns `409 Conflict`.

```json
200 {
  "job_id": "...",
  "language": "en",
  "segments": [
    {
      "id": 0,
      "start": 0.4,
      "end": 3.2,
      "text": "The weather is beautiful today",
      "words": [
        { "word": "The", "start": 0.4, "end": 0.8 }
      ]
    }
  ],
  "meta": { "model_size": "large-v3", "max_line_chars": 16 }
}
```

### `PUT /api/jobs/{job_id}/subtitles` — Save edited subtitles

Body: `{ "segments": [ { "id", "start", "end", "text" } ] }`. The `words` field may be omitted or preserved.

Returns `200 { "ok": true }`.

### `GET /api/jobs/{job_id}/media` — Stream original media

Used by the player with `Content-Disposition: inline`. A missing job returns `404`; an expired job returns `410`.

### `GET /api/jobs/{job_id}/audio` — Stream extracted audio

Returns a 16 kHz mono WAV (`audio/wav`, `Content-Disposition: inline`). Returns `404` if the track has not been generated yet.

### `GET /api/jobs/{job_id}/export/{format}` — Export

`format` ∈ `srt | vtt | txt | ass | fcpxml | capcut | mp4 | webm_alpha`

- Text formats (`srt/vtt/txt/ass/fcpxml`) return UTF-8 content as an attachment.
- `capcut` returns a JianYing (CapCut) draft Zip — `{stem}_capcut_draft.zip` (draft_content.json + assets) importable into CapCut desktop/mobile.
- `mp4` is an H.264 video with burned-in subtitles; `webm_alpha` is a transparent VP9 WebM video.
- The job must be `done`, otherwise the API returns `409`. Render exports run synchronously and may take up to 300 seconds; a timeout returns `504`.
- Query parameters include `font_size=64`, `font_color=#FFFFFF`, `outline_color=#000000`, `font_family=`, `karaoke=0|1`, `position=bottom|top` (ASS/MP4/WebM), and `include_punctuation=true|false` (TXT).

### Accounts (optional, v2)

| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/register` | Body `{ "email", "password", "display_name"? }` → `201 { "id", "email", "display_name", "created_at" }`; `409` duplicate email, `422` invalid format |
| POST | `/api/auth/login` | Body `{ "email", "password" }` → `200 { "id", "email", "display_name", "created_at" }` plus a session cookie; `401` bad credentials |
| POST | `/api/auth/logout` | Clears the cookie (idempotent) → `200 { "ok": true }` |
| GET | `/api/auth/me` | Current user → `200 {...}`; `401` when not logged in |

- Passwords are stored as PBKDF2-HMAC-SHA256 (600k iterations) with a per-user random salt; the cookie is an HMAC-SHA256-signed `{user_id}.{expiry}.{digest}` (HttpOnly, `SameSite=Lax`) — never in `localStorage` (XSS-readable).
- It is an overlay on the v1 anonymous flow: everything works without an account; logging in only adds the work collection and job ownership.

### Work collection (v2)

| Method | Path | Description |
|---|---|---|
| GET | `/api/works` | List the current user's works (newest first): `200 [ { "id", "job_id", "title", "created_at", "job": { "status", "filename", "duration", "expires_at" } } ]`; `401` when not logged in |
| POST | `/api/works/{job_id}` | Claim a session-token-owned job into the account's library; idempotent (returns the existing work on re-claim); `403` when the job belongs to another session/account |
| GET | `/api/works/{work_id}` | One work (with live job status); `403` when not owned |
| DELETE | `/api/works/{work_id}` | Remove from the library (the job itself is untouched) → `200 { "ok": true }` |

- After the job TTL (48h) cleanup removes the job, the work's `job.status` reports `"expired"`; the work row itself is kept.
- **Ownership is enforced**: once claimed, all job endpoints (status/subtitles/media/export) accept only the account cookie; requests with the original `X-Session-Token` get `403`.

### `GET /api/fonts` — List uploaded custom fonts

```json
200 { "fonts": [ { "name": "NotoSansSC", "filename": "NotoSansSC.ttf", "size": 123456, "uploaded_at": "ISO8601" } ] }
```

### `POST /api/fonts` — Upload a custom font

`multipart/form-data`: `file` (`.ttf` or `.otf`, required). The default limit is `SFC_MAX_FONT_MB` (20 MB).

Success: `201 { "name": "...", "filename": "...", "size": 123456 }`

Possible failures: `400` (not `.ttf`/`.otf`), `413` (file too large), `422` (empty file).

## Error codes

| Status | Situation |
|---:|---|
| 400 | Missing or oversized `X-Session-Token`, unsupported format, unparseable media, or duration over the limit |
| 401 | Authentication required (accessing auth/works endpoints without a cookie) |
| 403 | Upload session token mismatch; accessing a claimed job with the original session token; accessing another user's work |
| 404 | Job does not exist, or media/audio file does not exist, metrics disabled |
| 409 | Job is not complete (`require_done`), render not ready, duplicate email |
| 410 | Job TTL has expired |
| 413 | File exceeds `SFC_MAX_UPLOAD_MB` or font exceeds `SFC_MAX_FONT_MB` |
| 422 | Unsupported language, invalid options JSON, empty file, invalid export format/parameters, invalid subtitle segment, or invalid email/password format |
| 429 | Quota, rate limit, or queue capacity exceeded; response includes `retry_after_seconds` |
| 500 | Internal export or ASR error |
| 504 | Render timeout or FFmpeg failure |

### Rate limiting (`429`)

| Rule | Default | Setting |
|---|---:|---|
| File size | 1024 MB | `SFC_MAX_UPLOAD_MB` |
| File duration | 60 min | `SFC_MAX_DURATION_MIN` |
| Daily upload seconds per session | 3600 s | `SFC_DAILY_SECONDS_PER_SESSION` |
| Maximum queue length | 50 | `SFC_MAX_QUEUE` |
| Concurrent jobs | 2 | `SFC_MAX_CONCURRENT` (inline thread pool size; Celery mode uses worker `--concurrency`) |
| File TTL | 48 h | `SFC_TTL_HOURS` |
| Upload rate | 5 per 60 s | `SFC_UPLOAD_RATE_LIMIT` |
| ASR accuracy tier | `standard` | `SFC_TIER` (`lite` / `standard` / `pro`); `SFC_BEAM_SIZE`, `SFC_TEMPERATURE`, `SFC_VAD_ENABLED` override (unset = tier preset) |
| Denoise / loudness normalization | tier preset | `SFC_DENOISE_ENABLED`, `SFC_LOUDNORM_ENABLED` (`true`/`false`; unset = tier preset); `SFC_NOISE_REDUCTION_STRENGTH` (noisereduce `prop_decrease`, default `0.75`) |
| User dictionary | `./data/user_dictionary.json` | `SFC_DICTIONARY_PATH`; `SFC_INITIAL_PROMPT_MAX_CHARS` (default `1500`) |
| LLM correction | tier preset (pro on) | `SFC_LLM_CORRECTION_ENABLED`, `SFC_LLM_PROVIDER` (`ollama` / `openai`), `SFC_LLM_MODEL` (default `qwen2.5:7b`), `SFC_OLLAMA_URL` (default `http://localhost:11434`), `SFC_LLM_API_KEY`, `SFC_LLM_TIMEOUT_SECONDS` (default `120`) |
| Auth cookie name | `sfc_session` | `SFC_AUTH_COOKIE_NAME` |
| Auth cookie Secure | `false` | `SFC_AUTH_COOKIE_SECURE` (set `true` on HTTPS) |
| Auth signing secret | dev default | `SFC_AUTH_SECRET` (change when deploying) |
| Auth session days | 30 | `SFC_AUTH_SESSION_DAYS` |
| Metrics | `false` | `SFC_METRICS_ENABLED` |

A `429` response has the shape `{ "detail": "...", "retry_after_seconds": 60 }`.

## Job lifecycle

```text
queued → processing(extracting → preprocessing → transcribing → segmenting) → done
                                                                    ↘ failed (error contains the message)
done → (TTL expires) → 410
```

The `preprocessing` stage only appears when the job has denoising or loudness normalization enabled (`denoise_enabled` / `loudnorm_enabled`). LLM correction is best-effort: any failure (connection, parse, validation) keeps the original transcript and never fails the job.

## Backend data model

`jobs` table: `id (uuid str, pk)`, `session_token`, `status`, `stage`, `progress`, `error`, `filename`, `language`, `model_size`, `tier`, `denoise_enabled`, `loudnorm_enabled`, `llm_correction_enabled`, `duration`, `created_at`, `completed_at`, `expires_at`, and `segments_json` (complete subtitle data after processing, including words). `queue_position` is calculated live by the API and is not stored.

`usage` table (rate limiting): `session_token`, `date`, and `uploaded_seconds` (upserted).

`users` table (accounts, v2): `id (int, pk)`, `email` (lowercased unique), `password_hash` (`pbkdf2_sha256$iter$salt$hash`), `display_name`, `created_at`.

`works` table (collection, v2): `id (int, pk)`, `user_id` (FK users), `job_id` (deliberately **not** a FK — jobs are TTL-deleted while works must survive and report `expired`), `title`, `created_at`. A job can be claimed by at most one user.

## Storage layout

- Original upload: `{UPLOAD_DIR or S3}/jobs/{job_id}/source.<ext>`
- Extracted audio: `{...}/jobs/{job_id}/audio.wav` (16 kHz mono)
- Subtitle JSON: stored in the database as `segments_json`
- Rendered output: `{...}/jobs/{job_id}/burned.mp4` and `{...}/jobs/{job_id}/alpha.webm`
- Custom fonts: `{...}/fonts/<name>.<ext>`
- Cleanup: Celery Beat runs every 6 hours in Celery mode; inline mode uses an in-process scheduler. Expired job directories and database rows are deleted together.

## Frontend routes

| Route | Page |
|---|---|
| `/` | Upload page with queue status and recent jobs in local storage |
| `/edit/:jobId` | Editor with player, subtitle list, and wavesurfer timeline (with claim button) |
| `/works` | My Works — the claimed-work library (v2) |
| `/privacy` | Privacy policy |
| `/terms` | Terms of service |

`VITE_API_BASE` defaults to `/api`; the Vite development proxy points it to `http://localhost:8000`.
