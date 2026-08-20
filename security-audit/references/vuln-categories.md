# 漏洞分類：偵測訊號與安全寫法對照

本檔是 Vulnerability Deep Scan（Step 4）的查詢表：看到「偵測訊號」中的
模式，就懷疑對應漏洞；對照「安全寫法」確認是否已防住。

---

## 1. Injection（注入）

| 子類 | 偵測訊號（看到就要懷疑） | 安全寫法 |
|---|---|---|
| SQL Injection | 字串串接進 SQL：`f"SELECT * FROM users WHERE id = {uid}"`、`"..." + request.args.get("id") + "..."`、`db.execute(sql, raw)`、`.format()`/`%` 組 SQL | 參數化查詢 / ORM：`SELECT ... WHERE id = ?`、`session.execute(text(...), params)`；**永遠不要**把使用者輸入拼進 SQL 字串 |
| NoSQL Injection | MongoDB `$where`、`$gt`/`$ne` 操作符注入、把 query dict 直接傳入 `collection.find(user_input)` | 白名單欄位、型別強制、禁止操作符字串進入 query |
| XSS（反射/儲存） | `innerHTML = userInput`、`dangerouslySetInnerHTML`、`v-html`、`document.write`、`eval`、`new Function`、`window.open(url)` 接未驗證輸入、模板 `{{ user_content | safe }}` | 預設 escaping（React/Vue 文字節點）；`textContent` 取代 `innerHTML`；真要 HTML 用 DOMPurify 白名單消毒；`<script>` 內容放入 JSON 前先轉義 `</` |
| Command Injection | `os.system(cmd + user_input)`、`subprocess.run(f"...{x}...", shell=True)`、`exec`/`eval`、`child_process.exec`、`ProcessBuilder("sh", "-c", ...)`、`Runtime.getRuntime().exec` | `subprocess.run([...])` list 形式（不經 shell）、`execFile`、`ProcessBuilder` list 參數；永遠 `shell=False`；白名單驗證參數 |
| LDAP Injection | LDAP filter 串接使用者輸入：`(&(uid={user})(password={pass}))` | 使用 LDAP 函式庫的 escaping（`ldap3.utils.conv.escape_filter_chars`），或先驗證格式 |
| Log Injection | `logger.info(f"user: {username}")` 未過濾 CR/LF | 移除/轉義 `\r`、`\n`；記錄時加 `%r` 或 JSON 序列化 |
| SSTI | 使用者輸入進模板引擎：`Template(user_template)`（Jinja2/Pug/EJS）、`render_template_string` | 不允許使用者控制模板本體；只把輸入當變數傳入預編譯模板 |
| 路徑/名稱注入 | 檔名、語言、format 等參數直接進 `open()`/路徑組裝（見 Data Handling 路徑穿越） | 白名單 + 正規化 + 驗證 |

## 2. Auth & Access Control（認證與授權）

| 子類 | 偵測訊號 | 安全寫法 |
|---|---|---|
| IDOR / BOLA | 直接用使用者提供的 ID 取資源而不檢查所有權：`GET /api/orders/{id}` 只有登入檢查、沒有「此單屬於此人」檢查；`db.get(User, user_id)` 用 request 參數 | 資源存取前檢查 owner/scope：`if resource.owner_id != current_user.id: 403`；用查詢條件帶入 current_user，而非先取再比對 |
| 缺失認證 | 敏感路由沒有 auth middleware、`Depends(get_current_user)` 只加在部分路由、admin 路由僅靠前端隱藏 | 所有敏感路由統一掛 auth；admin 用獨立權限檢查（RBAC）；預設拒絕 |
| JWT weakness | `alg: none` 可選、`HS256` 用伺服器公鑰當 secret、secret 寫死在程式碼、無 `exp`、payload 放敏感資料未加密、`jwt.decode(..., verify=False)` | 固定 `RS256/ES256`；secret 走環境變數/金鑰管理；強制驗 `exp`/`aud`；拒絕 `alg=none` |
| CSRF | 狀態改變請求（POST/PUT/DELETE）只有 cookie session、無 CSRF token、無 SameSite、無 origin 檢查 | CSRF token（double-submit 或 signed）、`SameSite=Lax/Strict`、檢查 `Origin`/`Referer`；API 用 Bearer token 而非 cookie 則不受 CSRF 影響 |
| Mass Assignment | 直接把 request body 塞進 model：`User(**request.json)`、`Model.objects.create(**params)`、`update(request.form)` 含 `role`/`is_admin` | 顯式白名單欄位（`serializer`/`Schema` 只定義可寫欄位）；禁止 `**kwargs` 直接進 model |
| 密碼管理 | 明文存密碼、`md5(password)`、`sha1(password + salt)`、自製 hash 疊加、密碼長度無下限、無 rate limiting | `bcrypt`/`argon2`/`scrypt`；`pbkdf2_hmac`（高 iteration）；密碼最少 8-12 字元；登入失敗 rate limit |
| Session 管理 | session 固定（登入前後 session ID 不變）、cookie 無 `HttpOnly`/`Secure`/`SameSite`、session 永不過期、logout 不清 session | 登入後 rotation session ID；cookie 加 `HttpOnly; Secure; SameSite`；設過期；logout 銷毀 |
| 授權檢查位置 | 檢查寫在 UI 而非 API、權限檢查在資料存取**之後** | 權限檢查必須在 API 層、資料存取之前；**伺服器端**做，前端隱藏不算數 |

## 3. Data Handling（資料處理）

| 子類 | 偵測訊號 | 安全寫法 |
|---|---|---|
| SSRF | 使用者可控 URL 直接 fetch：`requests.get(user_url)`、`urllib.request.urlopen`、`fetch(input.url)`、`curl`/`wget` 接參數；內網服務無防護 | 白名單 host/port 或網域；禁止私有 IP 段（127.0.0.0/8、10/8、172.16/12、192.168/16、169.254、::1）；解析後再次驗證 IP（DNS rebinding）；`redirects=False` |
| 路徑穿越 | `open(os.path.join(base, user_filename))` 未驗證、`Path(user_input)`、`send_file(user_path)`、zip 解壓直接寫入 | 正規化後驗證前綴：`resolved = (base / name).resolve(); if not resolved.is_relative_to(base): reject`；解壓時逐檔檢查路徑（zip-slip） |
| XXE | XML 解析未關外部實體：`lxml.etree.parse`（預設）、`ElementTree`（部分版本）、`DocumentBuilderFactory` 未設 `disallow-doctype-decl`、`XmlReader` 未設 `DtdProcessing.Prohibit` | 關閉 DTD/外部實體：`XMLParser(resolve_entities=False, no_network=True)`、`setFeature("http://apache.org/xml/features/disallow-doctype-decl", true)`；能不用 XML 就不用（改 JSON） |
| 不安全反序列化 | `pickle.loads`、`yaml.load`（未指定 SafeLoader）、`eval(input)`、`ObjectInputStream.readObject`、`Marshal.load`、Ruby `Marshal.load`、PHP `unserialize` | 一律改用 JSON/msgpack；`yaml.safe_load`；永不反序列化不可信資料；Java 用白名單 filter |
| 敏感資料外洩 | 錯誤訊息回傳 stack trace/DB 連線字串、log 記錄 token/密碼/信用卡、API 回應回傳多餘欄位（`user` 含 `password_hash`）、`__dict__`/`vars()` 直接序列化 | 錯誤回應只給泛化訊息；log 前過濾敏感欄位；序列化用顯式 schema；測試金鑰與正式金鑰分離 |
| 檔案上傳 | 無副檔名/內容驗證、`os.path.join(upload_dir, filename)` 直接用原始檔名、`Content-Type` 只看 header | 伺服器端產生檔名（uuid）；白名單副檔名 + magic bytes 驗證；限制大小；不執行上傳目錄 |
| Zip-Slip | 解壓縮時把 `zip_entry.filename` 直接當路徑寫入 | 正規化 + `is_relative_to` 檢查；拒絕 `..`/絕對路徑 entry |

## 4. Cryptography（密碼學）

| 子類 | 偵測訊號 | 安全寫法 |
|---|---|---|
| 弱雜湊 | `md5`/`sha1` 存密碼或簽章、`hashlib.md5(password.encode())`、`MessageDigest.getInstance("MD5")` | 密碼用 bcrypt/argon2/scrypt；簽章用 SHA-256+ |
| 硬編碼金鑰/IV | `key = "mysecretkey123"`、IV 寫死、`secret = "..."` 在程式碼裡 | 金鑰走 env/secret manager；IV 每次隨機（`os.urandom`/`secrets`）；金鑰輪換 |
| 弱亂數 | `random.random()`/`random.randint` 用在 token、密碼重設、session、金鑰生成 | `secrets.token_*` / `os.urandom` / `SecureRandom`；`random` 只可用於非安全用途 |
| 自製加密 | 自寫 XOR/自訂演算法、`base64` 當加密、混淆當安全 | 用標準庫/成熟函式庫：`cryptography`、`PyNaCl`、`libsodium` |
| 錯誤 padding 處理 | 手動處理 AES-CBC padding、錯誤訊息區分「padding 錯誤」與「金鑰錯誤」（oracle） | 用 AEAD（`AESGCM`/`ChaCha20Poly1304`）；錯誤訊息統一 |
| 不安全模式 | ECB 模式、CBC 無 MAC、`AES.new(key, AES.MODE_ECB)` | GCM/ChaCha20-Poly1305（authenticated encryption）；先認證後解密 |

## 5. Business Logic（商業邏輯）

| 子類 | 偵測訊號 | 安全寫法 |
|---|---|---|
| Race Condition | 先檢查後寫入（check-then-act）無鎖：餘額扣款 `if balance >= amount: deduct`、庫存、兌換碼、註冊唯一性；`get` 後 `update` 之間有 await | 資料庫 atomic 操作/交易 + 條件更新（`UPDATE ... WHERE balance >= ?`）；樂觀鎖（version 欄位）；唯一約束 |
| Rate Limiting 缺失 | 登入、OTP、註冊、API 無任何限制；重置密碼無冷卻 | 依端點加 rate limit（IP + 帳號維度）；登入失敗鎖定/遞增延遲 |
| 金額/數量驗證 | 前端傳價格/數量直接採用、負數/零未檢查、溢位 | 金額伺服器端計算；驗證範圍與型別；整數分/cent 儲存 |
| 狀態機繞過 | 訂單/作業狀態可任意跳轉、無狀態轉換驗證、重複送出 | 定義合法狀態轉換表；伺服器端驗證目前狀態；冪等鍵 |
| 重放攻擊 | 請求無 nonce/timestamp 驗證、webhook 無簽章驗證 | webhook 驗簽（HMAC）+ timestamp 窗口 + nonce 去重；付款/兌換操作加冪等 |
| 授權依賴前端 | 價格、權限、步驟控制全在 client 端 | 所有關鍵決策伺服器端重驗 |

---

## 使用方式

Step 4 掃描時：看到「偵測訊號」欄的模式 → 記為 candidate finding →
進入 Step 5 追資料流 → Step 6 對抗式驗證（檢查「安全寫法」欄是否已被
上游/框架採用）。兩欄都命中同一模式時，以實際程式碼為準，不靠欄位猜測。