---
name: security-audit
description: 當使用者要求對程式碼進行資安審查、找漏洞、檢查 SQL injection、XSS、command injection、外洩的 API key、硬編碼密碼、依賴套件漏洞、權限控管問題，或任何類似「我的程式碼安全嗎？」「幫我審查資安」「audit this codebase」「/security-audit」的請求時使用。涵蓋 JavaScript/TypeScript、Python、Java、Go、Ruby、Rust、PHP。
---

# Security Audit — 整合式資安審查

對任意專案執行完整資安稽核：自動偵測技術棧、掃描 secrets 與依賴漏洞、
深度檢查注入/認證/資料處理/密碼學/商業邏輯五大類漏洞，追蹤跨檔案資料流，
並以「發現者 ≠ 驗證者」的對抗式角度自我驗證，最後輸出結構化報告與修補提案。

**安全底線：一切只讀，絕不自動修改任何檔案；修補一律只提案，需人工核准。**

## Workflow（8 步驟，依序執行）

### Step 0：上下文建立（Context Building）

先理解程式碼，再開始挖洞。逐檔/逐模組建立心智模型：

1. 讀取 README、專案結構、入口檔案（main / app / index / server）。
2. 標出**信任邊界**：哪些是外部輸入（HTTP 參數、headers、body、檔案上傳、
   WebSocket、queue、cron、第三方 callback），哪些是內部資料。
3. 標出**危險 sink**：DB 查詢、`exec`/`eval`/`spawn`、HTML 輸出、檔案寫入、
   反序列化、加密/簽章、SSRF 可達的 URL fetch。
4. 列出認證/授權機制：session、JWT、API key、RBAC/ACL，誰能碰什麼。

沒有心智模型就開始掃描，會漏掉跨模組漏洞。

### Step 1：Scope Resolution

- 使用者有指定路徑 → 只掃該路徑；否則掃整個 repo（含 config、CI/CD、
  Dockerfile、IaC、scripts）。
- 判斷語言與框架：檢查 `package.json` / `requirements.txt` / `pyproject.toml` /
  `go.mod` / `Cargo.toml` / `pom.xml` / `Gemfile` / `composer.json`。
- 依偵測到的語言，只讀 `references/language-patterns.md` 對應段落
  （避免把無關語言的規則塞進分析）。

### Step 2：Dependency Audit

依偵測到的生態系檢查鎖檔是否有已知 CVE 套件：

| 生態系 | 鎖檔 |
|---|---|
| npm | `package-lock.json` / `yarn.lock` / `pnpm-lock.yaml` |
| pip | `requirements*.txt` / `Pipfile.lock` / `poetry.lock` / `uv.lock` |
| Maven | `pom.xml` |
| Rubygems | `Gemfile.lock` |
| Cargo | `Cargo.lock` |
| Go | `go.mod` / `go.sum` |

比對 `references/vulnerable-packages.md` 的已知 CVE 清單；對照 OSV.dev /
GitHub Advisory / NVD 確認目前是否仍受影響、是否已有修復版本。**只列
「有明確 CVE 且當前版本受影響」的項目**，版本已修復者降為 INFO。

### Step 3：Secrets & Exposure Scan

掃描所有檔案（含 config、CI/CD、Dockerfile、IaC、`.git` 外的歷史殘留），
找：

- 硬編碼 API key / token / 私鑰（regex 與熵值偵測，見
  `references/secret-patterns.md`）。
- `.env` / 憑證檔誤提交進 repo。
- 雲端憑證（AWS / GCP / Azure / Stripe / Twilio 等）。
- 除錯後門：`DEBUG=True`、`console.log` 洩漏 token、測試金鑰誤當正式金鑰。
- 過度開放的權限設定：world-readable 檔案、`chmod 777`、IAM `*:*`。

### Step 4：Vulnerability Deep Scan

依 `references/vuln-categories.md` 的偵測訊號逐一檢查五大類：

- **Injection**：SQLi / XSS / 命令注入 / LDAP / Log Injection / SSTI / 路徑注入
- **Auth & Access Control**：IDOR / BOLA / JWT weakness / CSRF / mass assignment /
  密碼規則 / session 管理 / 權限檢查缺失
- **Data Handling**：SSRF / 路徑穿越 / XXE / 不安全反序列化 / zip-slip /
  敏感資料外洩（log、錯誤訊息、回應過度回傳）
- **Cryptography**：弱雜湊（MD5/SHA1 存密碼）、硬編碼 IV/金鑰、弱亂數、
  自製加密、錯誤 padding 處理
- **Business Logic**：race condition / rate limiting 缺失 / 金額與數量驗證 /
  狀態機繞過 / 重放攻擊

### Step 5：Cross-File Data Flow Analysis

追蹤使用者輸入從**入口點**到**危險 sink** 的完整路徑，找出跨檔案才會
浮現的漏洞：

```
入口點（HTTP 參數 / headers / body / 檔案上傳 / queue 訊息 / 第三方 callback）
  → 中間層（驗證、轉換、儲存、快取）
  → 危險 sink（DB 查詢 / exec 呼叫 / HTML 輸出 / 檔案寫入 / 反序列化）
```

沿途檢查：輸入是否有驗證？驗證是否可被繞過（double-encoding、type juggling、
Unicode 正規化）？sink 是否使用安全 API（參數化查詢、`subprocess` list 形式、
escaping）？權限檢查是在資料存取**之前**還是之後？

### Step 6：對抗式自我驗證（Adversarial Self-Verification）

每個 candidate finding 在列入報告前，必須用**與發現角度不同**的角度反問：

- 這個輸入真的能到達這個 sink 嗎？中間是否有擋下的驗證？
- 框架/上游是否已經防住？（ORM 參數化、React 自動 escaping、框架 CSRF 保護）
- 是否為誤判？（靜態掃描假陽性、已修復版本、不可能達成的路徑）
- 利用條件是否真的成立？攻擊者要控制哪些前置狀態？

驗證後仍成立的 finding 才列入報告，並標注信心度（High/Medium/Low）。
大型專案可用 team mode 讓不同 agent 分別負責「發現」與「驗證」，
確保驗證者不是發現者本人。

### Step 7：Generate Report

依 `references/report-format.md` 模板輸出結構化報告：

1. **發現摘要表**（依 Severity 計數）
2. **依類別分組**的逐項發現（檔案/行號/程式碼片段/白話風險/信心度）
3. 掃描範圍與方法說明

若乾淨無漏洞，**明確說「未發現漏洞」**並列出掃描範圍，不要硬湊發現。

### Step 8：Propose Patches

只對 **CRITICAL / HIGH** 給修補 diff 建議，明確聲明「尚未套用，需人工確認」。
每個 patch 必須：

- 最小改動、對應單一 finding
- 使用安全寫法（參數化查詢、`secrets` 模組、框架內建機制）
- 不引入新依賴（除非必要）

MEDIUM/LOW/INFO 只給書面建議，不給 diff。

## Severity 分級

| Severity | 說明 | 範例 |
|---|---|---|
| 🔴 CRITICAL | 立即可被利用，資料外洩風險 | SQL Injection、RCE、認證繞過 |
| 🟠 HIGH | 明確攻擊路徑存在 | XSS、IDOR、硬編碼密鑰 |
| 🟡 MEDIUM | 需特定條件或串連才能利用 | CSRF、開放重導向、弱加密 |
| 🔵 LOW | 最佳實踐違反，直接風險低 | 錯誤訊息過於詳細、缺少安全標頭 |
| ⚪ INFO | 觀察但非漏洞 | 依賴版本過舊但無已知 CVE |

## Output Rules

- 一律先出「發現摘要表」（依 Severity 計數）。
- 絕不自動套用任何修補，只提案。
- 每個 finding 附信心度（High/Medium/Low）。
- 依「類別」分組，不是依「檔案」分組。
- 具體到檔案路徑、行號、有問題的程式碼片段。
- 用白話文解釋風險：「攻擊者可以做什麼？」。
- 每個 CRITICAL/HIGH finding 必須註明已通過 Step 6 對抗式驗證。
- 若乾淨無漏洞，明確說「未發現漏洞」並列出掃描範圍。
- 報告結尾列出掃描範圍、方法與未檢查項目（如：無法驗證的 runtime 行為）。