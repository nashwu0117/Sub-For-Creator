# Sub for Creator — API Contract (v1)

The shared API contract for the backend and frontend. The backend implements this contract and the frontend consumes it.

## Conventions

- Base path: `/api`
- All responses are JSON except exported files.
- Anonymous sessions: the client generates a UUID v4 on first visit and sends `X-Session-Token: <uuid>` with every request. The token is stored in `localStorage`. The server treats it as an opaque key for rate limiting and job ownership.
- Time values are floating-point seconds (`start` / `end`).
- Error format: `{ "detail": "human readable message" }`, with the HTTP status conveying the error category.
- Environment variables use the `SFC_` prefix; `.env.example` lists them all.

## Endpoints

### `GET /api/health`

```json
200 { "status": "ok", "version": "0.1.0" }
```

### `GET /api/config`

Returns upload limits and supported languages for the frontend:

```json
200 {
  "max_upload_mb": 1024,
  "max_duration_min": 60,
  "max_queue": 50,
  "supported_languages": ["zh", "en", "ja", "ko", "..."],
  "session_remaining_seconds": 3000,
  "default_options": { "max_line_chars": 16, "model_size": "large-v3" }
}
```

`session_remaining_seconds` is the remaining upload time for the session today.

### `POST /api/jobs` — Upload video or audio

`multipart/form-data`:

| Field | Description |
|---|---|
| `file` | Video or audio file (required) |
| `language` | Language code; `auto` or omitted means automatic detection |
| `options` | JSON string such as `{ "model_size": "large-v3", "max_line_chars": 16 }` (optional; defaults are used when omitted) |

The server validates file size, media duration, the session's daily allowance, and queue capacity.

Success: `202 { "job_id": "...", "status": "queued", "queue_position": 3, "eta_seconds": 120 }`

Possible failures: `413` (file too large), `429` (quota or queue full), `400` (unsupported or unparseable media), `422` (invalid fields).

### `GET /api/jobs/{job_id}` — Job status

```json
200 {
  "job_id": "...",
  "status": "queued" | "processing" | "done" | "failed",
  "stage": null | "extracting" | "transcribing" | "segmenting",
  "progress": 0.0,
  "queue_position": 2,
  "error": null | "string",
  "created_at": "ISO8601",
  "expires_at": "ISO8601",
  "meta": { "filename": "x.mp4", "duration": 123.4, "language": "en", "model_size": "large-v3" }
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

`format` ∈ `srt | vtt | txt | ass | fcpxml | mp4 | webm_alpha`

- Text formats (`srt/vtt/txt/ass/fcpxml`) return UTF-8 content as an attachment.
- `mp4` is an H.264 video with burned-in subtitles; `webm_alpha` is a transparent VP9 WebM video.
- The job must be `done`, otherwise the API returns `409`. Render exports run synchronously and may take up to 300 seconds; a timeout returns `504`.
- Query parameters include `font_size=64`, `font_color=#FFFFFF`, `outline_color=#000000`, `font_family=`, `karaoke=0|1`, `position=bottom|top` (ASS/MP4/WebM), and `include_punctuation=true|false` (TXT).

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
| 404 | Job does not exist, or media/audio file does not exist |
| 409 | Job is not complete (`require_done`) |
| 410 | Job TTL has expired |
| 413 | File exceeds `SFC_MAX_UPLOAD_MB` or font exceeds `SFC_MAX_FONT_MB` |
| 422 | Unsupported language, invalid options JSON, empty file, invalid export format/parameters, or invalid subtitle segment |
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

A `429` response has the shape `{ "detail": "...", "retry_after_seconds": 60 }`.

## Job lifecycle

```text
queued → processing(extracting → transcribing → segmenting) → done
                                                          ↘ failed (error contains the message)
done → (TTL expires) → 410
```

## Backend data model

`jobs` table: `id (uuid str, pk)`, `session_token`, `status`, `stage`, `progress`, `error`, `filename`, `language`, `model_size`, `duration`, `created_at`, `completed_at`, `expires_at`, and `segments_json` (complete subtitle data after processing, including words). `queue_position` is calculated live by the API and is not stored.

`usage` table (rate limiting): `session_token`, `date`, and `uploaded_seconds` (upserted).

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
| `/edit/:jobId` | Editor with player, subtitle list, and wavesurfer timeline |
| `/privacy` | Privacy policy |
| `/terms` | Terms of service |

`VITE_API_BASE` defaults to `/api`; the Vite development proxy points it to `http://localhost:8000`.
