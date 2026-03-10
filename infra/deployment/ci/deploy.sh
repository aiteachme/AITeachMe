#!/bin/bash
set -e

echo "🚀 开始部署..."

# 拉取最新代码
echo "📥 拉取最新代码..."
git pull origin main

# 重建并重启所有服务
echo "🔨 重建并重启服务..."
cd infra/deployment/compose
docker compose down
docker compose build --no-cache
docker compose up -d

# 清理旧镜像
echo "🧹 清理旧镜像..."
docker image prune -f

echo "✅ 部署完成！"

# 显示运行状态
docker compose ps
