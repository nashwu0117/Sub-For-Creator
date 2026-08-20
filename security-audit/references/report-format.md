# 報告模板（report-format.md）

Step 7 的輸出格式。**結構固定，三段式**：摘要表 → 依類別分組的發現 →
修補提案。所有報告都以此模板輸出（人類可讀版；同時可用 JSON 形式輸出
`findings.json` 供後續工具處理）。

---

## 0. 標頭

```markdown
# 資安審查報告 — <專案名稱>

- **日期**：<YYYY-MM-DD>
- **掃描範圍**：<repo 根目錄 / 指定路徑；含哪些檔案類型；排除哪些>
- **技術棧**：<偵測到的語言/框架/依賴生態系>
- **方法**：<8 步驟 workflow 摘要；用了哪些工具（npm audit / osv-scanner 等）>
- **結論**：<一句話總結>
```

## 1. 發現摘要表（依 Severity 計數）

**一律放在報告最前面。**

```markdown
## 發現摘要

| Severity | 數量 |
|---|---|
| 🔴 CRITICAL | N |
| 🟠 HIGH | N |
| 🟡 MEDIUM | N |
| 🔵 LOW | N |
| ⚪ INFO | N |
| **總計** | **N** |
```

乾淨專案：

```markdown
## 發現摘要

**未發現漏洞。** 掃描範圍：<範圍>。已檢查：依賴漏洞（N 個套件）、
secrets（N 個檔案）、五大類漏洞模式、跨檔案資料流。未檢查：<例如
「未啟動的 runtime 行為」>。
```

> 規則：**絕不硬湊發現**。真的乾淨就明確說「未發現漏洞」。

## 2. 逐項發現（依類別分組）

依「類別」分組（Injection / Auth & Access Control / Data Handling /
Cryptography / Business Logic / Secrets & Exposure / Dependencies），
**不是依檔案分組**。每個 finding 一張卡片：

```markdown
### <編號>.<類別> — <簡短標題>

- **Severity**：🔴 CRITICAL / 🟠 HIGH / 🟡 MEDIUM / 🔵 LOW / ⚪ INFO
- **信心度**：High / Medium / Low（CRITICAL/HIGH 必須註明已通過 Step 6 對抗式驗證）
- **位置**：`<檔案路徑>:<行號>`（多處時列出全部；跨檔案時標出入口點 → sink 路徑）
- **程式碼片段**：
  ```<語言>
  <有問題的程式碼，5-15 行>
  ```
- **攻擊者可以做什麼？**：<白話文描述實際影響，含攻擊步驟與前置條件>
  - 例：「攻擊者只要把 `id` 參數改成別人的訂單編號，就能下載不屬於他的
    字幕檔（IDOR）。不需要任何特殊權限。」
- **為什麼成立（對抗式驗證摘要）**：<Step 6 的反問與結論——為什麼沒被
  框架/上游擋掉>
- **證據**：<驗證過的路徑 / 測試輸出 / 工具報告 ID>
```

## 3. 修補提案（Propose Patches）

只對 **CRITICAL / HIGH** 提供 diff；MEDIUM/LOW/INFO 給書面建議。

```markdown
## 修補提案

> ⚠️ 以下修補**尚未套用**，僅供審查。套用前請人工確認每一項。

### Patch 1：<標題>（對應 Finding #<編號>，Severity）

**檔案**：`<路徑>`

**變更**：
```diff
- <有問題的程式碼>
+ <安全寫法>
```

**理由**：<為什麼這樣修；對應哪個 CVE/漏洞模式>

**驗證方式**：<如何確認修好：重跑測試、特定攻擊 payload 不再成功、CI 檢查>

**風險**：<行為改變、相容性影響、是否需要遷移>
```

## 4. 結尾

```markdown
## 掃描限制

- <未檢查的目錄/檔案（如 node_modules、vendor）>
- <無法靜態確認的 runtime 行為（如第三方服務設定）>
- <建議的後續動作：接 CI、用真實滲透測試補強、更新依賴的優先序>
```

---

## JSON 結構化輸出（選用）

供工具/CI 消費（Cloudflare 風格，多次執行可疊加覆蓋率）：

```json
{
  "schema_version": "1.0",
  "project": "<名稱>",
  "scanned_at": "<ISO8601>",
  "scope": ["<路徑>"],
  "summary": { "CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0 },
  "findings": [
    {
      "id": "SEC-001",
      "category": "Auth & Access Control",
      "severity": "HIGH",
      "confidence": "High",
      "title": "<標題>",
      "files": [{ "path": "src/x.py", "line": 42 }],
      "description": "<白話風險說明>",
      "adversarial_verified": true,
      "suggested_fix": "<書面建議或 diff 摘要>"
    }
  ]
}
```

## 輸出規則檢查清單

- [ ] 摘要表在最前（依 Severity 計數）
- [ ] 發現依類別分組，非依檔案
- [ ] 每個 finding 有：路徑、行號、程式碼片段、白話風險、信心度
- [ ] 每個 CRITICAL/HIGH 標注「已通過 Step 6 對抗式驗證」
- [ ] 修補只有提案，明確聲明「尚未套用，需人工確認」
- [ ] 乾淨專案明確寫「未發現漏洞」+ 掃描範圍
- [ ] 沒有自動修改任何檔案