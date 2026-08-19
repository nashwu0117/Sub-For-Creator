# ============================================================
# Sub-For-Creator 常用命令
#
# 本地开发：
#   make install   安装后端依赖（含 pytest/ruff 开发依赖）
#   make api       启动后端 API（uvicorn 热重载）
#   make worker    启动 Celery worker
#   make web       启动前端 dev server（vite）
#   make test      运行后端测试
#   make lint      ruff 代码检查
#
# Docker 部署：
#   make up        构建镜像并后台启动全部服务（redis/api/worker/web）
#   make logs      跟随查看容器日志
#   make down      停止并删除容器（保留数据卷）
#   make clean     停止并删除容器 + 数据卷（数据会丢失！）
# ============================================================

.PHONY: install test lint api worker web up down logs clean

# 安装后端依赖（含开发依赖）
install:
	pip install -r backend/requirements-dev.txt

# 运行后端测试
test:
	pytest backend/tests

# 代码检查（ruff）
lint:
	ruff check backend

# 本地启动后端 API（热重载；入口 app.main:app，工作目录 backend/）
api:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 本地启动 Celery worker
worker:
	cd backend && celery -A app.worker.celery_app worker --loglevel=info

# 本地启动前端（vite dev server）
web:
	npm --prefix frontend run dev

# Docker 一键部署（构建镜像并后台启动 redis/api/worker/web）
# 注意：GPU 推理需先取消 docker-compose.yml 中 worker 的 deploy 注释块，
# 再重新构建共享镜像：docker compose build --build-arg INSTALL_GPU=1 api
up:
	docker compose up -d --build

# 查看 Docker 日志（-f 跟随；可追加服务名只看单个服务，如 make logs api）
logs:
	docker compose logs -f

# 停止并删除容器（保留 sfc-data / pgdata 数据卷）
down:
	docker compose down

# 停止并删除容器及全部数据卷（数据将丢失！）
clean:
	docker compose down -v
