# Sealos 前端 Nginx 部署

本文用于说明如何把前端作为 Nginx 静态容器部署到 Sealos，并通过同源 `/api` 反代后端内网服务。

## 目标架构

```text
Browser
  -> https://<frontend-domain>
  -> Nginx /api
  -> <backend-internal-upstream>
```

当前推荐后端只保留 Sealos 内网地址，不再暴露公网地址。Cloudflare Pages 入口可以保留为静态发布或预览入口；生产 API 流量应统一走 Sealos Nginx 前端的同源 `/api` 反代。

## 仓库内容

- `infra/deployment/docker/frontend.Dockerfile`：构建 React 静态产物并用 Nginx 运行。
- `infra/deployment/nginx/default.conf.template`：容器运行时模板，通过 `AITEACHME_API_UPSTREAM` 指向后端内网服务。
- `infra/deployment/nginx/default.conf`：本地 Compose 或手动 Nginx 默认配置。
- `frontend/public/_headers`：Cloudflare Pages 静态资源缓存配置。
- `.github/workflows/deploy.yml`：可把已验证 SHA 构建出的前端产物直接上传到 Cloudflare Pages，并部署 Sealos 前端/后端；非敏感部署常量可直接维护在 workflow，真实凭证必须放 GitHub Secrets。

## Sealos App 配置

推荐配置：

```text
Image: <registry>/<namespace>/aiteachme-frontend:nginx-latest
Container Port: 80
Replicas: 1
Public Access: enabled
Environment:
  AITEACHME_API_UPSTREAM=<backend-internal-upstream>
  AITEACHME_NGINX_IMPORT_CLIENT_MAX_BODY_SIZE=260m
  VITE_POSTHOG_ENABLED=true
  VITE_POSTHOG_TOKEN=<posthog-project-token>
  VITE_POSTHOG_HOST=https://us.i.posthog.com
  VITE_POSTHOG_SESSION_REPLAY=false
  VITE_POSTHOG_DEBUG=false
```

前端 App 不要配置 `VITE_API_URL`。Sealos 前端应该走同源 `/api`，再由 Nginx 反代到后端内网服务。

前端 Web 镜像默认使用 `VITE_BASE_PATH=/` 构建静态资源路径，避免深链页面把 JS/CSS 错误解析成相对路径。只有部署到子路径时才需要覆盖这个值。

PostHog 这类浏览器端配置由容器启动脚本写入 `/runtime-config.js`，所以 Sealos 的运行时环境变量会在页面加载时生效；不需要把这些值作为 Docker build args 重新构建镜像。注意优先在前端 App 配置 `VITE_POSTHOG_*` 这组公开浏览器变量。脚本也会兼容读取同一前端容器里的 `POSTHOG_ENABLED`、`POSTHOG_TOKEN`、`POSTHOG_HOST`、`POSTHOG_DEBUG` 作为兜底；后端 App 如需采集服务端事件则仍应单独配置 `POSTHOG_*`。

## 上传大小与网关限制

后端资料上传由 `ingest.max_upload_size_mb` 控制；默认值来自 `backend/app/shared/infra/settings/defaults.py` 的 `DEFAULT_INGEST_MAX_UPLOAD_SIZE_MB`。普通资料上传的业务上限只改这个默认变量或运行时 settings，不需要同步修改 Nginx。

前端 Nginx 对资料上传只保留传输天花板，默认复用 `AITEACHME_NGINX_IMPORT_CLIENT_MAX_BODY_SIZE=260m`，避免业务上限调到 20MB 以上时被旧的 10m/12m 网关配置提前截断。后端会分块读取上传内容，超过 `ingest.max_upload_size_mb` 会立即返回 413。

课程包导入 `.atmx` 走 `/api/v1/courses/import`，后端包大小上限为 256MB；Nginx 使用 `AITEACHME_NGINX_IMPORT_CLIENT_MAX_BODY_SIZE=260m`。

如果 Sealos 公网访问层、Ingress、Cloudflare 或其他网关也配置了请求体大小限制，需要同步放大到至少 260m。否则请求会先被外层网关拦截，后端和容器内 Nginx 的设置都不会生效。

## GitHub Actions 配置

需要在仓库 Secrets 中配置：

```text
SEALOS_KUBECONFIG_B64
ALIYUN_ACR_USERNAME
ALIYUN_ACR_PASSWORD
```

Sealos 部署常量维护在 `.github/workflows/deploy.yml` 的 `env` 中，例如：

```text
AITEACHME_API_UPSTREAM=<backend-internal-upstream>
AITEACHME_NGINX_IMPORT_CLIENT_MAX_BODY_SIZE=260m
FRONTEND_PUBLIC_URL=https://<frontend-domain>
SEALOS_FRONTEND_DEPLOYMENT=<frontend-deployment>
SEALOS_NAMESPACE=<namespace>
FRONTEND_ACR_REGISTRY=<acr-registry>
FRONTEND_ACR_NAMESPACE=<acr-namespace>
FRONTEND_IMAGE_NAME=aiteachme-frontend
SEALOS_IMAGE_PULL_SECRET=<image-pull-secret>
```

缺少 `SEALOS_KUBECONFIG_B64`、`ALIYUN_ACR_USERNAME` 或 `ALIYUN_ACR_PASSWORD` 时，Sealos 部署 job 会跳过，不会执行真实部署。

生成 kubeconfig base64：

```powershell
$raw = Get-Content -Raw -Encoding UTF8 "<path-to-kubeconfig.yaml>"
[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($raw))
```

## 验证

静态页面：

```bash
curl -I https://<frontend-domain>/
```

API 反代：

```bash
curl https://<frontend-domain>/api/health
```

上传链路 body limit：

```bash
eval "$(python backend/scripts/resolve_upload_probe.py)"
python backend/scripts/smoke_upload_body.py --url https://<frontend-domain>/api/v1/files/upload --expected-status 422 --bytes "${upload_probe_bytes}" --label "${upload_probe_label}"
```

静态资源缓存：

```bash
curl -I https://<frontend-domain>/assets/<hashed-js-file>
```

运行时前端配置：

```bash
curl https://<frontend-domain>/runtime-config.js
```

SPA 深链：

```bash
curl https://<frontend-domain>/courses/<course-id>/knowledge-docs
```

浏览器里重点验证：

- 登录
- 新建课程
- 上传资料
- 知识文档构建
- DocGen SSE 进度刷新

## 后端内网化口径

后端 App 保持 internal only，不配置公网访问地址。外部用户只访问 Sealos 前端域名，前端 Nginx 再通过 `AITEACHME_API_UPSTREAM` 访问后端内网服务。

推荐最终形态：

```text
Frontend: Sealos public
Backend: Sealos internal only
PostgreSQL: internal only
```
