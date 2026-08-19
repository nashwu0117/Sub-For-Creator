# Sub for Creator — API 契約 (v1)

前後端共同遵循的 API 規範。後端依此實作，前端依此串接。

## 慣例

- Base path: `/api`
- 所有回應皆為 JSON（匯出檔案除外）。
- 匿名 session：客戶端在首次造訪時產生 UUID v4，之後每個請求帶 `X-Session-Token: <uuid>` header（前端存 localStorage）。伺服器不驗證 token 格式（opaque），僅作為限流與作業歸屬的鍵。
- 時間格式：秒，浮點數（`start` / `end`）。
- 錯誤格式：`{ "detail": "human readable message" }`（HTTP 狀態碼對應語意）。
- 環境變數以 `SFC_` 為前綴，`.env.example` 列出全部。

## 端點

### `GET /api/health`

```
200 { "status": "ok", "version": "0.1.0" }
```

### `GET /api/config`

回傳給前端顯示的上傳限制與支援語言：

```
200 {
  "max_upload_mb": 1024,
  "max_duration_min": 60,
  "max_queue": 50,
  "supported_languages": ["zh", "en", "ja", "ko", ...],
  "session_remaining_seconds": 3000,   // 該 session 今日剩餘可上傳秒數
  "default_options": { "max_line_chars": 16, "model_size": "large-v3" }
}
```

### `POST /api/jobs` — 上傳影片/音檔

multipart/form-data：

| field | 說明 |
|---|---|
| `file` | 影片或音檔（必填） |
| `language` | 語言代碼，`auto` 或省略 = 自動偵測 |
| `options` | JSON 字串：`{ "model_size": "large-v3", "max_line_chars": 16 }`（可省略，用預設） |

伺服器驗證：檔案大小 ≤ `MAX_UPLOAD_MB`、ffprobe 時長 ≤ `MAX_DURATION_MIN`、session 每日上傳秒數額度、佇列長度 ≤ `MAX_QUEUE`。

成功：`202 { "job_id": "...", "status": "queued", "queue_position": 3, "eta_seconds": 120 }`
失敗：`413`（檔案過大）、`429`（額度/佇列滿）、`400`（格式不支援或內容無法解析）、`422`（欄位錯誤）

### `GET /api/jobs/{job_id}` — 作業狀態

```
200 {
  "job_id": "...",
  "status": "queued" | "processing" | "done" | "failed",
  "stage": null | "extracting" | "transcribing" | "segmenting",
  "progress": 0.0,          // 0-100
  "queue_position": 2,      // queued 時有效
  "error": null | "string",
  "created_at": "ISO8601",
  "expires_at": "ISO8601",  // TTL 期限
  "meta": { "filename": "x.mp4", "duration": 123.4, "language": "zh", "model_size": "large-v3" }
}
```

作業 TTL 到期後（處理完成起 48h，可設定）：`410 Gone`。

### `GET /api/jobs/{job_id}/subtitles` — 取得/匯出字幕資料

作業必須為 `done`，否則 `409 Conflict`。

```
200 {
  "job_id": "...",
  "language": "zh",
  "segments": [
    { "id": 0, "start": 0.4, "end": 3.2, "text": "今天天氣真好",
      "words": [ { "word": "今天", "start": 0.4, "end": 1.1 }, ... ] }   // 可為空陣列
  ],
  "meta": { "model_size": "large-v3", "max_line_chars": 16 }
}
```

### `PUT /api/jobs/{job_id}/subtitles` — 儲存編輯後的字幕

Body：`{ "segments": [ { "id", "start", "end", "text" } ] }`（可省略 words，或保留）。
回傳 `200 { "ok": true }`。

### `GET /api/jobs/{job_id}/media` — 串流原始影片/音檔

播放器用；`Content-Disposition: inline`。作業不存在回 `404`；已過期回 `410`。

### `GET /api/jobs/{job_id}/audio` — 串流抽取的音軌

16kHz mono WAV（`audio/wav`，`Content-Disposition: inline`）。音軌尚未產生（作業未到 transcribing 階段）回 `404`。

### `GET /api/jobs/{job_id}/export/{format}` — 匯出

`format` ∈ `srt | vtt | txt | ass | fcpxml | mp4 | webm_alpha`

- 文字類（srt/vtt/txt/ass/fcpxml）：`Content-Type: text/plain; charset=utf-8`，`Content-Disposition: attachment; filename="..."`
- `mp4`：燒錄字幕的 H.264 MP4（`video/mp4`）；`webm_alpha`：透明背景 VP9 webm（`video/webm`）
- 作業須為 `done`，否則 `409`；render 為同步執行（每次請求皆等待完成），render 逾時 300s 回 `504`。
- query params：`font_size=64`、`font_color=#FFFFFF`、`outline_color=#000000`、`font_family=`、`karaoke=0|1`、`position=bottom|top`（ass/mp4/webm_alpha 適用）；`include_punctuation=true|false`（txt 適用）

### `GET /api/fonts` — 列出已上傳的自訂字型

```
200 { "fonts": [ { "name": "NotoSansSC", "filename": "NotoSansSC.ttf", "size": 123456, "uploaded_at": "ISO8601" } ] }
```

### `POST /api/fonts` — 上傳自訂字型（燒錄用）

multipart/form-data：`file`（.ttf / .otf，必填）。上限 `SFC_MAX_FONT_MB`（預設 20 MB）。

成功：`201 { "name": "...", "filename": "...", "size": 123456 }`
失敗：`400`（非 .ttf/.otf）、`413`（超過大小上限）、`422`（空檔案）

### 錯誤碼總表

| 狀態碼 | 情境 |
|---|---|
| 400 | 缺少/過長 `X-Session-Token`、格式不支援、媒體無法解析、時長超過上限 |
| 404 | 作業不存在、media/audio 檔案不存在 |
| 409 | 作業尚未完成（`require_done`） |
| 410 | 作業 TTL 已到期 |
| 413 | 檔案超過 `SFC_MAX_UPLOAD_MB` / 字型超過 `SFC_MAX_FONT_MB` |
| 422 | 不支援的語言、options JSON 無效、空檔案、無效匯出格式/參數、字幕片段驗證失敗 |
| 429 | 額度/限流/佇列滿（附 `retry_after_seconds`） |
| 500 | 匯出或 ASR 內部錯誤 |
| 504 | render 逾時或 ffmpeg 失敗 |

### 限流 (429)

| 規則 | 預設 | 設定 |
|---|---|---|
| 單檔大小 | 1024 MB | `SFC_MAX_UPLOAD_MB` |
| 單檔時長 | 60 min | `SFC_MAX_DURATION_MIN` |
| session 每日上傳秒數 | 3600 s | `SFC_DAILY_SECONDS_PER_SESSION` |
| 最大佇列長度 | 50 | `SFC_MAX_QUEUE` |
| 同時處理任務數 | 2 | `SFC_MAX_CONCURRENT`（inline 佇列執行緒池大小；celery 模式由 worker `--concurrency` 控制） |
| 檔案 TTL | 48 h | `SFC_TTL_HOURS` |
| 上傳頻率 | 60 s 內最多 5 次 | `SFC_UPLOAD_RATE_LIMIT` |

429 response：`{ "detail": "...", "retry_after_seconds": 60 }`

## 作業生命週期

```
queued → processing(extracting → transcribing → segmenting) → done
                                                          ↘ failed (error 欄位含訊息)
done → (TTL 到期) → 410
```

## 資料模型（後端）

`jobs` 表：`id (uuid str, pk)`、`session_token`、`status`、`stage`、`progress`、`error`、`filename`、`language`、`model_size`、`duration`、`created_at`、`completed_at`、`expires_at`、`segments_json`（完成後的完整字幕資料，含 words）。`queue_position` 不落庫，由 API 依 active 作業即時計算。

`usage` 表（限流用）：`session_token`、`date`、`uploaded_seconds`（upsert）。

## 儲存佈局

- 上傳原始檔：`{UPLOAD_DIR or S3}/jobs/{job_id}/source.<ext>`
- 抽出的音軌：`{...}/jobs/{job_id}/audio.wav`（16kHz mono）
- 字幕 JSON：存 DB `segments_json`（不再單獨寫檔，避免一致性問題）
- render 產物：`{...}/jobs/{job_id}/burned.mp4`、`{...}/jobs/{job_id}/alpha.webm`
- 自訂字型：`{...}/fonts/<name>.<ext>`
- 清理：Celery beat 每 6 小時執行一次（celery 模式；inline 模式由 API 進程內定時迴圈負責），刪除 `expires_at < now` 的整個 job 目錄 + DB 列

## 前端路由

| 路由 | 頁面 |
|---|---|
| `/` | 上傳頁（含佇列狀態、最近作業清單 localStorage） |
| `/edit/:jobId` | 編輯器（播放器 + 字幕列表 + wavesurfer 時間軸） |
| `/privacy` | 隱私權政策 |
| `/terms` | 服務條款 |

前端 `VITE_API_BASE`（預設 `/api`，vite dev proxy 指向 `http://localhost:8000`）。
