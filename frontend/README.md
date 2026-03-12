# AiTeachMe Frontend

Vite + Vanilla JS 前端。

## 本地开发

```bash
# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

访问 http://localhost:5173 查看页面。

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `VITE_API_URL` | 后端 API 地址 | `http://localhost:8000` |

本地开发时如果后端也在本地运行则无需配置。部署时需设置为 Render 后端的 URL。

## 部署 (Vercel)

前端通过 [Vercel](https://vercel.com) 部署，配置文件为 `vercel.json`。

**自动部署**：连接 GitHub 仓库后，每次 push 到 `main` 分支会自动触发重新部署。

### Vercel 项目设置

| 配置项 | 值 |
|--------|-----|
| Framework Preset | Vite |
| Root Directory | `frontend` |
| Build Command | `npm run build` |
| Output Directory | `dist` |

### 环境变量（在 Vercel Dashboard 设置）

```
VITE_API_URL=https://你的render后端域名
```
