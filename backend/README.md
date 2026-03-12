# AiTeachMe Backend

FastAPI 后端服务。

## 本地开发

```bash
# 安装依赖
pip install -r requirements.txt

# 启动开发服务器
uvicorn app.main:app --reload --port 8000
```

访问 http://localhost:8000/api/health 验证是否正常运行。

## 部署 (Render)

后端通过 [Render](https://render.com) 部署，配置文件为仓库根目录的 `render.yaml`。

**自动部署**：连接 GitHub 仓库后，每次 push 到 `main` 分支会自动触发重新部署。

### 手动创建 Web Service

如果不使用 Blueprint (`render.yaml`)，也可以手动配置：

| 配置项 | 值 |
|--------|-----|
| Runtime | Python |
| Root Directory | `backend` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
