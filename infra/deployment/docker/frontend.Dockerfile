FROM node:18-alpine AS builder

WORKDIR /app

# Keep the Sealos/Nginx image same-origin by default. Cloudflare Pages can still
# inject VITE_API_URL in its own build pipeline.
ARG VITE_API_URL=""
ENV VITE_API_URL=${VITE_API_URL}

# 安装依赖
COPY frontend/package*.json ./
RUN npm ci

# 复制源代码并构建
COPY frontend/ .
RUN npm run build

# 生产镜像
FROM nginx:alpine

# Runtime upstream used by the Nginx template. Override this in Sealos with the
# backend internal service URL, e.g. http://<backend-internal-upstream>.
ENV AITEACHME_API_UPSTREAM=http://backend:9020

# 复制构建产物到 nginx
COPY --from=builder /app/dist /usr/share/nginx/html

# 注入 Kubernetes/Docker 运行时 DNS resolver，避免 Nginx 因 upstream 短暂解析失败而启动退出
COPY infra/deployment/docker/frontend-nginx-resolver.envsh /docker-entrypoint.d/16-aiteachme-resolver.envsh
RUN chmod +x /docker-entrypoint.d/16-aiteachme-resolver.envsh

# 复制 nginx 模板，容器启动时由官方 entrypoint 注入 AITEACHME_API_UPSTREAM
COPY infra/deployment/nginx/default.conf.template /etc/nginx/templates/default.conf.template

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
