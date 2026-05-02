# 云端部署配置

本文记录 AITeachMe 云端部署的当前口径。真实部署常量维护在平台配置或 `.github/workflows/deploy.yml`，文档只写占位符。

## 部署文件

部署相关文件仍放在 `infra/deployment/`：

```text
infra/deployment/
├── ci/
├── compose/
├── docker/
│   ├── backend.Dockerfile
│   ├── backend-office.Dockerfile
│   └── frontend.Dockerfile
└── nginx/
```

两份后端镜像：

- `backend.Dockerfile`：轻量后端镜像，不安装 LibreOffice。
- `backend-office.Dockerfile`：预装 LibreOffice/soffice，供 Office 转 PDF 链路使用。

## 当前结论

- 线上必须显式配置 `APP_MODE=cloud`。
- 云端正式环境使用 PostgreSQL + pgvector，不使用本地 SQLite。
- 文件与生成产物通过 `STORAGE_BACKEND=s3` 接入 S3-compatible OSS。
- Render 可以用 Pre-deploy command 跑 `backend/scripts/bootstrap_cloud_db.py`。
- Sealos 多副本时建议用独立 Job 跑迁移，Web 容器只启动 Uvicorn。

## Compose 本地试运行

```bash
docker compose -f infra/deployment/compose/docker-compose.yml up --build
```

验证：

- 前端：`http://localhost`
- 后端：`http://localhost:9020/api/health`

停止：

```bash
docker compose -f infra/deployment/compose/docker-compose.yml down
```

## Render 部署

推荐形态：

```text
Frontend: Cloudflare Pages / Render Static Site
Backend: Render Docker Web Service
Database: Render PostgreSQL + pgvector
Storage: S3-compatible OSS
```

后端 Docker 设置：

```text
Runtime: Docker
Root Directory: repository root
Dockerfile Path: infra/deployment/docker/backend.Dockerfile
Docker Build Context Directory: .
Health Check Path: /api/health
```

核心环境变量：

```env
APP_MODE=cloud
DATABASE_URL=<postgres pooled connection string>
STORAGE_BACKEND=s3
S3_CREDENTIAL_MODE=static
S3_BUCKET=<bucket>
S3_ENDPOINT=<s3-endpoint>
S3_ACCESS_KEY=<access-key>
S3_SECRET_KEY=<secret-key>
S3_REGION=<region>
S3_ADDRESSING_STYLE=virtual
S3_PUBLIC_BASE_URL=<optional-public-base-url>
CORS_ALLOWED_ORIGINS=<frontend-origins>
AUTH_ENABLED=true
LLM_API_KEY=<model-api-key>
LLM_BASE_URL=<model-api-base-url>
LLM_CONCURRENCY_LIMIT=8
WORKFLOW_STREAM_POSTGRES_BRIDGE_ENABLED=true
```

推荐 Pre-deploy command：

```bash
python scripts/bootstrap_cloud_db.py
```

推荐服务启动命令：

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## Sealos 部署

推荐形态：

```text
Frontend: Cloudflare Pages or Sealos Nginx frontend
Backend: Sealos App
Database: Sealos PostgreSQL with pgvector
Storage: S3-compatible OSS
Migration: one-off Job running bootstrap_cloud_db.py
```

镜像建议使用预构建 tag：

```text
<registry>/<namespace>/aiteachme-backend:slim-<tag>
<registry>/<namespace>/aiteachme-backend:slim-latest
```

如果需要 LibreOffice：

```text
<registry>/<namespace>/aiteachme-backend:office-<tag>
```

后端 App 建议：

```text
Image: <registry>/<namespace>/aiteachme-backend:slim-<tag>
Container Port: 9020
Environment:
  APP_MODE=cloud
  PORT=9020
  AUTH_ENABLED=true
  DATABASE_URL=<postgres connection string>
  STORAGE_BACKEND=s3
  S3_*=<object storage config>
  LLM_API_KEY=<model-api-key>
  LLM_BASE_URL=<model-api-base-url>
  CORS_ALLOWED_ORIGINS=<frontend-origins>
Health Check: /api/health
```

迁移任务命令：

```bash
python scripts/bootstrap_cloud_db.py
```

多副本时，Web 容器不要重复执行 bootstrap；只用独立 Job 跑迁移和运行时对象准备。

## 上线核对

- `GET /api/health` 正常。
- PostgreSQL 已通过 `python scripts/bootstrap_cloud_db.py` 完成 migration、运行时对象准备和 schema 检查。
- `STORAGE_BACKEND=s3` 时对象存储变量完整。
- 首次接入新 OSS 可临时打开 `S3_STARTUP_SMOKE_TEST=true`，验证完成后关闭。
- 如果使用 Office 镜像，确认 `soffice --headless --version` 可执行。
- SSE 网关关闭响应缓冲和压缩；自建 Nginx 可参考 `infra/deployment/nginx/default.conf`。
- 前端域名包含在后端 `CORS_ALLOWED_ORIGINS` 中。

## 参考

- [云端部署架构](./cloud-architecture.md)
- [云端数据库迁移](./cloud-db-migrations.md)
- [Sealos 前端 Nginx 部署](./sealos-frontend.md)
