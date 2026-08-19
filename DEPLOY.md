# 部署指南（Deployment Guide）

這個專案是「前端 + 後端 API + Celery worker + Redis」的完整 Web 應用，依照你的需求選擇部署方式：

| 情境 | 推薦方式 | 花費 | 完整功能 |
|---|---|---|---|
| 快速試用、自己/朋友小範圍 | GitHub Codespaces | 免費（120 core-hr/月） | ✅ |
| 公開服務、固定網址 | VPS + Docker Compose | ~$5/月 | ✅ |
| 不想管伺服器 | PaaS（Render / Fly.io） | 免費額度起 | ✅ |
| 只在自己電腦 | Docker Compose 本機 | 免費 | ✅ |
| 純前端展示（無後端功能） | GitHub Pages | 免費 | ❌ 不建議 |

> ⚠️ **GitHub Pages 跑不起來**：Pages 只能託管靜態檔案，無法執行 FastAPI、Redis、WhisperX 模型。它只能用來展示前端畫面，上傳/辨識/匯出全部無法運作。

---

## 方式一：GitHub Codespaces（免費、零安裝）

任何人只要有 GitHub 帳號，30 秒開啟完整環境：

1. 開啟 repo：`https://github.com/<owner>/Sub-For-Creator`
2. 點綠色 **Code** → **Codespaces** 分頁 → **Create codespace on main**
3. 等待自動 build（首次 2-4 分鐘，之後秒開）
4. 瀏覽器自動開啟 `http://localhost:8080` → 直接使用

環境已透過 `.devcontainer/devcontainer.json` 設定：自動 `docker compose up -d --build` 啟動全部 5 個服務（web / api / worker / beat / redis）。

---

## 方式二：VPS + Docker Compose（公開服務標準解）

### 1. 準備一台 VPS

任選一家（DigitalOcean、Vultr、Hetzner、阿里雲、GCP…）：

- 最低規格：**2 vCPU / 4GB RAM / 40GB SSD**（CPU 跑 faster-whisper small 模型夠用）
- 作業系統：**Ubuntu 22.04+**
- 開通 **80 / 443** 埠（HTTP/HTTPS），SSH 預設 22

### 2. 安裝 Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# 重新登入 SSH 後生效
```

### 3. 部署

```bash
git clone https://github.com/<owner>/Sub-For-Creator.git
cd Sub-For-Creator
cp .env.example .env
docker compose up -d --build
```

完成後 `http://<你的IP>:8080` 即可使用。

### 4. 綁定域名 + HTTPS（Caddy 最簡單）

```bash
sudo apt install -y caddy
sudo tee /etc/caddy/Caddyfile > /dev/null <<'EOF'
sub.yourdomain.com {
    reverse_proxy localhost:8080
}
EOF
sudo systemctl restart caddy
```

自動取得 HTTPS 憑證。DNS 記得把 `sub.yourdomain.com` 指向 VPS IP。

### 5. 常用維護指令

```bash
docker compose ps          # 看服務狀態
docker compose logs -f api # 跟隨 API 日誌
docker compose logs -f worker
docker compose pull && docker compose up -d   # 更新
docker compose down        # 停止（保留資料）
```

### 6. 效能與規模調整（`.env`）

| 變數 | 預設 | 說明 |
|---|---|---|
| `SFC_ASR_BACKEND` | `faster-whisper`（compose 已設） | CPU 用 faster-whisper；GPU 用 whisperx |
| `SFC_WHISPER_MODEL` | `small` | CPU 建議 small；GPU 可 `large-v3` 品質更好 |
| `SFC_MAX_UPLOAD_MB` | 1024 | 單檔大小上限 |
| `SFC_TTL_HOURS` | 48 | 檔案保留時數 |

**GPU 加速**：裝 NVIDIA Container Toolkit → `docker compose build --build-arg INSTALL_GPU=1 api` → 取消 `docker-compose.yml` 中 worker 的 `deploy` 區塊註解。

---

## 方式三：PaaS（Render / Fly.io）

不想自己管伺服器的選擇：

- **Render**：Web Service（api + web）+ Background Worker（celery）+ Redis 外掛
- **Fly.io**：`fly launch` 產生設定，Dockerfile 已內建

兩者都有免費額度，但 Redis 通常需付費（~$15/月）或使用免費的外部 Redis（如 Redis Cloud 免費方案）。設定上需要：

1. 把 `docker-compose.yml` 的 5 個服務拆成獨立部署單元
2. 使用託管 Redis URL（`SFC_CELERY_BROKER_URL` / `SFC_RESULT_BACKEND`）
3. 持久化磁碟掛到 `/data`

---

## 方式四：GitHub Actions 自動部署（push 即上線）

repo 內附 `.github/workflows/deploy.yml` 範例：每次 push 到 `main` 時自動 SSH 到 VPS 更新部署。

### 設定 secrets（repo → Settings → Secrets and variables → Actions）

| Secret | 內容 |
|---|---|
| `VPS_HOST` | VPS IP 或域名 |
| `VPS_USER` | SSH 使用者（如 `root` 或 `ubuntu`） |
| `VPS_SSH_KEY` | 部署用 SSH 私鑰（`ssh-keygen -t ed25519` 產生，公鑰加入 VPS 的 `~/.ssh/authorized_keys`） |

### 運作流程

1. push 到 `main`
2. Actions 執行 `Deploy` workflow
3. SSH 到 VPS → `git pull` → `docker compose up -d --build`
4. 服務自動更新

### 想手動觸發？

Actions 頁面 → Deploy workflow → **Run workflow** 按鈕。

---

## 常見問題

**Q: 第一次上傳後一直停在 queued？**
A: 看 worker 日誌：`docker compose logs -f worker`。通常是模型下載中（faster-whisper small 約 460MB，第一次需幾分鐘）。

**Q: 中文顯示方塊？**
A: 確認鏡像含字型：`docker compose exec worker fc-list | grep -i cjk`。Dockerfile 已安裝 `fonts-noto-cjk`；重新 build 即可。

**Q: 記憶體不足？**
A: 關閉 VAD 或改用更小模型：`.env` 設 `SFC_WHISPER_MODEL=tiny`。

**Q: 資料備份？**
A: 所有資料在 `sfc-data` volume（uploads + SQLite）：`docker run --rm -v sfc-data:/data -v $(pwd):/backup alpine tar czf /backup/sfc-backup.tar.gz /data`

---

## 目錄對照

- `.github/workflows/ci.yml` — 每次 push 自動跑測試/build（pytest、ruff、前端 build、Docker build）
- `.github/workflows/deploy.yml` — VPS 自動部署（需設定 secrets）
- `.devcontainer/devcontainer.json` — Codespaces 一鍵啟動
- `docker-compose.yml` — 5 服務定義（web/api/worker/beat/redis）