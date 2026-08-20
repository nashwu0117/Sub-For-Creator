# 已知 CVE 套件清單（依生態系）

Step 2 Dependency Audit 的起點。**重要**：本清單是「歷史上有名且常被掃到的
CVE」起始清單，**不是即時權威資料**。每個命中都必須用當前權威來源複查：

- 通用：**OSV.dev**（`osv-scanner`）、**GitHub Advisory Database**（`ghsa`）、
  **NVD**（nvd.nist.gov）
- npm：`npm audit`；pip：`pip-audit` / `pipenv check`；Maven：
  `mvn org.owasp:dependency-check-maven`；Ruby：`bundle audit`；Cargo：
  `cargo audit`；Go：`govulncheck`

規則：套件在清單上但版本已 >= 修復版本 → 不列為 finding（最多 INFO 註記
「版本已修復」）。套件不在清單上 ≠ 安全——以權威來源為準。

---

## npm / JavaScript

| 套件 | 受影響 | 修復版本 | 主要 CVE / 說明 |
|---|---|---|---|
| `lodash` | < 4.17.21 | 4.17.21 | CVE-2021-23337（命令注入）、prototype pollution |
| `minimist` | < 1.2.6 | 1.2.6 | CVE-2021-44906（prototype pollution，經由無數間接依賴） |
| `ua-parser-js` | < 0.7.33 / < 1.0.33 | 0.7.33 / 1.0.33 | CVE-2022-25927（ReDoS） |
| `event-stream` | 3.3.6（含惡意後門） | 移除/換 flatmap-stream | 2018 supply-chain 攻擊 |
| `node-fetch` | < 2.6.7 / < 3.2.10 | 2.6.7 / 3.2.10 | CVE-2022-0235（大小寫混淆繞過 allowlist） |
| `qs` | < 6.10.3 | 6.10.3 | CVE-2022-24999（prototype pollution，express < 4.17.3 亦受影響） |
| `jsonwebtoken` | < 9.0.0 | 9.0.0 | CVE-2022-23529（secretOrPublicKey 型別混淆） |
| `moment` | < 2.29.4 | 2.29.4 | CVE-2022-31129（ReDoS） |
| `axios` | < 0.21.2 | 0.21.2 | CVE-2021-3749（SSRF：`allowAbsoluteUrls`） |
| `ws` | < 7.4.6 / < 8.17.1 | 7.4.6 / 8.17.1 | CVE-2024-37890（無上限 frame 數 → DoS） |
| `next.js` | < 12.0.9（舊版） | 各 minor 最新 | 多起 XSS/DoS；定期 `npm audit` |
| `undici` | < 5.19.1 等 | 各 minor 最新 | 多起 request smuggling / DoS |

## pip / Python

| 套件 | 受影響 | 修復版本 | 主要 CVE / 說明 |
|---|---|---|---|
| `python-multipart` | < 0.0.7 | 0.0.7 | CVE-2024-24762（multipart DoS；FastAPI 依賴它） |
| `pillow` | 多個舊版 | 最新（如 ≥ 10.0.0） | 大量影像解碼 RCE/DoS（CVE-2023-44271 等） |
| `requests` / `urllib3` | urllib3 < 1.24.2 | urllib3 最新 | CVE-2018-20060（`CVE-2018-20060`/CVE-2019-11236 等） |
| `pyyaml` | < 5.4 | 5.4 | CVE-2020-14343（unsafe load 的 RCE 面） |
| `jinja2` | < 3.1.4 | 3.1.4 | CVE-2024-34064（HTML attribute 注入/DoS） |
| `cryptography` | < 3.3.2 | 3.3.2 | CVE-2020-25659（不安全的 RSA 加密 padding oracle） |
| `django` | 各 minor 舊版 | 每 minor 最新 patch | 大量（XSS、DoS、auth 繞過）；定期看 release notes |
| `werkzeug` | < 2.2.3 | 2.2.3 | CVE-2023-25577（multipart DoS） |
| `flask` | < 2.3.3 | 2.3.3 | CVE-2023-30861（cookie 長度 DoS） |
| `scrapy` | < 2.11.1 | 2.11.1 | CVE-2024-52532（HTTP auth 繞過） |
| `aiohttp` | < 3.10.2 | 3.10.2 | CVE-2024-23334（靜態檔案目錄穿越） |
| `gunicorn` | < 22.0.0 | 22.0.0 | CVE-2024-6827（request smuggling） |

## Maven / Java

| 套件 | 受影響 | 修復版本 | 主要 CVE / 說明 |
|---|---|---|---|
| `log4j-core` | < 2.17.1 | 2.17.1（2.17.0 亦有 DoS） | CVE-2021-44228 Log4Shell（RCE）、CVE-2021-45105（DoS） |
| `logback` | < 1.2.9 | 1.2.9 | CVE-2021-42550（JNDI） |
| `spring-core` / `spring-webmvc` | < 5.3.18 / < 5.2.20 | 5.3.18 / 5.2.20 | CVE-2022-22965 Spring4Shell（RCE） |
| `struts2` | 多個舊版 | 各版本對應 patch | S2-045（CVE-2017-5638）、S2-057（CVE-2019-0230）等 RCE 系列 |
| `jackson-databind` | 多個舊版 | 每 minor 最新 | 大量 polymorphic deserialization RCE |
| `commons-text` | < 1.9 | 1.9 | CVE-2022-42889 Text4Shell（JNDI RCE） |
| `shiro`（Apache Shiro） | < 1.10.0 / < 2.0.0-alpha | 1.10.0 | CVE-2023-34478（認證繞過） |
| `xstream` | < 1.4.20 | 1.4.20 | 多起反序列化 RCE |
| `tomcat`（內嵌於 spring-boot） | < 9.0.83 / < 10.1.15 | 各線最新 | 多起 smuggling / DoS |
| `netty` | < 4.1.86 等 | 各 minor 最新 | HTTP/2 系列（含 CVE-2023-44487 影響） |

## Rubygems / Ruby

| 套件 | 受影響 | 修復版本 | 主要 CVE / 說明 |
|---|---|---|---|
| `rack` | < 2.2.6.4 / < 3.0.6.1 | 2.2.6.4 / 3.0.6.1 | CVE-2022-44570（DoS）、CVE-2023-27539 等 |
| `actionpack`（Rails） | 各 minor 舊版 | 每 minor 最新 patch | XSS / DoS / 繞過系列；定期升級 |
| `nokogiri` | < 1.13.6 | 1.13.6 | CVE-2022-23437（ReDoS） |
| `puma` | < 5.6.7 / < 6.0.1 | 5.6.7 / 6.0.1 | CVE-2023-40175（HTTP request smuggling） |
| `devise` | < 4.7.1 | 4.7.1 | CVE-2019-16109（email 正規化繞過） |
| `rails-html-sanitizer` | < 1.4.4 | 1.4.4 | CVE-2022-32209（XSS） |
| `loofah` | < 2.19.1 | 2.19.1 | CVE-2022-23515（XSS） |

## Cargo / Rust（RUSTSEC）

| 套件 | 受影響 | 修復版本 | 主要 ID / 說明 |
|---|---|---|---|
| `chrono` | < 0.4.20 | 0.4.20 | RUSTSEC-2020-0159（`localtime_r` UB） |
| `time` | < 0.2.23 / < 0.3.5 | 0.2.23 / 0.3.5 | RUSTSEC-2020-0071（`local_offset` UB） |
| `regex` | < 1.5.5 | 1.5.5 | CVE-2022-24713（ReDoS） |
| `openssl` / `openssl-src` | 各舊版 | 各 minor 最新 | RUSTSEC-2023-0022 等（openssl CVE 鏡像） |
| `rustls` / `rustls-webpki` | < 0.20.6 / < 0.21.1 | 對應版本 | CVE-2023-43669（webpki 信任錨） |
| `hyper` | < 0.14.18（HTTP/2） | 0.14.18+ | CVE-2021-32714（HTTP/2）等 |
| `tokio` | < 1.8.4 / < 1.13.1（oneshot） | 對應版本 | RUSTSEC-2021-0072（oneshot 關閉後 data race） |
| `zip` | < 0.6.6 / < 1.2.0 | 對應版本 | CVE-2023-29608（zip-slip / DoS） |
| `tar` | < 0.4.38 | 0.4.38 | CVE-2023-39141（symlink 穿越） |
| `h2` | < 0.3.17 / < 0.4.2 | 對應版本 | CVE-2023-44487（HTTP/2 rapid reset） |

## Go modules

| 套件 | 受影響 | 修復版本 | 主要 CVE / 說明 |
|---|---|---|---|
| `golang.org/x/net` | < 0.17.0（HTTP/2） | 0.17.0 | CVE-2023-44487（rapid reset DoS） |
| `golang.org/x/text` | < 0.3.8 | 0.3.8 | CVE-2021-38561（BOM 處理 DoS） |
| `golang.org/x/crypto` | < 0.17.0 | 0.17.0 | CVE-2023-48795 Terrapin（SSH） |
| `github.com/gin-gonic/gin` | < 1.7.7 | 1.7.7 | CVE-2020-28483（`gin.Dump` XSS / 路徑處理） |
| `github.com/dgrijalva/jwt-go` | < 4.0.0（已封存） | 改用 `golang-jwt/jwt` | CVE-2020-26160（aud 驗證缺失） |
| `github.com/labstack/echo` | < 4.10.0 | 4.10.0 | CVE-2022-40003（`SplitHostPort` 繞過） |
| `github.com/gorilla/websocket` | < 1.4.2 | 1.4.2 | CVE-2020-27813（無限制 control frame → DoS） |
| `github.com/go-git/go-git` | < 5.4.2 | 5.4.2 | CVE-2023-44313（path traversal） |
| 標準庫 `net/http` | Go < 1.20.11 等 | 各線最新 patch | CVE-2023-44487（HTTP/2）、CVE-2023-24538（HTML escaping） |

---

## 執行指引

1. 先跑生態系對應的自動掃描工具（`npm audit` / `pip-audit` / `govulncheck` /
   `cargo audit` / `bundle audit` / OWASP dependency-check），拿當前權威結果。
2. 對照本清單補查工具可能漏掉的間接/傳遞依賴。
3. 命中規則：**受影響版本 + 有實際利用路徑** → HIGH/MEDIUM（依可達性）；
   已修復 → INFO；工具報但本清單無 → 以工具為準並標注來源。
4. 商業依賴（有 license 限制）與開發依賴（devDependencies）分開計，避免
   高估生產風險。