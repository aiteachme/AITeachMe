# AiTeachMe Backend

FastAPI 后端服务。

## 快速开始

### 1. 安装依赖

所有依赖在 `pyproject.toml` 中声明，`requirements.txt` 用于锁定版本。

```bash
pip install -e .
```

### 2. 初始化环境变量

项目会从仓库根目录读取 `.env`。首次启动前，至少需要配置 `LLM_API_KEY`。

推荐直接运行初始化脚本：

```bash
python scripts/init_env.py
```

它会：

- 从 `.env.example` 复制生成 `.env`
- 如果 `.env` 已存在则不覆盖
- 打印下一步需要填写和验证的内容

如果你想手动处理，也可以：

```bash
cp .env.example .env
```

然后编辑 `.env`，至少填入：

```env
LLM_API_KEY=sk-your-api-key-here
```

可选配置项和说明见：

- [docs/local-dev.md](./docs/local-dev.md)
- [.env.example](./.env.example)

### 3. 验证环境变量

在真正启动服务前，建议先跑一次：

```bash
python scripts/test_env.py
```

这能更快发现 API Key、模型名或 Base URL 配置问题。

### 4. 启动服务

```bash
uvicorn app.main:app --reload --port 8000
```

启动后可访问以下地址检查：

- 健康检查：`http://localhost:8000/api/health`
- OpenAPI：`http://localhost:8000/openapi.json`
- Redoc：`http://localhost:8000/redoc`

## 导出 API 文档

```bash
python scripts/export_api_docs.py
```

## 环境变量说明

当前只要求一个必填项：

| 变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `LLM_API_KEY` | 是 | — | 你的 LLM 服务 API Key |

其他配置项都有默认值，通常不需要第一次就修改：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LLM_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | LLM API 地址 |
| `LLM_MODEL` | `qwen-plus` | 对话模型 |
| `EMBEDDING_MODEL` | `text-embedding-v3` | 向量模型 |
| `DATA_DIR` | `./data` | 数据目录 |
| `MAX_UPLOAD_SIZE_MB` | `50` | 上传大小限制 |
| `RAG_TOP_K` | `5` | RAG 检索数量 |
| `RAG_SIMILARITY_THRESHOLD` | `0.3` | RAG 相似度阈值 |
| `CHAT_HISTORY_TURNS` | `10` | 历史对话保留轮数 |



## 部署 (Render)

后端通过 [Render](https://render.com) 部署，配置文件为仓库根目录的 `render.yaml`。

自动部署：连接 GitHub 仓库后，每次 push 到 `main` 分支会自动触发重新部署。

### 手动创建 Web Service

如果不使用 Blueprint (`render.yaml`)，也可以手动配置：

| 配置项 | 值 |
| --- | --- |
| Runtime | Python |
| Root Directory | `backend` |
| Build Command | `pip install -e .` |
| Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
