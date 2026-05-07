# AITeachMe Frontend

本目录是 AITeachMe 前端应用，基于 React + TypeScript + Vite，同时承接 Electron / Tauri 桌面端入口。

## 快速启动

```powershell
cd frontend
npm install
npm run dev
```

默认访问：

```text
http://127.0.0.1:5180
```

开发模式默认通过 Vite 代理把 `/api` 转发到 `http://127.0.0.1:9020`。

## 技术栈

- React
- TypeScript
- Vite
- TailwindCSS
- React Router
- TanStack Query
- Lucide Icons

## 当前页面

```text
frontend/src/pages/
├── HomePage.tsx
├── LearningSpacesPage.tsx
├── LibraryPage.tsx
├── BuildPlanPage.tsx
├── KnowledgeDocsPage.tsx
├── KnowledgeInteractivePage.tsx
├── ExamsPage.tsx
├── ProfilePage.tsx
├── GlobalAssistantPage.tsx
└── FeatureOfflinePages.tsx
```

## 生成代码约束

后端 OpenAPI 变化后，通过 Orval 重新生成前端客户端；不要手改：

```text
frontend/src/api/generated/
```

手写 API 代码位于：

```text
frontend/src/api/client.ts
frontend/src/api/types.ts
```

## 构建

```powershell
npm run build
```

构建产物位于：

```text
frontend/dist/
```

桌面端打包需要保留相对静态资源路径，使用：

```powershell
npm run build:desktop
```

## 部署

### 静态站点

前端可以部署到任意 Vite 静态站点平台。生产环境推荐使用同源网关把 `/api/*` 转发到后端；如果临时使用独立 API origin，可以配置：

```env
VITE_API_URL=<backend-api-origin>
```

Web 部署默认使用 `/` 作为 Vite base，保证直接访问 `/courses/<id>/knowledge-docs` 这类深链时仍从 `/assets/*` 加载静态资源。

### Sealos Nginx

前端也可以构建为 Nginx 容器部署，用同源 `/api` 反代后端内网服务：

```text
infra/deployment/docker/frontend.Dockerfile
```

运行时配置：

```env
AITEACHME_API_UPSTREAM=<backend-internal-upstream>
```

完整说明见 [Sealos 前端 Nginx 部署](../docs/deployment/sealos-frontend.md)。

## 文档

- [项目文档导航](../docs/README.md)
- [本地开发](../docs/development/local-development.md)
- [API 契约与开发流程](../docs/development/api-contracts-and-dev-workflow.md)
- [桌面端打包](../packaging/README.md)
