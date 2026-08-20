# 多 GPU 橫向擴展部署手冊（Multi-GPU Horizontal Scaling Runbook）

本文件說明如何把 Sub-for-Creator 的 Celery worker 艦隊橫向擴展到多張 GPU、
多台主機，同時保持 v1 的單 GPU / CPU 預設路徑 100% 可用。

## 1. 佇列拓撲（Queue Topology）

v1 只有一個預設佇列。本版本新增兩個佇列，任務依類型分流：

| 佇列 | 預設名稱 | 任務 | 資源特性 |
|---|---|---|---|
| `transcribe` | `transcribe` | `app.worker.tasks.process_job_task`（ASR，重任務） | GPU 密集（WhisperX / faster-whisper） |
| `render` | `render` | `app.worker.render_tasks.render_job`（ffmpeg 燒錄） | CPU 密集（libx264 / libvpx），GPU 可選 |
| 預設佇列 | `celery` | 輕量任務（`cleanup_expired_jobs` 等 beat 排程） | 幾乎無負載 |

路由定義在 `backend/app/worker/celery_app.py` 的 `task_routes`：

```python
task_routes={
    "app.worker.tasks.process_job_task": {"queue": "transcribe"},
    "app.worker.render_tasks.render_job": {"queue": "render"},
    "app.worker.cleanup.cleanup_expired_jobs": {"queue": "celery"},
},
```

所有佇列共用 `worker_prefetch_multiplier=1` 與 `task_acks_late=True`（見 §7）。

### Worker 如何選擇佇列

Celery worker 用 `-Q` 指定要消費的佇列：

```bash
# 全部佇列（單 worker 部署，等同 v1 行為）
celery -A app.worker.celery_app worker -Q transcribe,render,celery

# 只做 GPU ASR
celery -A app.worker.celery_app worker -Q transcribe

# 只做燒錄渲染
celery -A app.worker.celery_app worker -Q render
```

> 佇列名稱可透過 `SFC_TRANSCRIBE_QUEUE` / `SFC_RENDER_QUEUE` /
> `SFC_DEFAULT_QUEUE` 覆寫；**改名稱後必須同步所有 worker 的 `-Q` 參數**。

## 2. 前置需求（Prerequisites）

每台要跑 GPU worker 的主機都需要：

1. **NVIDIA 驅動**：`nvidia-smi` 在宿主機上正常輸出。
2. **NVIDIA Container Toolkit**（`nvidia-container-toolkit`）：

   ```bash
   # Ubuntu / Debian
   sudo apt-get install -y nvidia-container-toolkit
   sudo nvidia-container-toolkit runtime update
   sudo systemctl restart docker
   ```

   驗證容器內看得到 GPU：

   ```bash
   docker run --rm --gpus all nvidia/cuda:12.0-runtime-ubuntu22.04 nvidia-smi
   ```

3. **GPU 映像檔**：用 `INSTALL_GPU=1` build-arg 重建共享映像（安裝
   `requirements-gpu.txt`，含 whisperx + torch，約 3GB+）：

   ```bash
   docker compose build --build-arg INSTALL_GPU=1 api
   # 或直接 build 並打 tag
   docker build --build-arg INSTALL_GPU=1 -t sfc-backend:gpu backend/
   ```

   > 若需要完整 CUDA 執行庫（cuBLAS/cuDNN），建議改以
   > `nvidia/cuda:12.x-runtime-ubuntu22.04` 為基礎映像（見 `backend/Dockerfile`
   > 頭部註解）。

## 3. GPU 親和性（GPU Affinity）

### `SFC_GPU_INDEX` → `CUDA_VISIBLE_DEVICES`

每個 worker 進程在啟動時讀取 `SFC_GPU_INDEX`（0-based），並在 import
`celery_app` 時設定 `CUDA_VISIBLE_DEVICES`，把該進程釘到指定 GPU：

```bash
SFC_GPU_INDEX=0 celery -A app.worker.celery_app worker -Q transcribe
# 等價於 CUDA_VISIBLE_DEVICES=0 celery ...
```

- 未設定 / 留空 → 不釘選，`CUDA_VISIBLE_DEVICES` 保持原樣（單 GPU 主機行為不變）。
- 負數 → 忽略並警告。
- 因為 ASR 後端是在 `transcribe()` 內才 lazy import torch，import 時期設定
  env 是安全的。

### 主機名綁定佇列（Hostname-based Queue Binding）

多節點部署時，用「每台主機只消費特定佇列」的方式把工作釘到本機 GPU：

| 節點 | 角色 | 命令 |
|---|---|---|
| `gpu-node-0` | GPU 0 | `celery ... worker -Q transcribe` + `SFC_GPU_INDEX=0` |
| `gpu-node-1` | GPU 1 | `celery ... worker -Q transcribe` + `SFC_GPU_INDEX=0`（本機第一張卡） |
| `render-node` | 純 CPU 渲染 | `celery ... worker -Q render` |

每台主機的 worker 都連到同一個 Redis broker（`SFC_CELERY_BROKER_URL`），
broker 負責把任務派給有消費該佇列的 worker。

### 每張 GPU 建議並發數

int8 量化的 large-v3 約佔 8GB VRAM，一張 24GB 的 GPU 可安全共駐 **2 個
worker**（`--concurrency=1` × 2 個進程）；float16 的 large-v3 約 12-16GB，
建議 **1 個 worker / GPU**。多 worker 共用一張卡時，把每個 worker 的
`SFC_GPU_INDEX` 設成相同值即可（見 §4 的 `--scale` 範例）。

## 4. 啟動 N 個 Worker（單機多 GPU / 多節點）

### 單機單 GPU（預設，不變）

```bash
docker compose up -d --build
```

`worker` 服務消費全部佇列（`-Q transcribe,render,celery`），行為與 v1 相同。

### 單機多 GPU（docker compose）

取消 `docker-compose.yml` 中 `worker-gpu` 服務塊的註解，然後：

```bash
# 2 個 worker 共用 GPU 0（int8 large-v3 約 8GB，可共駐）
docker compose up -d --scale worker-gpu=2
```

> `--scale` 的所有副本共享同一份 `environment`（`SFC_GPU_INDEX=0`），所以
> 這是「多 worker 共用一張 GPU」的示範。要分散到多張 GPU，為每張卡建一個
> override 檔：

```yaml
# docker-compose.gpu1.yml
services:
  worker-gpu:
    environment:
      SFC_GPU_INDEX: 1
```

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu1.yml up -d worker-gpu
```

### 獨立渲染 worker

取消 `render-worker` 服務塊註解（需先套用 §9 的 api/export.py wiring diff）：

```bash
docker compose up -d --scale render-worker=2
```

### 多節點

每台節點各自 `docker compose up -d`（或跑裸 `celery` 進程），共用同一個
Redis broker 與共享儲存（見 §8）：

```bash
# 節點 A（GPU 0）
SFC_GPU_INDEX=0 celery -A app.worker.celery_app worker -Q transcribe --concurrency=1
# 節點 B（GPU 1）
SFC_GPU_INDEX=0 celery -A app.worker.celery_app worker -Q transcribe --concurrency=1
# 節點 C（渲染）
celery -A app.worker.celery_app worker -Q render --concurrency=2
```

## 5. 驗證 GPU 使用率

```bash
# 宿主機：即時看每張卡的利用率 / 記憶體
watch -n 1 nvidia-smi

# 容器內：確認 CUDA_VISIBLE_DEVICES 生效
docker exec -it <worker-container> nvidia-smi

# 確認 worker 進程真的在用 GPU（看 PID 對應的 process）
nvidia-smi --query-compute-apps=pid,used_memory --format=csv

# 確認 worker 已連上 broker 並消費正確佇列
docker exec -it <worker-container> celery -A app.worker.celery_app inspect active
docker exec -it <worker-container> celery -A app.worker.celery_app inspect registered
```

## 6. 佇列監控

```bash
# 各佇列的待處理數量（Redis）
redis-cli LLEN transcribe
redis-cli LLEN render
redis-cli LLEN celery

# 正在處理的任務
celery -A app.worker.celery_app inspect active

# 已註冊的任務（確認 render_job / process_job_task 都在）
celery -A app.worker.celery_app inspect registered
```

## 7. 擴縮容不丟任務（Celery 語意）

`task_acks_late=True` + `worker_prefetch_multiplier=1` 的組合保證：

- worker 先執行任務、成功後才 ack；**執行中 crash 不會丟任務**。
- 每個 worker 進程一次只預取 1 個任務，任務不會被囤在 worker 記憶體裡。
- crash 的任務會在 **visibility timeout**（預設 1 小時，可設
  `broker_transport_options={"visibility_timeout": ...}`）後被 Redis 重新投遞。

因此：

- **縮容**（`docker compose stop worker-gpu` / `docker compose up -d --scale
  worker-gpu=1`）：正在跑的任務會被其他 worker 在 visibility timeout 後接手；
  佇列中的任務原封不動留在 Redis。
- **優雅關機**：先送 `SIGTERM`（`docker compose stop` 就是），Celery 會
  warm shutdown——完成手上任務、不再取新任務，然後才退出。避免直接
  `docker compose kill`（SIGKILL）造成任務等 visibility timeout。
- **不要**在縮容時清空 Redis（`FLUSHALL`）——佇列就是任務的持久化儲存。

## 8. 跨主機儲存（S3 遷移）

worker 分散到多台主機後，**本機磁碟儲存（`SFC_STORAGE_BACKEND=local`）不再
可行**——節點 A 上傳的檔案節點 B 看不到。改用 S3 / R2 相容物件儲存：

```bash
SFC_STORAGE_BACKEND=s3
SFC_S3_ENDPOINT_URL=https://<account_id>.r2.cloudflarestorage.com
SFC_S3_BUCKET=sfc-uploads
SFC_S3_ACCESS_KEY=...
SFC_S3_SECRET_KEY=...
```

所有節點（api + 全部 worker）必須設定**相同**的 S3 設定。S3 後端會把物件
下載到本機快取（`<upload_dir>/.cache`）供 ffmpeg / FileResponse 讀取，寫入
後再上傳，跨主機透明。

> 不想用 S3 的話，替代方案是讓所有節點掛載同一個共享磁碟（NFS / EFS），
> 並把 `SFC_UPLOAD_DIR` 指向共享路徑。SQLite 不適合多節點同時寫入——多節點
> 部署請改用 PostgreSQL（見 `docker-compose.yml` 頭部說明）。

## 9. 常見失敗模式

| 症狀 | 原因 | 處理 |
|---|---|---|
| `CUDA out of memory` | 單張卡塞太多 worker / 模型太大 | 降低該 GPU 上的 worker 數；改用 int8（`compute_type=int8`）；換大卡 |
| 兩個 worker 共用一張卡時啟動即 crash | CUDA init race：同時載入模型搶 VRAM | 錯開啟動（`restart` 會自動重試）；或先跑一個、確認載入完成再起第二個；或 `--concurrency=1` 單進程 |
| `nvidia-smi` 在容器內看不到 GPU | 沒裝 Container Toolkit / 沒設 `deploy.resources` | 見 §2；確認 compose 的 nvidia reservation 已取消註解 |
| worker 一直重啟 | 映像沒用 `INSTALL_GPU=1` 重建，whisperx import 失敗 | `docker compose build --build-arg INSTALL_GPU=1 api` |
| 任務卡在 `queued` 不執行 | worker 沒消費對應佇列（`-Q` 漏了） | `celery inspect active` / `redis-cli LLEN <queue>` 確認 |
| 渲染狀態一直 `rendering` | 渲染任務在 worker 進程失敗，API 看不到 | 套用 §9 的 `render_status` diff 後會顯示 `failed` + 錯誤訊息 |
| 節點 B 找不到節點 A 的檔案 | 儲存沒共享 | 見 §8，改用 S3 或共享磁碟 |

## 10. 啟用渲染離線化（Render Offload）的 Wiring Notes

`render_tasks.py` 已就緒，但 `backend/app/api/export.py` 仍用執行緒跑渲染。
套用以下最小 diff 後，渲染會改走 `render` 佇列（API 進程不再被 ffmpeg 佔用）：

### 10.1 `start_render()`：改用 Celery 派發（保留 broker 掛掉時的執行緒 fallback）

```python
def start_render(job: Job, fmt: str, settings: Settings, params: dict) -> str:
    key = render_key(job.id, RENDER_FORMATS[fmt][0])
    if get_storage().exists(key):
        _set_render_state(job.id, fmt, "ready")
        return "ready"
    state = _get_render_state(job.id, fmt)
    if state and state["status"] == "rendering":
        return "rendering"
    _set_render_state(job.id, fmt, "rendering")
    # NEW: clear any stale cross-process failure marker from a previous attempt
    err_key = render_key(job.id, f"{RENDER_FORMATS[fmt][0]}.error")
    get_storage().save(b"", err_key)
    from app.worker.render_tasks import render_task  # lazy import

    try:
        render_task.delay(job.id, fmt, params)
    except Exception:
        # broker unreachable — fall back to the in-process thread so renders
        # keep working without Redis (mirrors the inline-queue fallback)
        thread = threading.Thread(
            target=_render_worker,
            args=(job.id, fmt, settings, params),
            name=f"sfc-render-{job.id}-{fmt}",
            daemon=True,
        )
        thread.start()
    return "rendering"
```

### 10.2 `render_status()`：跨進程終態優先（worker 寫檔 / 寫錯誤 marker）

```python
def render_status(job_id: str, fmt: str, settings: Settings) -> tuple[str, str | None]:
    # NEW: the render task runs in a Celery worker process, so terminal states
    # derived from storage take precedence over the local in-memory hint.
    if get_storage().exists(render_key(job_id, RENDER_FORMATS[fmt][0])):
        _set_render_state(job_id, fmt, "ready")
        return "ready", None
    err_key = render_key(job_id, f"{RENDER_FORMATS[fmt][0]}.error")
    if get_storage().exists(err_key):
        try:
            with open(get_storage().open_path(err_key), encoding="utf-8") as fh:
                error = fh.read()
        except OSError:
            error = ""
        if error:
            _set_render_state(job_id, fmt, "failed")
            return "failed", error
    state = _get_render_state(job_id, fmt)
    if state and state["status"] == "rendering":
        if time.time() - state["started"] > settings.render_timeout_seconds + 120:
            _set_render_state(job_id, fmt, "idle")
        else:
            return "rendering", None
    if state and state["status"] == "failed":
        return "failed", state.get("error")
    return "idle", None
```

> 不套用 10.2 也能運作：成功渲染會因檔案存在而回 `ready`；失敗則在
> `render_timeout_seconds + 120` 後回 `idle`（可重試）。套用後失敗會即時
> 顯示 `failed` 與錯誤訊息。

### 10.3 新增環境變數

| 變數 | 預設 | 說明 |
|---|---|---|
| `SFC_GPU_INDEX` | 空 | 0-based GPU 索引；設定後 worker 以 `CUDA_VISIBLE_DEVICES` 釘選 |
| `SFC_TRANSCRIBE_QUEUE` | `transcribe` | ASR 佇列名（改動需同步 `-Q`） |
| `SFC_RENDER_QUEUE` | `render` | 渲染佇列名（改動需同步 `-Q`） |
| `SFC_DEFAULT_QUEUE` | `celery` | 預設佇列名（改動需同步 `-Q`） |

### 10.4 Compose 操作

1. 套用 10.1 / 10.2 的 diff。
2. 取消 `docker-compose.yml` 中 `render-worker` 服務塊註解。
3. `docker compose up -d --scale render-worker=2`（或直接 `up -d` 起單個）。

### 10.5 `main.py`

**無需修改**。API 進程不 import `render_tasks`（`start_render` 內 lazy
import），GPU 釘選只影響設了 `SFC_GPU_INDEX` 的 worker 容器。