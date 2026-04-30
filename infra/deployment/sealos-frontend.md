# Sealos 前端 Nginx 部署与 Cloudflare Pages A/B 测试

本文用于把前端同时部署到 Cloudflare Pages 和 Sealos。Cloudflare Pages 继续保留，Sealos 前端作为新的测试入口，用来对比国内访问速度、API TTFB 和 SSE 稳定性。

## 目标架构

```text
Cloudflare Pages 入口
  Browser -> https://aiteachme.pages.dev -> https://<backend-public>.sealosbja.site/api

Sealos 前端入口
  Browser -> https://<frontend>.sealosbja.site -> Nginx /api -> http://<backend-service>.<namespace>.svc.cluster.local:9020
```

双入口测试阶段不要关闭后端公网访问，因为 Cloudflare Pages 仍然需要直接访问后端公网 API。等最终只保留 Sealos 前端后，才可以关闭后端公网访问。

## 已改造的仓库内容

- `infra/deployment/docker/frontend.Dockerfile` 构建 React 静态产物，并用 Nginx 运行。
- `infra/deployment/nginx/default.conf.template` 是 Sealos 容器运行时配置，支持用 `AITEACHME_API_UPSTREAM` 指向后端内网服务。
- `infra/deployment/nginx/default.conf` 保留给本地 Compose 或手动 Nginx 使用，默认反代 `http://backend:9020`。
- `frontend/public/_headers` 给 Cloudflare Pages 的 Vite hash 资源配置 immutable 缓存。
- `.github/workflows/deploy.yml` 保留 Cloudflare Pages deploy hook，同时新增可选的 Sealos 前端部署 job。

## 1. 在 Sealos 创建前端 App

在 Sealos 新建一个 App，建议名称：

```text
atm-frontend
```

推荐配置：

```text
镜像：crpi-eit0zz7ic5vs22ow.cn-beijing.personal.cr.aliyuncs.com/aiteachme/aiteachme-frontend:nginx-latest
容器端口：80
部署模式：固定实例
实例数：1
CPU：0.25 Core 起步，测试不够再调到 0.5 Core
内存：256 Mi 起步，测试不够再调到 512 Mi
公网访问：开启
环境变量：
  AITEACHME_API_UPSTREAM=http://atm-d-tgkmhxmhacer.ns-icbq3ltw.svc.cluster.local:9020
```

如果后端 Sealos 内网地址变化，把 `AITEACHME_API_UPSTREAM` 改成新的后端内网地址：

```text
AITEACHME_API_UPSTREAM=http://<后端服务名>.<命名空间>.svc.cluster.local:9020
```

前端 App 不要配置 `VITE_API_URL`。Sealos 前端应该走同源 `/api`，再由 Nginx 反代到后端内网服务。

首次创建时，如果 `nginx-latest` 镜像还没有推送，Sealos 可能会短暂拉取失败。创建好 App 和公网地址后，手动触发 GitHub `Deploy` workflow，它会构建并推送镜像，然后更新这个 Deployment。

## 2. 确认 GitHub Actions 部署常量

不敏感的 Sealos 部署信息已经集中写在 `.github/workflows/deploy.yml` 顶部的 `env` 区域：

```yaml
env:
  AITEACHME_API_UPSTREAM: http://atm-d-tgkmhxmhacer.ns-icbq3ltw.svc.cluster.local:9020
  FRONTEND_PUBLIC_URL: https://ghxbqhzlktyi.sealosbja.site
  SEALOS_FRONTEND_DEPLOYMENT: atm-frontend
  SEALOS_NAMESPACE: ns-icbq3ltw
  FRONTEND_ACR_REGISTRY: crpi-eit0zz7ic5vs22ow.cn-beijing.personal.cr.aliyuncs.com
  FRONTEND_ACR_NAMESPACE: aiteachme
  FRONTEND_IMAGE_NAME: aiteachme-frontend
```

以后如果 Sealos 重新生成了前端公网域名、后端内网地址或 App 名称，只改这里即可。

需要继续保留这些 Secrets：

```text
SEALOS_KUBECONFIG_B64
ALIYUN_ACR_USERNAME
ALIYUN_ACR_PASSWORD
```

## 3. 触发部署

进入 GitHub Actions，手动运行 `Deploy` workflow，或者合并到 `main` 后等待 CI 成功触发部署。

成功后会同时发生：

```text
Cloudflare Pages deploy hook 被触发
前端 Nginx 镜像被构建并推送到 ACR/GHCR
Sealos 前端 Deployment 被更新
后端 Sealos Deployment 正常更新
```

Sealos 前端镜像 tag 形如：

```text
crpi-eit0zz7ic5vs22ow.cn-beijing.personal.cr.aliyuncs.com/aiteachme/aiteachme-frontend:nginx-<short-sha>
crpi-eit0zz7ic5vs22ow.cn-beijing.personal.cr.aliyuncs.com/aiteachme/aiteachme-frontend:nginx-latest
```

## 4. 验证 Sealos 前端

先测静态页面：

```bash
curl -I https://<frontend>.sealosbja.site/
```

再测 Nginx 反代后端：

```bash
curl https://<frontend>.sealosbja.site/api/health
```

应该返回后端健康检查响应。

再测静态资源缓存：

```bash
curl -I https://<frontend>.sealosbja.site/assets/<任意 hash js 文件>
```

应该看到：

```text
Cache-Control: public, max-age=31536000, immutable
Content-Encoding: gzip
```

最后用浏览器完整测试：

- 登录
- 新建课程
- 上传资料
- 打开知识库构建页面
- 观察 DocGen SSE 进度是否持续刷新

## 5. A/B 对比方式

同时打开两个入口：

```text
Cloudflare Pages：https://aiteachme.pages.dev
Sealos 前端：https://<frontend>.sealosbja.site
```

用同一个账号和同一份资料对比：

- 首页首屏加载时间
- JS/CSS 加载时间
- `/api/health` TTFB
- 登录、课程列表、资料库 API 响应
- DocGen SSE 是否断流、是否明显延迟

浏览器 DevTools 里重点看 Network：

```text
Doc
JS
CSS
Fetch/XHR
EventStream
```

也可以用命令粗测 TTFB。PowerShell 示例：

```powershell
$urls = @(
  "https://aiteachme.pages.dev/",
  "https://aiteachme.pages.dev/assets/<Cloudflare 上任意 hash js 文件>",
  "https://<backend-public>.sealosbja.site/api/health",
  "https://<frontend>.sealosbja.site/",
  "https://<frontend>.sealosbja.site/assets/<Sealos 上任意 hash js 文件>",
  "https://<frontend>.sealosbja.site/api/health"
)

foreach ($url in $urls) {
  curl.exe -L -o NUL -s -w "$url status=%{http_code} ttfb=%{time_starttransfer} total=%{time_total}`n" $url
}
```

如果 Sealos 前端明显更快，再考虑把正式入口从 Cloudflare Pages 切到 Sealos 前端。

## 6. 什么时候可以关闭后端公网

双入口测试阶段：

```text
前端 Cloudflare Pages：需要后端公网
前端 Sealos Nginx：不需要后端公网
```

所以现在不要关后端公网。

只有当你决定不再使用 Cloudflare Pages 入口，或者 Cloudflare Pages 不再直接请求后端公网 API 时，才可以关闭后端公网访问。最终推荐形态是：

```text
前端 Sealos：开启公网
后端 Sealos：关闭公网，只保留内网
PostgreSQL：关闭公网，只保留内网
```
