# ============================================================
# Sub-For-Creator 后端镜像（FastAPI + Celery 共用同一镜像）
#
# 默认 CPU 构建：安装 requirements.txt（faster-whisper，不含 torch），
# 体积小、构建快（约 1 分钟）。
#
# —— GPU 构建说明（WhisperX 需要 torch + CUDA，仅供 GPU 宿主机）——
#   1. 宿主机需安装 NVIDIA Container Toolkit（nvidia-container-toolkit），
#      并配置 docker 使用 nvidia 容器运行时。
#   2. 构建时传参 INSTALL_GPU=1：
#        docker build --build-arg INSTALL_GPU=1 -t sfc-backend:gpu backend/
#      或配合 compose：docker compose build --build-arg INSTALL_GPU=1 api
#      （api 与 worker 共享镜像，会一起重建；api 不受影响，只是镜像变大）
#   3. INSTALL_GPU=1 会安装 requirements-gpu.txt（whisperx + torch，
#      镜像体积约 3GB+）。
#   4. 运行容器需挂载 GPU：docker run --gpus all ...
#      或取消 docker-compose.yml 中 worker 的 deploy.resources 注释。
#   5. 若需要完整 CUDA 运行库（cuBLAS/cuDNN，官方基础镜像不含），
#      建议改以 nvidia/cuda:12.x-runtime-ubuntu22.04 或
#      pytorch/pytorch:2.x-cuda 为基础镜像（自带 CUDA 运行时）。
#      本 Dockerfile 的 apt/COPY 步骤在这些镜像上同样适用。
# ============================================================
FROM python:3.11-slim

# 安装 ffmpeg（音频提取 / ASR 预处理必需）
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先复制依赖清单，充分利用 Docker 构建缓存
COPY requirements.txt requirements-gpu.txt ./

# 按构建参数选择依赖：默认 CPU（faster-whisper）；INSTALL_GPU=1 时安装
# requirements-gpu.txt（whisperx + torch，需要 CUDA 运行时，见文件头注释）
ARG INSTALL_GPU=0
RUN if [ "$INSTALL_GPU" = "1" ]; then \
        pip install --no-cache-dir -r requirements-gpu.txt; \
    else \
        pip install --no-cache-dir -r requirements.txt; \
    fi

# 应用代码（入口模块 app.main:app；Celery 入口 app.worker.celery_app）
COPY app/ ./app/

# 非 root 运行（安全加固）；预创建数据目录并归属 appuser，
# 使空卷挂载到 /data 时继承正确属主
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/uploads \
    && chown -R appuser:appuser /app /data

USER appuser

EXPOSE 8000

# 健康检查：GET /api/health（与 compose 中 api 服务 healthcheck 一致）
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
