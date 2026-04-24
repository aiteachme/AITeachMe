# 部署配置指南

## 📋 文件结构

根据项目架构规范，所有部署相关文件已组织在 `infra/deployment/` 目录下：

```
infra/deployment/
├── ci/
│   └── deploy.sh              # 服务器部署脚本
├── compose/
│   └── docker-compose.yml     # Docker Compose 编排配置
├── docker/
│   ├── backend.Dockerfile     # 后端容器配置
│   └── frontend.Dockerfile    # 前端容器配置
├── nginx/
│   └── default.conf           # Nginx 反向代理配置
└── deployment.md              # 本文档
```

## 🚀 配置步骤

### 1. 在 GitHub 仓库配置 Secrets

进入仓库 Settings → Secrets and variables → Actions → New repository secret

添加以下 4 个 secrets：

| Secret 名称 | 说明 | 示例 |
|------------|------|------|
| `SERVER_HOST` | 服务器 IP 地址 | `123.45.67.89` |
| `SERVER_USER` | SSH 登录用户名 | `root` 或 `ubuntu` |
| `SSH_PRIVATE_KEY` | SSH 私钥（完整内容） | 见下方说明 |
| `DEPLOY_PATH` | 服务器上项目路径 | `/home/ubuntu/AiTeachMe` |

**获取 SSH 私钥：**
```bash
# 在本地生成密钥对（如果还没有）
ssh-keygen -t ed25519 -C "github-actions"

# 查看私钥内容（复制全部内容到 GitHub Secret）
cat ~/.ssh/id_ed25519

# 将公钥添加到服务器
ssh-copy-id -i ~/.ssh/id_ed25519.pub user@your-server
```

### 2. 服务器初始化

SSH 登录到服务器，执行以下命令：

```bash
# 安装 Docker 和 Docker Compose
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# 克隆项目到服务器
cd /home/ubuntu  # 或你的部署目录
git clone https://github.com/your-username/AiTeachMe.git
cd AiTeachMe

# 给部署脚本添加执行权限
chmod +x infra/deployment/ci/deploy.sh

# 首次手动部署测试
bash infra/deployment/ci/deploy.sh
```

### 3. 验证部署

访问服务器：
- 前端：`http://your-server-ip`
- 后端 API：`http://your-server-ip:9020`

查看容器状态：
```bash
cd infra/deployment/compose
docker compose ps
docker compose logs -f
```

## 🔄 工作流程

1. 本地开发并提交代码到 `main` 分支
2. GitHub Actions 自动触发
3. 通过 SSH 连接到服务器
4. 执行 `infra/deployment/ci/deploy.sh` 脚本
5. 拉取最新代码 → 重建镜像 → 重启容器

## 🔧 自定义配置

### 修改端口

编辑 [compose/docker-compose.yml](compose/docker-compose.yml)：
```yaml
services:
  frontend:
    ports:
      - "3000:80"  # 改为 3000 端口
  backend:
    ports:
      - "8080:9020"  # 改为 8080 端口
```

### 添加环境变量

在 [compose/docker-compose.yml](compose/docker-compose.yml) 中添加：
```yaml
services:
  backend:
    environment:
      - DATABASE_URL=postgresql://...
      - API_KEY=your-key
```

## 🐛 故障排查

**部署失败？**
```bash
cd infra/deployment/compose

# 查看容器日志
docker compose logs backend
docker compose logs frontend

# 重新构建
docker compose build --no-cache
docker compose up -d
```

**SSH 连接失败？**
- 检查服务器防火墙是否开放 SSH 端口
- 确认私钥格式正确（包含 `-----BEGIN` 和 `-----END`）
- 验证服务器用户有 Docker 权限

**容器无法启动？**
- 检查端口是否被占用：`netstat -tulpn | grep :80`
- 查看 Docker 日志：`docker compose logs`
