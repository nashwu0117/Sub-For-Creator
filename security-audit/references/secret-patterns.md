# Secrets / API Key 偵測：regex 與熵值啟發式

Secrets & Exposure Scan（Step 3）的查詢表。**規則：只回報「看起來像真的
金鑰」的命中**——測試金鑰、明顯的範例字串（`example`、`test`、`changeme`、
`xxxx`）不算 finding（頂多 INFO）。高價值 finding 需人工確認後才列入報告。

---

## 1. 供應商特定 Pattern（高信心度）

| 供應商 | Pattern | 範例前綴 |
|---|---|---|
| AWS Access Key | `AKIA[0-9A-Z]{16}` | `AKIAIOSFODNN7EXAMPLE` |
| AWS Secret Key | `(?i)aws.{0,20}(secret|access).{0,20}['\"][0-9a-zA-Z/+]{40}['\"]` | `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY` |
| GCP API Key | `AIza[0-9A-Za-z\-_]{35}` | `AIzaSy...` |
| GCP Service Account | `"type": "service_account"` 附近的 `private_key` 區塊 | `-----BEGIN PRIVATE KEY-----` |
| Azure Storage Key | `AccountKey=[A-Za-z0-9+/=]{80,}` | `DefaultEndpointsProtocol=https;AccountKey=...` |
| Azure Client Secret | `(?i)azure.{0,20}(client_secret|clientsecret).{0,20}['\"][0-9A-Za-z_~\-]{30,}['\"]` | |
| Stripe Live Key | `sk_live_[0-9a-zA-Z]{16,}` | `sk_live_...` |
| Stripe Restricted | `rk_live_[0-9a-zA-Z]{16,}` | `rk_live_...` |
| Twilio | `SK[0-9a-fA-F]{32}` / `AC[0-9a-fA-F]{32}` | `SK...`、`AC...` |
| GitHub Token | `ghp_[0-9A-Za-z]{36}` / `gho_` / `ghu_` / `ghs_` / `ghr_` | `ghp_...` |
| GitHub Fine-grained | `github_pat_[0-9A-Za-z_]{22,}` | `github_pat_...` |
| GitLab | `glpat-[0-9A-Za-z\-_]{20,}` | `glpat-...` |
| Slack | `xox[baprs]-[0-9A-Za-z\-]{10,}` | `xoxb-...`、`xoxa-...` |
| Discord Bot | `[MN][A-Za-z\d]{23}\.[\w-]{6}\.[\w-]{27}` | `M...`、`N...` |
| OpenAI | `sk-[0-9A-Za-z]{20}T3BlbkFJ[0-9A-Za-z]{20}` | `sk-...T3BlbkFJ...` |
| Anthropic | `sk-ant-[0-9A-Za-z\-_]{20,}` | `sk-ant-...` |
| Google OAuth | `[0-9]+-[0-9A-Za-z_]{32}\.apps\.googleusercontent\.com` | `12345-xxx.apps.googleusercontent.com` |
| SendGrid | `SG\.[0-9A-Za-z\-_]{22}\.[0-9A-Za-z\-_]{43}` | `SG.xxxx.yyyy` |
| Square | `sq0atp-[0-9A-Za-z\-_]{22}` | `sq0atp-...` |
| Shopify | `shpat_[0-9a-fA-F]{32}` | `shpat_...` |
| npm token | `npm_[0-9A-Za-z]{36}` | `npm_...` |
| PyPI token | `pypi-AgEIcHlwaS5vcmc[A-Za-z0-9\-_]{50,}` | `pypi-AgEIcHlwaS5vcmc...` |
| DigitalOcean | `dop_v1_[0-9a-fA-F]{64}` | `dop_v1_...` |
| Heroku | `(?i)heroku.{0,20}[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}` | |
| Firebase | `AIza[0-9A-Za-z\-_]{35}`（同 GCP） | |
| JWT（疑似洩漏） | `eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}` 出現在非測試檔、含 `secret`/`signing` 字樣 | `eyJhbGciOi...` |

## 2. 通用 Pattern（需熵值/情境驗證）

| 類型 | Pattern | 附註 |
|---|---|---|
| 私鑰 | `-----BEGIN (RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----` | 任何環境都算 HIGH |
| PEM 憑證金鑰 | `-----BEGIN CERTIFICATE-----` 旁的私鑰檔 | 私鑰在 repo = HIGH |
| Generic API Key 賦值 | `(?i)(api[_-]?key|apikey|secret|token|password|passwd|pwd|client[_-]?secret)\s*[:=]\s*['\"][^'\"]{12,}['\"]` | 需排除範例/測試值 |
| 連線字串 | `(?i)(mongodb(\+srv)?|postgres(ql)?|mysql|redis|amqp)://[^\s'\"<>]+` 含密碼 | 比對 `user:pass@` 形式 |
| .env 誤提交 | 檔名 `.env`、`.env.production`、`*.pem`、`*.key`、`credentials.json`、`secrets.yml`、`id_rsa` | 在 git 追蹤中即為 finding |
| 雲端 metadata | `169.254.169.254` 出現在程式碼（SSRF 目標） | 搭配 SSRF 檢查 |

## 3. 熵值偵測（Entropy Heuristics）

對「看起來像亂碼」的長字串做 Shannon entropy：

```
entropy = -Σ p(c) · log2(p(c))   （對每個字元類別：小寫/大寫/數字/符號）
```

- **門檻**：長度 ≥ 20 且 entropy ≥ 4.5（bits/char）→ candidate。
- **加分**：字串含大小寫混合 + 數字 + 符號；出現在 `=`/`:` 之後的引號內。
- **減分/排除**：base64 編碼的樣本資料、uuid（含連字號的固定格式）、
  hash 輸出（`sha256` 的 hex 是 40 字元固定格式，若變數名為 `hash`/`digest`
  則排除）、`example`/`test`/`fake`/`dummy`/`changeme`/`placeholder`/
  `xxxxx`、明顯的 lorem ipsum。
- **情境驗證**：命中後看變數名稱與使用位置——`api_key = "..."` 且字串高熵
  → 高信心；`seed = "..."` 且是測試 fixture → 低信心。

## 4. 誤報排除清單（常見假陽性）

| 排除 | 原因 |
|---|---|
| 測試 fixture / 範例資料 | `test_*` 目錄、`examples/`、文件中的示範金鑰（多為 `EXAMPLE` 字樣） |
| 公開文件中的範例 | README、文件內 `sk_test_` / `AKIA...EXAMPLE` |
| 已撤銷的已知洩漏金鑰 | 若可確認（如 GitHub secret scanning 已標記）降為 INFO |
| 金鑰 hash 而非金鑰本身 | `sha256(api_key)` 用於比對是安全寫法，不是洩漏 |
| 長 UUID / hash 字串 | 格式固定、非隨機字元集 |
| 密碼欄位雜湊值 | `password_hash` 欄位存 bcrypt 字串是安全寫法 |

## 5. 報告規則

- 供應商特定 pattern 命中（非排除清單）→ 至少 **HIGH**，附 pattern 名稱。
- 私鑰/憑證在 repo → **HIGH**（即使標示測試）。
- 通用 pattern + 熵值過關 → **MEDIUM**（需情境佐證）。
- 排除清單命中 → 不列入或 **INFO** 附註。
- 每個列入報告的 secrets finding 都標注：檔案、行號、pattern/熵值、
  信心度、建議動作（撤銷輪換 + 移出 git 歷史）。