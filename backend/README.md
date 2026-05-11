# AITeachMe Backend

本目录是 AITeachMe 后端服务，基于 FastAPI + SQLModel + LangGraph，面向本地优先的 AI 学习系统。

## 快速启动

```powershell
cd backend
$env:PYTHONUTF8 = "1"
pip install -e .
uvicorn app.main:app --reload --port 9020
```

默认健康检查：

```text
http://127.0.0.1:9020/api/health
```

## 当前接口形态

- `GET /api/health`
- 业务接口以 `POST` 为主，少量稳定读取接口使用 `GET`
- JSON 接口统一返回 `ApiResponse`
- `chat/send` 使用原生 SSE，不包 `ApiResponse`

主要资源：

- `courses`
- `files`
- `knowledge`
- `chats`
- `exams`
- `profile`
- `system`

## 架构入口

后端当前依赖方向：

```text
api -> workflows -> repositories / shared.infra / models / schemas
shared.infra -> shared.kernel
```

关键文档：

- [系统架构](../docs/architecture/system-architecture.md)
- [领域模型与状态](../docs/architecture/domain-model-and-state.md)
- [Workflows 结构规则](./app/workflows/README.md)
- [Infra 分层说明](./app/shared/infra/README.md)
- [云端数据库迁移](../docs/deployment/cloud-db-migrations.md)

## 环境变量

本地用户侧变量参考仓库根目录 `.env.sample`，开发/部署/验证码/通知变量参考 `.env.developer.sample`。

最小本地示例：

```env
APP_MODE=local
AUTH_ENABLED=false
LLM_API_KEY=<model-api-key>
LLM_BASE_URL=https://api.example.com/v1
```

未开启鉴权的 Ollama、vLLM、LM Studio 等本地网关可以不填 `LLM_API_KEY`。

## 数据库

- 本地：SQLite，默认写入 `backend/data/aiteachme.db`。
- 云端：PostgreSQL + pgvector，必须通过 Alembic migration 和准备脚本管理。

本地 SQLite 会在 schema drift 时做开发便利处理；云端 PostgreSQL 不允许应用启动时自动建表、删表或删列。

## LangGraph Dev

调试入口配置在 `backend/langgraph.json`。

```powershell
cd backend
pip install -e .
pip install -U "langgraph-cli[inmem]"
langgraph dev --config langgraph.json
```

当前主要图包括：

- `ingest_fast_parse`
- `digest_planner`
- `digest_docgen`
- `kg_doc_sync`
- `interact_chat`
- `examine_question_build`
- `examine_exam_grade`
- `profile_update`
- `profile_snapshot`
- `profile_study_plan`

更多调试说明见 [Workflows 调试指南](../docs/workflows/debugging.md)。

## 手动验证

- [本地开发](../docs/development/local-development.md)
- [手动验证](../docs/development/manual-testing.md)
- [API 契约与开发流程](../docs/development/api-contracts-and-dev-workflow.md)
- [playground README](./playground/README.md)
