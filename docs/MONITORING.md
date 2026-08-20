# Sub for Creator — Production Monitoring

Prometheus + Grafana monitoring for the Sub for Creator stack: queue depth, job
counts by status, storage usage, GPU utilization/memory, active ASR backend,
worker concurrency, job durations, and daily cost estimation.

Covers spec §8 (監控：GPU 使用率、儲存空間用量、每日成本追蹤).

---

## 1. Quick start

```bash
# from the repo root
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d
```

This starts the normal stack plus two extra services:

| Service    | Port | Purpose                                        |
|------------|------|------------------------------------------------|
| prometheus | 9090 | Scrapes `http://api:8000/api/metrics` every 15s |
| grafana    | 3000 | Dashboards (auto-provisioned)                  |

- Grafana login: `admin` / `admin` (override with `GRAFANA_ADMIN_USER` /
  `GRAFANA_ADMIN_PASSWORD` in `.env`).
- Open **http://localhost:3000** → the dashboard **"Sub for Creator — Overview"**
  is already loaded (folder *Sub for Creator*).
- Prometheus UI: **http://localhost:9090** (query `sfc_queue_depth`, etc.).

To stop the monitoring stack only:

```bash
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml stop prometheus grafana
```

### Local development (no Docker)

```bash
cd backend
uvicorn app.main:app --reload --port 8000   # API
# in another terminal:
prometheus --config.file=../monitoring/prometheus.yml
```

The dev endpoint is `http://localhost:8000/api/metrics` (the router is mounted
under `/api`). Through the nginx frontend it is `http://localhost:8080/api/metrics`.

---

## 2. Metric catalog

All metrics are exposed by `GET /api/metrics` on the FastAPI API in Prometheus
text format (`prometheus-client`). The endpoint is **unauthenticated** so
Prometheus can scrape it — see [Securing the endpoint](#securing-the-endpoint).

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `sfc_jobs_total` | gauge | `status` | Number of jobs per status (`queued`, `processing`, `done`, `failed`, `expired`). |
| `sfc_queue_depth` | gauge | — | Jobs currently queued **or** processing. Same definition as the API's queue-capacity check (`SFC_MAX_QUEUE`). |
| `sfc_workers_concurrency` | gauge | — | Jobs currently being processed (`status=processing`). Should track worker `--concurrency`. |
| `sfc_storage_bytes` | gauge | — | Total bytes stored (local disk walk or S3 `list_objects_v2`). Cached 10 s. |
| `sfc_storage_objects` | gauge | — | Total stored objects/files. Cached 10 s. |
| `sfc_gpu_utilization_percent` | gauge | `gpu` | GPU utilization % per device (`nvidia-smi`). Cached 5 s. |
| `sfc_gpu_memory_used_bytes` | gauge | `gpu` | GPU memory used in bytes per device. |
| `sfc_gpu_memory_total_bytes` | gauge | `gpu` | GPU memory total in bytes per device. |
| `sfc_gpu_present` | gauge | — | `1` when `nvidia-smi` reported at least one GPU, `0` otherwise. |
| `sfc_asr_backend` | gauge | `backend` | Info-style gauge: `1` on the active backend (`whisperx` / `faster-whisper` / `mock`), `0` elsewhere. |
| `sfc_job_duration_seconds` | histogram | — | Wall-clock duration of completed jobs (`completed_at - created_at`). Buckets 1 s … 16 h. |

### Notes

- **GPU metrics** are read via `nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total
  --format=csv,noheader,nounits` (zero extra dependencies). When `nvidia-smi` is
  absent (CPU-only container, no driver), the scrape still succeeds: a comment
  line is emitted, `sfc_gpu_present` is `0`, and the per-device gauges are `0`.
  Do **not** alert on `sfc_gpu_utilization_percent == 0` alone — check
  `sfc_gpu_present` first.
- **Storage** is measured with `os.walk` for the local backend and paginated
  `list_objects_v2` for S3. Both are cached for 10 s so scrape storms do not
  hammer the filesystem or object store.
- **Job duration** is a cumulative histogram; the API observes only jobs that
  completed since the previous scrape (cursor-based), so `rate()` /
  `increase()` over it are meaningful. After an API restart the cursor resets
  and a few recent jobs may be re-observed (minor double-count, acceptable for
  cost estimation).
- **Scrape resilience**: every probe is wrapped in `try/except`. If Redis, the
  database, storage or the GPU driver is temporarily unavailable, the endpoint
  still returns valid Prometheus text with the metrics that *are* available.

---

## 3. Reading the Grafana dashboard

The provisioned dashboard **"Sub for Creator — Overview"** (`sfc-overview.json`)
contains:

| Panel | What to look for |
|---|---|
| Queue depth | Spikes above `SFC_MAX_QUEUE` mean uploads are being rejected with `429`. |
| Jobs by status | Stacked area; a growing `queued` band with a flat `processing` band = workers are the bottleneck. |
| Active ASR backend | Which engine is serving jobs (`whisperx` = GPU, `faster-whisper` = CPU, `mock` = test). |
| GPU utilization per device | Sustained 100% = GPU-bound (good); low util with a deep queue = add workers or check CPU/IO. |
| GPU memory per device | `used` approaching `total` = OOM risk for WhisperX large-v3. |
| Storage usage / objects | Growth rate vs. the 48 h TTL cleanup; a flat line after cleanup is expected. |
| Job duration p50/p95 | Latency per job; p95 >> p50 means long-tail jobs (long videos, 4K renders). |
| Estimated GPU cost over time | `sum(increase(sfc_job_duration_seconds_sum[$__range])) / 3600 × $/hr`. |
| Estimated GPU cost (all time) | Cumulative GPU cost since the API started observing. |
| Estimated storage cost / month | `sfc_storage_bytes / 2^30 × $/GB-month`. |
| GPU-hours (all time) | `sum(sfc_job_duration_seconds_sum) / 3600`. |

The two cost variables are editable from the dashboard dropdown:

- **`gpu_hourly_rate`** — default `0.34` (RunPod RTX 4090). Set it to your
  provider's price (see below).
- **`storage_gb_monthly_rate`** — default `0.02` ($/GB-month).

---

## 4. Cost estimation

### GPU cost

GPU-hours are approximated by the wall-clock duration of completed jobs. This
assumes the worker holds the GPU for the whole job (true for WhisperX: the
model stays resident and transcription is the dominant phase).

```
GPU-hours = sum(sfc_job_duration_seconds_sum) / 3600
GPU cost  = GPU-hours × $/hr
```

In PromQL (dashboard panels):

```promql
# cost over the selected time range
sum(increase(sfc_job_duration_seconds_sum[$__range])) / 3600 * $gpu_hourly_rate

# cumulative cost
sum(sfc_job_duration_seconds_sum) / 3600 * $gpu_hourly_rate
```

### Storage cost

```
storage cost / month = sfc_storage_bytes / (1024^3) × $/GB-month
```

### Worked examples

**RunPod RTX 4090** (≈ $0.34/hr, 24 GB VRAM):

- 50 jobs × 6 min average = 300 min = 5 GPU-hours → **$1.70**
- 200 jobs × 6 min = 20 GPU-hours → **$6.80**

**RunPod RTX 3090** (≈ $0.22/hr, 24 GB VRAM):

- 50 jobs × 8 min average = 400 min ≈ 6.7 GPU-hours → **$1.47**
- 200 jobs × 8 min ≈ 26.7 GPU-hours → **$5.87**

**Vast.ai** (prices vary by region/GPU; typically $0.10–$0.60/hr for
consumer GPUs, e.g. RTX 3090 ≈ $0.15–0.25/hr):

- 100 jobs × 5 min ≈ 8.3 GPU-hours × $0.20 → **$1.67**

**Storage** (S3/R2, $0.015–0.023/GB-month):

- 50 GB of uploads + renders ≈ 50 × $0.02 → **$1.00/month**

> These are *estimates*. Actual billing depends on provider, GPU model, model
> size (`large-v3` is ~3× slower than `small`), video length, and whether the
> instance is billed per-second or per-hour. For per-hour billing, round up
> each job to the next hour boundary.

---

## 5. Alerting

Prometheus alert rules (drop into `monitoring/prometheus.yml` under
`rule_files:` or a separate `alerts.yml`):

```yaml
groups:
  - name: sfc
    rules:
      # Queue too deep: uploads are being rejected with 429.
      - alert: SFCQueueTooDeep
        expr: sfc_queue_depth > 20
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Queue depth {{ $value }} for 5m"
          description: "Uploads may be rejected (SFC_MAX_QUEUE). Consider scaling workers."

      # GPU OOM risk: memory used within 90% of total.
      - alert: SFCGpuMemoryPressure
        expr: sfc_gpu_memory_used_bytes / sfc_gpu_memory_total_bytes > 0.9
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "GPU {{ $labels.gpu }} memory at {{ $value | humanizePercentage }}"
          description: "WhisperX large-v3 may OOM. Check model size / batch settings."

      # Storage growing faster than the 48h TTL cleanup can reclaim.
      - alert: SFCStorageGrowth
        expr: delta(sfc_storage_bytes[6h]) > 10 * 1024 * 1024 * 1024
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Storage grew >10 GiB in 6h"
          description: "Check TTL cleanup (celery beat) and upload volume."

      # API unreachable: Prometheus cannot scrape the metrics endpoint.
      - alert: SFCApiDown
        expr: up{job="sfc-api"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "API /api/metrics unreachable"
          description: "Prometheus cannot scrape the API. Check the api container."

      # GPU disappeared (driver removed / container restarted without GPU).
      - alert: SFCGpuLost
        expr: sfc_gpu_present == 0
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "No GPU detected"
          description: "nvidia-smi failed for 10m. Check the NVIDIA driver / container runtime."
```

To enable, add to `monitoring/prometheus.yml`:

```yaml
rule_files:
  - /etc/prometheus/alerts.yml
```

and mount the file in `docker-compose.monitoring.yml` (e.g.
`./monitoring/alerts.yml:/etc/prometheus/alerts.yml:ro`). Wire notifications
(Alertmanager, Slack, email) separately — out of scope here.

---

## 6. Securing the endpoint

`/api/metrics` is intentionally unauthenticated so Prometheus can scrape it.
If the API is publicly reachable:

- **Do not** expose it through the nginx frontend: add a `location` block that
  returns 403 for `/api/metrics`, or
- firewall the port at the host/cloud level so only the Prometheus host can
  reach `:8000`, or
- run Prometheus on the same private network and block `:8000` from the
  internet (recommended for the compose deployment).

The endpoint can be hard-disabled with `SFC_METRICS_ENABLED=false` (returns
404).

---

## 7. Wiring notes (MANDATORY)

Changes required to enable this feature in a fresh checkout:

1. **Router registration** — in `backend/app/main.py`, add to the imports:

   ```python
   from app.api import metrics as metrics_router
   ```

   and add `metrics_router.router` to the router tuple in `create_app()`:

   ```python
   for router in (
       health_router.router,
       config_router.router,
       jobs_router.router,
       uploads_router.router,
       subtitles_router.router,
       media_router.router,
       export_router.router,
       fonts_router.router,
       metrics_router.router,   # <-- add this line
   ):
       app.include_router(router, prefix="/api")
   ```

   The endpoint then lives at `/api/metrics` (dev: `http://localhost:8000/api/metrics`,
   nginx: `http://localhost:8080/api/metrics`, compose: `http://api:8000/api/metrics`).

2. **Dependency** — add to `backend/requirements.txt` (and it flows into
   `requirements-gpu.txt` via `-r requirements.txt`):

   ```
   prometheus-client>=0.20
   ```

   Pure-Python, no native deps. This is the **only** new dependency.

3. **Env vars** — optional, all have defaults:

   | Variable | Default | Meaning |
   |---|---|---|
   | `SFC_METRICS_ENABLED` | `true` | Set `false` to hard-disable `/api/metrics` (404). |
   | `GRAFANA_ADMIN_USER` | `admin` | Grafana login (compose override only). |
   | `GRAFANA_ADMIN_PASSWORD` | `admin` | Grafana password (compose override only). |

4. **Ports to publish** (compose override):

   | Service | Port |
   |---|---|
   | prometheus | `9090` |
   | grafana | `3000` |

5. **Files added** (all new, nothing existing modified except
   `backend/app/config.py` for the `metrics_enabled` setting):

   ```
   backend/app/api/metrics.py
   backend/tests/test_metrics.py
   monitoring/prometheus.yml
   monitoring/grafana/provisioning/datasources/prometheus.yml
   monitoring/grafana/provisioning/dashboards/dashboards.yml
   monitoring/grafana/dashboards/sfc-overview.json
   docker-compose.monitoring.yml
   docs/MONITORING.md
   ```

6. **Run** — `docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d`.