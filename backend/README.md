# AiTeachMe Backend

本目录是 AITeachMe 的后端服务，基于 FastAPI + SQLModel，面向“本地优先”的 AI 助教场景。

## 当前接口形态

- `GET /api/health`
- 业务接口以 `POST` 为主，少量稳定读取接口使用 `GET`
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

要求：Python `3.11+`

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

首次启动时若缺少 SQLite 相关 Python 依赖，服务会自动尝试安装并继续启动。
数据库文件会自动创建在 `data/aiteachme.db`。
如果检测到 schema 过期，服务会自动备份旧库并重建新库。

## LangGraph Dev 调试

后端现在额外提供了一组只用于调试的 LangGraph 入口，配置文件在 `backend/langgraph.json`。

可调试的 graph 包括：

- `ingest_fast_parse`
- `ingest_deep_enhance`
- `digest_kg`
- `digest_curriculum`
- `digest_docgen`
- `digest_unified`
- `interact_chat`
- `examine_question_build`
- `examine_exam_grade`
- `profile_pipeline`

这些 graph 是在现有 FastAPI / service 入口之外新增的调试表面，不替换原有业务调用链。

### 使用说明

1. 使用 Python `3.11+`
2. 在 `backend/` 目录运行：

```bash
pip install -e .
langgraph dev --config langgraph.json
```

### 说明

- `backend` 现在将 Python 版本要求收敛为 `3.11+`，这样 `pip install -e .` 会一并安装 LangGraph Dev 所需依赖。
- `interact_chat` 使用的是“非生产 SSE 外壳”的调试图，目的是在 Studio 里直接观察完整 state，而不改变线上聊天接口行为。
- `profile_pipeline` 是为调试新增的可执行 graph；原有 `profile` 概览图仍然保留。

## 手动验证

查看以下文档：

- [docs/design.md](./docs/design.md)
- [docs/local-dev.md](./docs/local-dev.md)
- [docs/manual-testing.md](./docs/manual-testing.md)
- [docs/implementation-log.md](./docs/implementation-log.md)
- [playground/README.md](./playground/README.md)
