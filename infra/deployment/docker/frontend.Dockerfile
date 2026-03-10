FROM node:18-alpine AS builder

WORKDIR /app

# 安装依赖
COPY frontend/package*.json ./
RUN npm install

# 复制源代码并构建
COPY frontend/ .
RUN npm run build

# 生产镜像
FROM nginx:alpine

# 复制构建产物到 nginx
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制 nginx 配置
COPY infra/deployment/nginx/default.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
