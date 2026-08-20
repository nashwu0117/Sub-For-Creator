# Sub for Creator — API 契約 (v2)

前後端共同遵循的 API 規範。後端依此實作，前端依此串接。

## 慣例

- Base path: `/api`
- 所有回應皆為 JSON（匯出檔案除外）。
- 匿名 session：客戶端在首次造訪時產生 UUID v4，之後每個請求帶 `X-Session-Token: <uuid>` header（前端存 localStorage）。伺服器不驗證 token 格式（opaque），僅作為限流與作業歸屬的鍵。
- 帳號系統（可選）：登入後伺服器設定 HttpOnly cookie（預設 `sfc_session`，`SameSite=Lax`，可由 `SFC_AUTH_*` 調整）。**作業歸屬規則**：未收藏（claim）的作業以 session token 存取；一旦被某帳號收藏，該作業只能由該帳號（cookie）存取，原始 session token 失效（403）。
- 時間格式：秒，浮點數（`start` / `end`）。
- 錯誤格式：`{ "detail": "human readable message" }`（HTTP 狀態碼對應語意）。
- 環境變數以 `SFC_` 為前綴，`.env.example` 列出全部。

## 端點

### `GET /api/health`

```
200 { "status": "ok", "version": "0.1.0" }
```

### `GET /api/metrics` — Prometheus 指標（監控）

`SFC_METRICS_ENABLED=true` 時啟用（預設 `false`）。回傳 Prometheus text format：

- `sfc_http_requests_total{method,path,status}` — HTTP 請求計數
- `sfc_http_request_duration_seconds{method,path}` — 直方圖
- `sfc_active_jobs` — 目前佇列/處理中的作業數
- `sfc_gpu_utilization_percent{gpu}` / `sfc_gpu_memory_used_bytes{gpu}` — NVIDIA GPU（有 GPU 時）
- `sfc_storage_used_bytes` / `sfc_upload_dir_bytes` — 儲存用量
- `sfc_font_dir_bytes` — 字型目錄用量

未啟用時回 `404`。

### `GET /api/config`

回傳給前端顯示的上傳限制與支援語言（`0` = 不限制）：

```
200 {
  "max_upload_mb": 0,
  "max_duration_min": 0,
  "max_queue": 0,
  "supported_languages": ["zh", "en", "ja", "ko", ...],
  "session_remaining_seconds": 0,   // 0 = 該 session 無每日額度
  "tiers": ["lite", "standard", "pro"],
  "llm_available": true,            // LLM 校正可用（ollama 或已設 SFC_LLM_API_KEY）
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

`default_options` 為目前 tier 預設解析後的 ASR 選項（前端上傳時可省略，直接沿用）。

### 使用者詞庫（dictionary）

詞庫是 `{"terms": [...]}` 的 JSON 檔（預設 `SFC_DICTIONARY_PATH`，`./data/user_dictionary.json`），用於建構 ASR `initial_prompt` 與 LLM 校正的詞彙表。所有請求都需帶 `X-Session-Token`。

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/api/dictionary` | 取得全部詞條 → `200 { "terms": ["OpenAI", "WhisperX"] }` |
| POST | `/api/dictionary` | 新增詞條：body `{ "terms": ["OpenAI"] }` → `200 { "terms": [...], "added": ["OpenAI"] }`（`added` 只含實際新增者，大小寫不敏感去重）；`422` 空清單 / 詞條含控制字元 / 超過 100 字元 |
| DELETE | `/api/dictionary` | 刪除一個詞條：body `{ "term": "OpenAI" }`（大小寫不敏感）→ `200 { "ok": true }` |

### `POST /api/jobs` — 上傳影片/音檔

multipart/form-data：

| field | 說明 |
|---|---|
| `file` | 影片或音檔（必填） |
| `language` | 語言代碼，`auto` 或省略 = 自動偵測 |
| `options` | JSON 字串：`{ "model_size": "large-v3", "max_line_chars": 16, "tier": "pro", "denoise_enabled": true, "loudnorm_enabled": true, "llm_correction_enabled": false }`（可省略，用預設） |

伺服器驗證（僅在對應 `SFC_` 變數 > 0 時啟用）：檔案大小 ≤ `MAX_UPLOAD_MB`、ffprobe 時長 ≤ `MAX_DURATION_MIN`、session 每日上傳秒數額度、佇列長度 ≤ `MAX_QUEUE`；變數為 0（預設）時不做限制。

> **大檔分片上傳**：超過 8 MB 的檔案建議改用分片 session（下方端點），可繞過網關/代理（如 GitHub Codespaces 轉發）對單一請求 body 的大小上限。前端會自動選擇。

成功：`202 { "job_id": "...", "status": "queued", "queue_position": 3, "eta_seconds": 120 }`
失敗：`413`（檔案過大）、`429`（額度/佇列滿）、`400`（格式不支援或內容無法解析）、`422`（欄位錯誤）

### 分片上傳 session

| 方法 | 路徑 | 說明 |
|---|---|---|
| POST | `/api/jobs/uploads` | 開啟 session，multipart：`filename`、`language`、`options`（可省略）→ `201 { "upload_id": "..." }` |
| POST | `/api/jobs/uploads/{upload_id}/chunks` | 上傳一片：multipart `index`（0 起）＋ `data`（檔案內容）→ `200 { "ok": true }` |
| POST | `/api/jobs/uploads/{upload_id}/complete` | 合併並建立作業（等同 `POST /api/jobs` 成功回應）→ `202 { "job_id", ... }` |
| DELETE | `/api/jobs/uploads/{upload_id}` | 放棄 session（清理暫存）→ `204` |

- 所有請求都需帶與開 session 相同的 `X-Session-Token`，否則 `403`。
- 分片內容先暫存於 `{UPLOAD_DIR}/.chunks/{upload_id}/`，`complete` 時合併、probe 後入佇列；逾時未完成由清理任務刪除。

### 帳號系統（可選，v2）

| 方法 | 路徑 | 說明 |
|---|---|---|
| POST | `/api/auth/register` | 註冊：body `{ "email", "password", "display_name"? }` → `201 { "id", "email", "display_name", "created_at" }`；`409` email 重複、`422` 格式錯誤 |
| POST | `/api/auth/login` | 登入：body `{ "email", "password" }` → `200 { "id", "email", "display_name", "created_at" }` ＋ 設定 session cookie；`401` 憑證錯誤 |
| POST | `/api/auth/logout` | 登出（清除 cookie，冪等）→ `200 { "ok": true }` |
| GET | `/api/auth/me` | 目前使用者 → `200 {...}`；未登入 `401` |

- 密碼以 PBKDF2-HMAC-SHA256（600k iterations）＋每使用者隨機 salt 儲存；cookie 為 HMAC-SHA256 簽章的 `{user_id}.{expiry}.{digest}`（HttpOnly、`SameSite=Lax`），不存 localStorage（XSS 可讀性考量）。
- 行為為 v1 的「覆蓋層」：不登入仍可完全使用所有功能；登入只是多了作品收藏與作業所有權。

### 作品收藏（v2）

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/api/works` | 列出目前使用者的作品（最新在前）：`200 [ { "id", "job_id", "title", "created_at", "job": { "status", "filename", "duration", "expires_at" } } ]`；未登入 `401` |
| POST | `/api/works/{job_id}` | 收藏（claim）一個 session token 擁有的作業到目前帳號；冪等（重複 claim 回傳既有作品）；`403` 作業屬其他 session/帳號 |
| GET | `/api/works/{work_id}` | 單一作品（含即時 job 狀態）；非本人 `403` |
| DELETE | `/api/works/{work_id}` | 從收藏移除（作業本身不動）→ `200 { "ok": true }` |

- 作業 TTL（48h）到期被清除後，作品列的 `job.status` 回報 `"expired"`，作品本身保留。
- **所有權生效**：一經 claim，該 job 的所有端點（狀態/字幕/媒體/匯出）只接受帳號 cookie；以原始 `X-Session-Token` 存取回 `403`。

### `GET /api/jobs/{job_id}` — 作業狀態

```
200 {
  "job_id": "...",
  "status": "queued" | "processing" | "done" | "failed",
  "stage": null | "extracting" | "preprocessing" | "transcribing" | "segmenting",
  "progress": 0.0,          // 0-100
  "queue_position": 2,      // queued 時有效
  "error": null | "string",
  "created_at": "ISO8601",
  "expires_at": "ISO8601",  // TTL 期限
  "meta": {
    "filename": "x.mp4",
    "duration": 123.4,
    "language": "zh",
    "model_size": "large-v3",
    "tier": "standard",
    "denoise_enabled": true,
    "loudnorm_enabled": true,
    "llm_correction_enabled": false
  }
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

`format` ∈ `srt | vtt | txt | ass | fcpxml | capcut | mp4 | webm_alpha`

- 文字類（srt/vtt/txt/ass/fcpxml）：即時產生，`Content-Type: text/plain; charset=utf-8`，`Content-Disposition: attachment; filename="..."`
- `capcut`：剪映草稿（CapCut draft）Zip — 產生 `{stem}_capcut_draft.zip`（draft_content.json + 對應素材），可直接匯入剪映桌面版/手機版
- `mp4`：燒錄字幕的 H.264 MP4（`video/mp4`）；`webm_alpha`：透明背景 VP9 webm（`video/webm`）
- 作業須為 `done`，否則 `409`。
- query params：`font_size=64`、`font_color=#FFFFFF`、`outline_color=#000000`、`font_family=`、`karaoke=0|1`、`position=bottom|top`（ass/mp4/webm_alpha 適用）；`include_punctuation=true|false`（txt 適用）

### 背景渲染（MP4 / WebM）

轉檔耗時（長片或 4K 可達數十分鐘），採「背景渲染 + 進度輪詢」，避免同步請求被 nginx / 代理逾時（504）：

| 方法 | 路徑 | 回應 |
|---|---|---|
| POST | `/api/jobs/{job_id}/export/{format}/render` | 啟動背景編碼（若已快取直接回 `ready`）：`200 { "status": "rendering" \| "ready" }` |
| GET | `/api/jobs/{job_id}/export/{format}/status` | `200 { "status": "idle" \| "rendering" \| "ready" \| "failed", "error": null \| "..." }` |

- render/status 端點與 `GET .../export/{format}` 使用相同的 query params 指定樣式；render 產物以 `jobs/{job_id}/burned.mp4` / `alpha.webm` 快取。
- 渲染完成前 `GET .../export/{format}` 回 `409`；完成後回傳檔案（attachment）。
- 渲染預設逾時 1 小時（`SFC_RENDER_TIMEOUT_SECONDS`）；逾時或 ffmpeg 失敗時 `status` 回 `failed` 並附 `error`。

### `GET /api/fonts` — 列出字型（內建免費 + 已上傳）

```
200 {
  "fonts": [ { "name": "NotoSansSC", "filename": "NotoSansSC.ttf", "size": 123456, "uploaded_at": "ISO8601" } ],
  "system_fonts": [
    { "name": "LXGW WenKai", "family": "LXGW WenKai", "filename": "LXGWWenKai-Regular.ttf",
      "size": 25575676, "license": "SIL Open Font License 1.1", "license_url": "https://...", "available": true }
  ]
}
```

`system_fonts` 為映像內建的免費字體（Noto 思源黑體/宋體、霞鶩文楷、站酷快樂體/小薇體，全部 SIL OFL），可直接選用（`family` 即 ASS `font_name`），也可下載。

### `POST /api/fonts` — 上傳自訂字型（燒錄用）

multipart/form-data：`file`（.ttf / .otf，必填）。上限 `SFC_MAX_FONT_MB`（0 = 不限制，預設）。

成功：`201 { "name": "...", "filename": "...", "size": 123456 }`
失敗：`400`（非 .ttf/.otf）、`413`（超過大小上限）、`422`（空檔案）

### 字型下載

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/api/fonts/system/{filename}` | 下載內建免費字型檔（attachment） |
| GET | `/api/fonts/{filename}` | 下載已上傳的自訂字型檔（attachment） |

`{filename}` 需為清單中的實際檔名，否則 `404`。

### 錯誤碼總表

| 狀態碼 | 情境 |
|---|---|
| 400 | 缺少/過長 `X-Session-Token`、格式不支援、媒體無法解析、時長超過上限 |
| 401 | 需要登入（未帶 cookie 存取 auth/works 端點） |
| 403 | 分片上傳 session 的 owner token 不符；作業已被他人收藏（claim）後以原始 session token 存取；存取他人作品 |
| 404 | 作業不存在、media/audio 檔案不存在、字型檔不存在、metrics 未啟用 |
| 409 | 作業尚未完成（`require_done`）、render 尚未準備好、email 已註冊 |
| 410 | 作業 TTL 已到期 |
| 413 | 檔案超過 `SFC_MAX_UPLOAD_MB` / 字型超過 `SFC_MAX_FONT_MB`（僅限值 > 0 時） |
| 422 | 不支援的語言、options JSON 無效、空檔案、無效匯出格式/參數、字幕片段驗證失敗、email/password 格式錯誤 |
| 429 | 額度/限流/佇列滿（附 `retry_after_seconds`） |
| 500 | 匯出或 ASR 內部錯誤 |

### 限流 (429)

| 規則 | 預設（0 = 不限制） | 設定 |
|---|---|---|
| 單檔大小 | 0 MB | `SFC_MAX_UPLOAD_MB` |
| 單檔時長 | 0 min | `SFC_MAX_DURATION_MIN` |
| session 每日上傳秒數 | 0 s | `SFC_DAILY_SECONDS_PER_SESSION` |
| 最大佇列長度 | 0 | `SFC_MAX_QUEUE` |
| 同時處理任務數 | 2 | `SFC_MAX_CONCURRENT`（inline 佇列執行緒池大小；celery 模式由 worker `--concurrency` 控制） |
| 檔案 TTL | 48 h | `SFC_TTL_HOURS` |
| 上傳頻率 | 0 次/60s | `SFC_UPLOAD_RATE_LIMIT` |
| render 逾時 | 3600 s | `SFC_RENDER_TIMEOUT_SECONDS` |
| ASR 精準度 tier | `standard` | `SFC_TIER`（`lite` / `standard` / `pro`）；`SFC_BEAM_SIZE`、`SFC_TEMPERATURE`、`SFC_VAD_ENABLED` 可覆寫（留空 = 沿用 tier 預設） |
| 降噪 / 響度標準化 | tier 預設 | `SFC_DENOISE_ENABLED`、`SFC_LOUDNORM_ENABLED`（`true`/`false`，留空 = 沿用 tier 預設）；`SFC_NOISE_REDUCTION_STRENGTH`（noisereduce `prop_decrease`，預設 `0.75`） |
| 使用者詞庫 | `./data/user_dictionary.json` | `SFC_DICTIONARY_PATH`；`SFC_INITIAL_PROMPT_MAX_CHARS`（預設 `1500`） |
| LLM 校正 | tier 預設（pro 開） | `SFC_LLM_CORRECTION_ENABLED`、`SFC_LLM_PROVIDER`（`ollama` / `openai`）、`SFC_LLM_MODEL`（預設 `qwen2.5:7b`）、`SFC_OLLAMA_URL`（預設 `http://localhost:11434`）、`SFC_LLM_API_KEY`、`SFC_LLM_TIMEOUT_SECONDS`（預設 `120`） |
| 帳號 cookie 名稱 | `sfc_session` | `SFC_AUTH_COOKIE_NAME` |
| 帳號 cookie Secure | `false` | `SFC_AUTH_COOKIE_SECURE`（HTTPS 部署設 `true`） |
| 帳號簽章密鑰 | dev 預設值 | `SFC_AUTH_SECRET`（部署務必改） |
| 帳號 session 天數 | 30 | `SFC_AUTH_SESSION_DAYS` |
| 監控指標 | `false` | `SFC_METRICS_ENABLED` |

429 response：`{ "detail": "...", "retry_after_seconds": 60 }`

## 作業生命週期

```
queued → processing(extracting → preprocessing → transcribing → segmenting) → done
                                                                    ↘ failed (error 欄位含訊息)
done → (TTL 到期) → 410
```

`preprocessing` 階段僅在該作業啟用降噪或響度標準化時出現（`denoise_enabled` / `loudnorm_enabled`）。LLM 校正為 best-effort：任何失敗（連線、解析、驗證）都會保留原始逐字稿，不影響作業完成。

## 資料模型（後端）

`jobs` 表：`id (uuid str, pk)`、`session_token`、`status`、`stage`、`progress`、`error`、`filename`、`language`、`model_size`、`tier`、`denoise_enabled`、`loudnorm_enabled`、`llm_correction_enabled`、`duration`、`created_at`、`completed_at`、`expires_at`、`segments_json`（完成後的完整字幕資料，含 words）。`queue_position` 不落庫，由 API 依 active 作業即時計算。

`usage` 表（限流用）：`session_token`、`date`、`uploaded_seconds`（upsert）。

`users` 表（帳號，v2）：`id (int, pk)`、`email`（小寫唯一）、`password_hash`（`pbkdf2_sha256$iter$salt$hash`）、`display_name`、`created_at`。

`works` 表（作品收藏，v2）：`id (int, pk)`、`user_id`（FK users）、`job_id`（**刻意不加 FK** — job 有 TTL 會被刪除，work 要存活並回報 `expired`）、`title`、`created_at`。一 job 至多被一人收藏。

## 儲存佈局

- 上傳原始檔：`{UPLOAD_DIR or S3}/jobs/{job_id}/source.<ext>`
- 抽出的音軌：`{...}/jobs/{job_id}/audio.wav`（16kHz mono）
- 字幕 JSON：存 DB `segments_json`（不再單獨寫檔，避免一致性問題）
- render 產物：`{...}/jobs/{job_id}/burned.mp4`、`{...}/jobs/{job_id}/alpha.webm`
- 自訂字型：`{...}/fonts/<name>.<ext>`；內建免費字體：映像內 `/app/fonts/`（Dockerfile 打包，OFL 授權）
- 分片暫存：`{...}/.chunks/{upload_id}/`（逾時未 complete 由清理任務刪除）
- 清理：Celery beat 每 6 小時執行一次（celery 模式；inline 模式由 API 進程內定時迴圈負責），刪除 `expires_at < now` 的整個 job 目錄 + DB 列、過期的分片暫存

## 前端路由

| 路由 | 頁面 |
|---|---|
| `/` | 上傳頁（含佇列狀態、最近作業清單 localStorage） |
| `/edit/:jobId` | 編輯器（播放器 + 字幕列表 + wavesurfer 時間軸 + 收藏按鈕） |
| `/works` | 我的作品（收藏列表，v2） |
| `/privacy` | 隱私權政策 |
| `/terms` | 服務條款 |

前端 `VITE_API_BASE`（預設 `/api`，vite dev proxy 指向 `http://localhost:8000`）。
