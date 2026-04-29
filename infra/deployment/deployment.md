# 部署配置指南

## 📋 文件结构

根据项目架构规范，部署相关文件统一组织在 `infra/deployment/` 目录下。后端镜像从仓库根目录构建，并由根目录 `.dockerignore` 控制上下文内容。当前维护两份后端 Dockerfile：

- `infra/deployment/docker/backend.Dockerfile`：轻量后端镜像，不安装 LibreOffice。
- `infra/deployment/docker/backend-office.Dockerfile`：Office 后端镜像，安装 LibreOffice/soffice，供后续 `.doc` / `.ppt` / `.pptx` 本地转 PDF 链路使用。

后端两份 Dockerfile 都有同名 `.dockerignore`，构建时只发送 `backend/` 必要文件，避免前端源码、文档、本地缓存、`.env` 和运行时数据进入 build context。

```
infra/deployment/
├── ci/
│   └── deploy.sh              # 服务器部署脚本
├── compose/
│   └── docker-compose.yml     # Docker Compose 编排配置
├── docker/
│   ├── backend.Dockerfile     # 轻量后端容器配置
│   ├── backend-office.Dockerfile # 带 LibreOffice 的后端容器配置
│   └── frontend.Dockerfile    # 前端容器配置
├── nginx/
│   └── default.conf           # Nginx 反向代理配置
└── deployment.md              # 本文档
```

## 当前部署结论

- 后端部署优先使用 Docker 镜像；当前推荐生产直接使用 `backend-office.Dockerfile` 构建的 Office 镜像，减少后续支持 PPT/PPTX 时的部署切换。
- 轻量镜像仍保留，适合不需要本地 Office 转换、希望镜像更小的环境。当前产品入口仍只开放 `.pdf` / `.docx` / Markdown / 文本上传。
- 运行模式只由 `APP_MODE` 显式控制；未配置或配置非法时默认 `local`。Render / Sealos 不会被自动识别成云端模式，线上必须配置 `APP_MODE=cloud`。
- 云端正式环境使用 PostgreSQL + pgvector，不使用本地 SQLite。
- 文件与生成产物通过 `STORAGE_BACKEND=s3` 接入 S3-compatible OSS，Render 和 Sealos 都按同一组 `S3_*` 变量配置。
- Render 可以用 Pre-deploy command 跑 `bootstrap_cloud_db.py`；Sealos 多副本时建议用独立 Job 跑迁移和准备脚本，后端容器只启动 Web 服务。

## 🚀 单机 Compose 配置步骤

当前 `compose/docker-compose.yml` 面向单机本地/自托管试运行，默认使用：

- 后端：`APP_MODE=local` + SQLite + `backend-data` Docker volume。
- 前端：Nginx 静态资源 + `/api` 反代到后端容器。

云端正式部署继续优先使用 Render / Sealos 的 PostgreSQL、S3-compatible OSS 和平台环境变量，不把生产数据库直接写进这份 Compose 模板。

### 本地试运行

在仓库根目录执行：

```bash
docker compose -f infra/deployment/compose/docker-compose.yml up --build
```

验证：

- 前端：`http://localhost`
- 后端：`http://localhost:9020/api/health`

停止服务：

```bash
docker compose -f infra/deployment/compose/docker-compose.yml down
```

如需清空本地容器数据，再显式删除 volume：

```bash
docker compose -f infra/deployment/compose/docker-compose.yml down -v
```

## Render 部署

推荐部署形态：

```text
Cloudflare Pages / Render Static Site
  -> Render Docker Web Service
  -> Render PostgreSQL + pgvector
  -> S3-compatible OSS
```

后端使用 Docker runtime。当前可选两类镜像：轻量镜像用于现有 `.pdf` / `.docx` / Markdown / 文本上传；Office 镜像预装 LibreOffice/soffice，便于后续恢复 `.doc`、PPT/PPTX 本地转 PDF 链路。Native Python runtime 不适合维护 LibreOffice 这类系统包。

Render Web Service 建议：

```text
Language / Runtime: Docker
Root Directory: 留空或仓库根目录
Dockerfile Path: infra/deployment/docker/backend-office.Dockerfile
Docker Build Context Directory: .
Health Check Path: /api/health
```

核心环境变量：

```env
APP_MODE=cloud
DATABASE_URL=<Render/PostgreSQL pooled connection string preferred>
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=5
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=1800
DB_POOL_USE_LIFO=true
STORAGE_BACKEND=s3
S3_CREDENTIAL_MODE=static
S3_BUCKET=<bucket>
S3_ENDPOINT=<s3 endpoint>
S3_ACCESS_KEY=<access key>
S3_SECRET_KEY=<secret key>
S3_REGION=<region or auto-compatible value>
S3_ADDRESSING_STYLE=virtual
S3_PUBLIC_BASE_URL=<optional CDN/public base url>
CORS_ALLOWED_ORIGINS=https://your-frontend-domain
AUTH_ENABLED=true
LLM_API_KEY=<model api key>
LLM_BASE_URL=<model api base url>
LLM_CONCURRENCY_LIMIT=8
```

数据库连接建议：

- 生产优先使用 PgBouncer 或平台提供的 pooled connection string，让后端只维护小连接池。
- 总连接预算约等于实例数 * worker 数 * (`DB_POOL_SIZE` + `DB_MAX_OVERFLOW`)；小规格库先从 `3~5` 常驻连接和 `2~5` 溢出连接开始。
- SSE、轮询和后台 workflow 不应长期持有 DB session；接口只在读取/写入状态时短暂取连接。

迁移有两种口径：

- 付费 Web Service：配置 Pre-deploy command：

```bash
python scripts/bootstrap_cloud_db.py
```

然后把 Docker Command 覆盖为只启动服务：

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

- 没有 Pre-deploy：保留镜像默认 `CMD`。它会通过 `scripts/start_cloud_app.py` 在启动前做一次幂等 DB bootstrap，再启动服务。

如果使用 Office 镜像，部署后在 Render Shell 或日志中确认：

```bash
which soffice
soffice --headless --version
```

注意：Render Web Service 必须监听 `0.0.0.0:$PORT`。当前 Dockerfile 默认兼容 Render 的 `PORT=10000`，Compose 会覆盖为 `9020`。

### Render / OSS 上线检查

后端镜像部署完成后，先用平台 Shell 或一次性任务确认基础服务可用：

```bash
python scripts/check_cloud_db.py
python scripts/test_env.py
```

如果使用 Office 镜像，再确认 LibreOffice 可用：

```bash
which soffice
soffice --headless --version
```

对象存储检查：

- `STORAGE_BACKEND=s3` 时必须同时配置 `S3_BUCKET`、`S3_ENDPOINT`、`S3_ACCESS_KEY`、`S3_SECRET_KEY`。
- 如果前端需要直接访问解析资产，配置 `S3_PUBLIC_BASE_URL`，并在 OSS/CDN 侧允许前端域名访问对应对象。
- 首次上线可临时开启 `S3_STARTUP_SMOKE_TEST=true`，确认启动日志里没有 bucket 读写错误；验证完成后关闭，避免每次启动都做额外探测。
- 当前解析链路上传 PDF、DOCX、Markdown/TXT 各一份，确认 `/api/v1/subjects/{subject}/files` 返回 `markdown_ready=true`，并且知识文档页面能展示解析资产。
- 只有在代码层恢复 `.ppt` / `.pptx` 上传与 Office 转 PDF 链路后，才额外验证 PPT/PPTX 转 PDF。

后续迁移到 Sealos 或多副本时，把数据库迁移与服务启动拆开：迁移只由 Job 执行一次，后端 App 只启动 Uvicorn，避免多个副本同时 bootstrap。

## Sealos 部署

推荐部署形态：

```text
Frontend: Cloudflare Pages，或可选 Sealos 静态前端容器
Backend: Sealos App Launchpad 后端容器
Database: Sealos PostgreSQL，需确认 pgvector 可用
Storage: DogeCloud / Sealos Object Storage / 其他 S3-compatible OSS
Migration: 单独 Job / 临时任务运行 bootstrap_cloud_db.py
```

Sealos 更适合使用预构建镜像。先在本地或 CI 从仓库根目录构建并推送后端镜像：

```bash
docker build -f infra/deployment/docker/backend-office.Dockerfile -t <registry>/aiteachme-backend:office-<tag> .
docker push <registry>/aiteachme-backend:office-<tag>
```

也可以用仓库内 PowerShell 脚本：

```powershell
.\scripts\build_backend_image.ps1 -Image <registry>/aiteachme-backend -Variant office -Tag office-<tag> -Push
```

如果明确不需要 LibreOffice，构建轻量镜像：

```bash
docker build -f infra/deployment/docker/backend.Dockerfile -t <registry>/aiteachme-backend:slim-<tag> .
docker push <registry>/aiteachme-backend:slim-<tag>
```

```powershell
.\scripts\build_backend_image.ps1 -Image <registry>/aiteachme-backend -Variant slim -Tag slim-<tag> -Push
```

不要在 Sealos 容器启动后临时 `apt install libreoffice`；系统依赖应在 Docker 构建期固化到镜像里。

如需手动多平台构建并直接推送：

```bash
docker buildx build --platform linux/amd64 -f infra/deployment/docker/backend-office.Dockerfile -t <registry>/aiteachme-backend:office-<tag> --push .
```

创建 PostgreSQL：

1. 在 Sealos Database 中创建 PostgreSQL。
2. 记录内网连接串，写入后端 `DATABASE_URL`。
3. 确认数据库支持 `CREATE EXTENSION vector`。如果不支持 pgvector，应换成支持 pgvector 的 PostgreSQL 服务或自建 pgvector 镜像。

创建对象存储：

1. 如果已经使用 DogeCloud OSS，不需要再创建 Sealos Object Storage。
2. 获取 DogeCloud/S3 endpoint、bucket、access key、secret key。
3. 后端配置 `STORAGE_BACKEND=s3` 和对应 `S3_*` 变量。

先运行一次迁移任务。可以用 Sealos 的 Job/CronJob/临时容器，镜像同后端镜像，命令为：

```bash
python scripts/bootstrap_cloud_db.py
```

迁移任务环境变量至少包含：

```env
APP_MODE=cloud
DATABASE_URL=<postgres connection string>
STORAGE_BACKEND=s3
S3_CREDENTIAL_MODE=static
S3_BUCKET=<bucket>
S3_ENDPOINT=<s3 endpoint>
S3_ACCESS_KEY=<access key>
S3_SECRET_KEY=<secret key>
S3_REGION=auto
LLM_API_KEY=<model api key>
LLM_BASE_URL=<model api base url>
```

创建后端 App：

```text
Image: <registry>/aiteachme-backend:office-<tag>
Container Port: 9020
Environment: 同迁移任务，另加 PORT=9020、AUTH_ENABLED=true、LLM_CONCURRENCY_LIMIT=8、CORS_ALLOWED_ORIGINS=<frontend origins>
Public Address: 使用 Cloudflare Pages 前端时需要开启并绑定 API 域名
Health Check: /api/health
```

单副本试运行可以继续使用镜像默认 `CMD`。如果后续开多副本，建议把后端启动命令改成：

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

并且只通过独立 Job 执行 `bootstrap_cloud_db.py`，避免多个副本同时启动时重复跑迁移准备。

前端部署有两种方式：

- 推荐：继续使用 Cloudflare Pages，构建时设置 `VITE_API_URL=https://<sealos-backend-public-address>`，后端 `CORS_ALLOWED_ORIGINS` 包含 Cloudflare Pages 域名。
- 或者：使用 `infra/deployment/docker/frontend.Dockerfile` 构建前端 Nginx 镜像，并确保 `/api` 能反代到后端服务地址；如果后端服务名不是 `backend`，需要同步调整 `infra/deployment/nginx/default.conf`。

## 云端上线核对清单

正式切流前至少确认：

- 后端健康检查返回正常：`GET /api/health`。
- 如果使用 Office 镜像，容器内 LibreOffice 可用：`which soffice` 与 `soffice --headless --version`。
- 对象存储配置完整：`STORAGE_BACKEND=s3`、`S3_BUCKET`、`S3_ENDPOINT`、`S3_ACCESS_KEY`、`S3_SECRET_KEY`。
- 首次接入新 OSS 时临时打开 `S3_STARTUP_SMOKE_TEST=true`，确认启动日志里没有 bucket 读写/权限错误；稳定后可关闭。
- PostgreSQL 已通过 `python scripts/bootstrap_cloud_db.py` 完成 Alembic migration、运行时对象准备和 schema 检查。
- 多副本部署时只让独立 Job 执行 `bootstrap_cloud_db.py`；Web 容器启动命令保持为 `python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`。
- 前端环境变量 `VITE_API_URL` 指向后端公网地址，且后端 `CORS_ALLOWED_ORIGINS` 包含前端域名。

## 参考文档

- Render Docker: https://render.com/docs/docker
- Render Web Services / PORT: https://render.com/docs/web-services
- Render Deploys / Pre-deploy: https://render.com/docs/deploys
- Sealos App Deploy: https://sealos.io/docs/guides/fundamentals/deploy/
- Sealos Environment Variables: https://sealos.io/docs/guides/app-deploy/environments/
- Sealos PostgreSQL: https://sealos.io/docs/guides/databases/postgresql/
- Sealos Object Storage: https://sealos.io/docs/guides/object-storage/

## 旧式 SSH Compose 部署

这一节只适合自己有一台 Docker 服务器、想直接跑仓库内 Compose 的场景。云端平台部署优先看上面的 Render / Sealos。

`infra/deployment/ci/deploy.sh` 使用 `git pull + docker compose build`，只服务这种旧式 SSH 服务器部署。Sealos / Render 这类容器平台不要在运行中容器里 `git pull` 更新代码，而应使用新的镜像 tag 发布；这样每次上线都能对应到一个明确镜像版本，也方便回滚。

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
