# ============================================================
# Sub-For-Creator 前端镜像（多阶段构建）
#
# 阶段 1：node:20-alpine 构建 vite 产物 → /app/dist
# 阶段 2：nginx:alpine 托管静态文件 + /api 反向代理（见 nginx.conf）
# ============================================================
FROM node:20-alpine AS build

WORKDIR /app

# 先复制依赖清单，充分利用构建缓存
COPY package*.json ./
RUN npm ci

# 复制源码并构建（产物输出到 frontend/dist，vite 默认）
COPY . .
RUN npm run build

# ---- 运行阶段 ----
FROM nginx:alpine

# 自定义站点配置（SPA fallback + /api 反代 + 缓存策略）
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 拷贝构建产物到 nginx 站点根目录
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
