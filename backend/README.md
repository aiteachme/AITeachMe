# AiTeachMe Backend

本目录是 AITeachMe 的后端服务，基于 FastAPI + SQLModel，面向“本地优先”的 AI 助教场景。

## 当前接口形态

- `GET /api/health`
- 其余业务接口全部使用 `POST`
- JSON 接口统一返回：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

- `chat/send` 仍然保留原生 SSE，不包 `ApiResponse`

## 主要资源

- `subjects`
- `files`
- `knowledge`
- `chat`
- `exam`
- `profile`

新增的动作接口：

- `files/retry`
- `files/delete`
- `knowledge/retry`
- `knowledge/delete`
- `chat/clear`
- `exam/delete`

## 快速启动

### 1. 安装依赖

```bash
pip install -e .
```

### 2. 配置 `.env`

至少需要：

```env
LLM_API_KEY=sk-your-api-key-here
APP_MODE=local
AUTH_ENABLED=false
```

### 3. 启动服务

```bash
uvicorn app.main:app --reload --port 8000
```

## 手动验证

查看以下文档：

- [docs/design.md](./docs/design.md)
- [docs/local-dev.md](./docs/local-dev.md)
- [docs/manual-testing.md](./docs/manual-testing.md)
- [docs/implementation-log.md](./docs/implementation-log.md)
- [playground/README.md](./playground/README.md)
