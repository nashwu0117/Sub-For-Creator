# 語言 / 框架特有漏洞模式

Step 1 偵測到語言後，只讀對應段落。本檔是「框架怎麼寫才容易出錯」的
對照表——通用漏洞（SQLi/XSS/SSRF 等）見 `vuln-categories.md`，本檔只列
**該生態系特有的坑**。

---

## JavaScript / TypeScript（Express / React / Next.js / Node）

| 模式 | 偵測訊號 | 安全寫法 |
|---|---|---|
| prototype pollution | `Object.assign({}, user_input)`、`_.merge`/`_.defaultsDeep`、`JSON.parse` 後遞迴合併、`qs` 舊版 | 用 `structuredClone`/白名單欄位；升級 `qs`；禁止 `__proto__`/`constructor` key |
| `eval` / `new Function` / `vm.runInNewContext` | 任何使用者輸入進 eval 家族 | 移除；必要時用 sandbox 仍屬高風險 |
| ReDoS | 使用者可控 regex：`new RegExp(user_input)`、複雜 pattern 對長輸入 | 禁止使用者提供 pattern；固定 pattern 加超時/`re2` |
| path traversal（Express） | `res.sendFile(user_path)`、`fs.readFile(path.join(public, name))` | `path.resolve` + 前綴檢查；`express.static` 只掛固定目錄 |
| 不安全 redirect | `res.redirect(req.query.next)`、`window.location = user_input` | 白名單網域；`open redirect` 也算 MEDIUM |
| SSRF（Node） | `axios.get(user_url)`、`fetch(user_input)`、`http.get` | 白名單 + 禁止內網 IP（見 vuln-categories） |
| React XSS | `dangerouslySetInnerHTML`、`<a href={user_input}>`（`javascript:` URL）、`eval` 於 useEffect | 預設 escaping 已安全；`dangerouslySetInnerHTML` 必經 DOMPurify；href 白名單 protocol |
| Next.js | `getServerSideProps` 直接使用 query 未驗證、`next/image` 的 `src` 為使用者可控 URL（SSRF）、API route 缺 auth、`middleware` 只檢查部分路徑 | API routes 各自驗證 auth；image `src` 白名單；middleware 覆蓋全部敏感路徑 |
| 依賴混淆 / supply chain | `package.json` 裝了相似名字套件、install script 有網路行為 | 鎖 `package-lock.json`；稽核 `npm audit`；檢查 `postinstall` |
| 記憶體 DoS | 上傳/body 無大小限制、`JSON.parse` 超大 body、graphql 深度攻擊 | body 大小限制（`express.json({limit})`）、查詢深度限制 |

## Python（Django / Flask / FastAPI）

| 模式 | 偵測訊號 | 安全寫法 |
|---|---|---|
| `eval`/`exec`/`pickle`/`yaml.load` | 使用者輸入進任何一種 | `yaml.safe_load`；JSON 取代 pickle；禁止 eval |
| SQLi | `cursor.execute(f"...{x}...")`、`.format()` 組 SQL、`raw()` 查詢接變數 | ORM/參數化：`WHERE id = %s` 或 `?`；`text()` + bind params |
| 不安全反序列化 | `pickle.loads(request.body)`、`joblib.load`、`torch.load`（舊版） | 只反序列化可信來源；`torch.load(weights_only=True)` |
| FastAPI/Pydantic 坑 | `response_model` 未設（回傳整個 ORM 物件洩漏欄位）、`**kwargs` 進 model（mass assignment）、path/query 參數型別太寬 | 顯式 `response_model` schema；`model_config = ConfigDict(extra="forbid")` |
| Django 坑 | `objects.raw()`、`.extra()`、`mark_safe`、`|safe` filter、`@csrf_exempt` 過度使用、`SECRET_KEY` 寫死 | ORM 查詢 + 參數化；`mark_safe` 僅用於已消毒內容；`SECRET_KEY` 走 env；`DEBUG=False` |
| Flask 坑 | `render_template_string(user_input)`（SSTI）、`session` 簽章 secret 寫死、`request.args` 直接進 SQL/HTML | 預編譯模板；secret 走 env；同上注入防護 |
| 路徑穿越 | `os.path.join(base, filename)` 未驗證、`send_file(user_path)`、`zipfile` 解壓 | `Path.resolve()` + `is_relative_to`；逐檔檢查 zip entry |
| 密碼學 | `hashlib.md5`/`sha1` 存密碼、自製 AES、`random` 用於 token | `bcrypt`/`argon2`；`secrets` 模組；`cryptography` 函式庫 |
| SSRF | `requests.get(user_url)`、`urllib.request.urlopen` | 白名單 + 內網 IP 阻擋 |
| 命令注入 | `os.system`、`subprocess` + `shell=True`、`os.popen` | list 形式 `subprocess.run([...])` |

## Java（Spring Boot / 傳統 Servlet）

| 模式 | 偵測訊號 | 安全寫法 |
|---|---|---|
| SQLi（JDBC） | `Statement` + 字串串接、`createQuery("..." + param)`（HQL/JPQL 串接） | `PreparedStatement`；Spring Data JPA 參數綁定 |
| 反序列化 | `ObjectInputStream.readObject()`、`XMLDecoder`、`jackson` 多型（`@JsonTypeInfo` 開 polymorphic + `defaultTyping`） | 白名單 `ObjectInputFilter`；Jackson 關閉 polymorphic 或白名單 class；`XMLDecoder` 禁用 |
| XXE | `DocumentBuilderFactory`/`SAXParserFactory` 未設 `disallow-doctype-decl`、`XMLInputFactory` 未關 | 統一設 `disallow-doctype-decl=true`、`external-general-entities=false` |
| Spring 坑 | `@RequestParam` 直進 SQL/命令、`SpEL` 注入（`@Value("#{...}")` 接使用者輸入、`StandardEvaluationContext`）、`@PathVariable` 進檔案路徑 | SpEL 用 `SimpleEvaluationContext`；路徑/查詢參數驗證 |
| 路徑穿越 | `Paths.get(base + user_input)`、`new File(user_path)`、`Resource` 載入未驗證 | 正規化 + 前綴檢查；`Path.normalize()` 後 `startsWith` |
| 不安全加密 | `DES`/`ECB`/`MD5`、`SecureRandom` 被 `Random` 取代 | AES-GCM + `SecureRandom`；`MessageDigest` SHA-256+ |
| Log Injection / Log4j | `log4j` < 2.17（CVE-2021-44228）、`logger.info(user_input)` | 升級 log4j 2.17+；`%m` 輸入過濾 |
| 缺少認證（Spring Security） | `permitAll()` 過寬、`@PreAuthorize` 缺失、filter 順序錯誤 | 預設拒絕 + 最小 `permitAll`；方法級安全 |

## Go

| 模式 | 偵測訊號 | 安全寫法 |
|---|---|---|
| SQLi | `fmt.Sprintf("SELECT ... %s", param)`、`db.Query("..." + x)` | `database/sql` 參數 `?`；`sqlx` named params |
| 命令注入 | `exec.Command("sh", "-c", ...)`、`exec.Command` + `fmt.Sprintf` 拼參數 | `exec.Command` 直接傳 list（不經 shell）；參數獨立 |
| 路徑穿越 | `filepath.Join(base, user_input)` 未驗證、`http.ServeFile` 接輸入 | `filepath.Clean` + 前綴檢查；`http.ServeFileFS` 綁目錄 |
| SSRF | `http.Get(user_url)`、`net/http` 直接 fetch 使用者 URL | 白名單 + 內網 IP 阻擋（`net.ParseIP` 檢查 private range） |
| 不安全的 `crypto/rand` 替代 | `math/rand` 用在 token/金鑰 | `crypto/rand`；`crypto/rand` 的 `Read` |
| 弱雜湊 | `crypto/md5`、`crypto/sha1` 存密碼、`bcrypt` 未用 | `golang.org/x/crypto/bcrypt` 或 argon2 |
| 整數溢位 / 記憶體 | 上傳大小計算、`int` 轉換未檢查、slice 越界由使用者控制 | 明確範圍檢查；`io.LimitReader` |
| 缺少 context 取消 | 長任務無 `context.Context`、無 timeout | 所有 IO 帶 context + timeout（防 hang/DoS） |
| 不安全的 `unsafe` | `unsafe.Pointer` 大量使用於資料邊界 | 避免；確認 memory 安全 |

## Ruby（Rails）

| 模式 | 偵測訊號 | 安全寫法 |
|---|---|---|
| Mass Assignment | `User.new(params)` / `update_attributes(params)`（Rails < 4 或關了 strong parameters） | `params.permit(:name)`；strong parameters 預設開啟 |
| SQLi | `where("name = '#{x}'")`、`find_by_sql` 串接、`User.where(params[:q])`（hash 注入） | `where("name = ?", x)`；bind variables |
| SSTI | `ERB.new(user_template)`、`render inline: user_input`、`Haml::Engine` | 預編譯模板；使用者輸入只能當變數 |
| 反序列化 | `Marshal.load`、`YAML.load`（舊版）、`Psych.load` | `YAML.safe_load`（白名單 classes）；JSON |
| 命令注入 | `system("ls #{x}")`、`\`cmd #{x}\``、`Open3` shell 形式 | `system(*args)` list 形式 |
| 不安全 redirect | `redirect_to params[:next]`、`redirect_back fallback_location: user_input` | 白名單網域；`redirect_to` 只接內部路徑 |
| 缺少 CSRF | `protect_from_forgery` 被關、`skip_before_action :verify_authenticity_token` 過度使用 | 預設開啟；API-only 用 token auth |
| 路徑穿越 | `File.join(Rails.root, "public", params[:file])`、`send_file` | `File.expand_path` + 前綴檢查 |
| 不安全的 session | `session[:user_id] = params[:id]`、cookie session 存敏感資料 | 伺服器端 session；只存 ID；`config.force_ssl` |

## Rust

| 模式 | 偵測訊號 | 安全寫法 |
|---|---|---|
| 不安全的 `unsafe` | `unsafe { ... }` 出現在輸入處理路徑、`std::mem::transmute`、手動 `from_raw_parts` | 最小化 unsafe；包裝成安全 API 並加註不變量 |
| 命令注入 | `Command::new("sh").arg("-c").arg(format!(...))` | `Command` list 形式（Rust 預設不經 shell，勿自行接 `sh -c`） |
| SQLi | `format!("SELECT ... {}", x)` 進 sqlx/rusqlite、`sqlx::query(&s)` | `sqlx::query("... ?")` bind；`rusqlite` 參數綁定 |
| 路徑穿越 | `PathBuf::from(base).join(user_input)` 未驗證、`File::create(user_path)` | `canonicalize`/`components()` 檢查 `ParentDir` |
| 不安全的反序列化 | `serde` 於不可信資料未驗證 schema、`bincode`/`rmp` 直接反序列化 | 先驗證 schema/長度；`serde_json` 白名單 struct |
| 弱隨機 | `rand::thread_rng` 用於 token/金鑰 | `getrandom`/`rand::rngs::OsRng`；`uuid` v4 |
| 弱雜湊 | `md5`/`sha1` crate 存密碼 | `argon2`/`bcrypt` crate |
| 整數溢位 | `+`/`*` 於長度/索引計算（debug 以外 build） | `checked_add`/`saturating_*`；`wrapping` 明確標注 |
| DoS（資源） | 讀取不可信輸入無 `take(n)`/`Read::take`、`Vec::with_capacity(user_n)` | 限制輸入大小與分配上限 |

## PHP

| 模式 | 偵測訊號 | 安全寫法 |
|---|---|---|
| SQLi | `mysqli_query("SELECT ... $_GET[id]")`、`$db->query("...".$x)` | PDO prepared statements |
| XSS | `echo $_GET['q']`、`<?= $user_input ?>` 未 escaping | `htmlspecialchars($x, ENT_QUOTES)` 輸出時 |
| 命令注入 | `exec("... $x")`、`system()`、`shell_exec`、反引號 | `escapeshellarg` 逐參數 + 白名單；`proc_open` list |
| 不安全的反序列化 | `unserialize($_POST['data'])`（magic methods 觸發 gadget chain） | JSON；白名單 allowed_classes |
| 路徑穿越 | `file_get_contents($base . $_GET['f'])`、`include $_GET['page']`（LFI） | 正規化 + 前綴檢查；include 白名單 |
| 弱雜湊 | `md5($pass)`、`sha1`、`crypt()` 預設 | `password_hash(PASSWORD_BCRYPT)`/`PASSWORD_ARGON2I` + `password_verify` |
| PHP 型別 juggling | `==` 比較 hash（`"0e123..." == "0e456..."` 為 true）、`strcmp` 回傳 0 | `hash_equals`、`===` |
| 上傳漏洞 | `move_uploaded_file` 用原始檔名、只檢查 `$_FILES['type']` | 重新命名 + 副檔名白名單 + `finfo` magic bytes |
| 弱亂數 | `rand()`/`mt_rand()` 用於 token | `random_bytes()`/`random_int()` |
| 過度寬鬆的 `file_put_contents`/`eval` | `eval($user_code)`、動態 include | 禁止；設計上避免 |

---

## 跨語言通用檢查（每種語言都跑）

- 依賴鎖檔比對 `vulnerable-packages.md` 與 OSV/GHSA（Step 2）。
- 使用者輸入 → 任何 sink 的資料流（Step 5）。
- 框架內建防護被關閉的訊號：`escape=false`、`@csrf_exempt`、`permitAll()`、
  `unsafe`、`shell=True`、`skip_before_action`。