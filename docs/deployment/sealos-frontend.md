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
- `.github/workflows/deploy.yml`：保留可选 Cloudflare Pages deploy hook，并部署 Sealos 前端/后端；部署拓扑通过 GitHub Repository Variables 配置，真实凭证必须放 GitHub Secrets。

## Sealos App 配置

推荐配置：

```text
Image: <registry>/<namespace>/aiteachme-frontend:nginx-latest
Container Port: 80
Replicas: 1
Public Access: enabled
Environment:
  AITEACHME_API_UPSTREAM=<backend-internal-upstream>
```

前端 App 不要配置 `VITE_API_URL`。Sealos 前端应该走同源 `/api`，再由 Nginx 反代到后端内网服务。

## GitHub Actions 配置

需要在仓库 Secrets 中配置：

```text
SEALOS_KUBECONFIG_B64
ALIYUN_ACR_USERNAME
ALIYUN_ACR_PASSWORD
```

Sealos 部署常量维护在 GitHub Repository Variables 中，例如：

```text
AITEACHME_API_UPSTREAM=<backend-internal-upstream>
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

静态资源缓存：

```bash
curl -I https://<frontend-domain>/assets/<hashed-js-file>
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
