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
LLM_BASE_URL=https://api.openai.com/v1
# 可选：LLM_PROVIDER=openai|openai_compatible|anthropic|gemini|azure|deepseek|kimi|glm|qwen|minimax|siliconflow|doubao|vllm|ollama|...
# Azure 场景通常还需要：LLM_API_VERSION=2024-10-21
APP_MODE=local
AUTH_ENABLED=false
```

环境变量样例现在拆成两份：

- `.env.sample`：本地用户与设置页主入口
- `.env.developer.sample`：开发 / 部署 / 基础设施 / 验证码 / 通知变量

大多数本地开发只需要先复制 `.env.sample`，再按需从 `.env.developer.sample` 补充部署项。

`LLM_API_KEY / LLM_BASE_URL` 是统一模型接入口，会被对话、规划、出题、批改、Embedding、Vision OCR 等模型能力复用。后端现在会优先根据 `LLM_PROVIDER` 或 `LLM_BASE_URL` 自动识别 OpenAI-compatible、Anthropic、Gemini、Azure、DeepSeek、Kimi、GLM、MiniMax、Doubao、SiliconFlow、vLLM、Ollama 等主流上游，并切换一组更匹配的默认 `models.*`。如果供应商支持的模型名与默认值不同，仍可通过代码默认值、设置页或 `PROJECT_SETTINGS_PATH` 指向的外部 override 文件覆盖 `models.*`。Azure OpenAI 这类上游通常还需要额外提供 `LLM_API_VERSION`；本地 Ollama / vLLM / LM Studio 等未开启鉴权的网关可以不填 `LLM_API_KEY`。

### 3. 启动服务

```bash
uvicorn app.main:app --reload --port 8010
```

首次启动时若缺少 SQLite 相关 Python 依赖，服务会自动尝试安装并继续启动。
数据库文件会自动创建在 `data/aiteachme.db`。
如果检测到本地 SQLite schema 过期，服务会自动备份旧库并重建新库。
云端 PostgreSQL 使用 Alembic 迁移，见 `docs/designs/16_cloud_db_migrations.md`。

## LangGraph Dev 调试

后端现在额外提供了一组只用于调试的 LangGraph 入口，配置文件在 `backend/langgraph.json`。

可调试的 graph 包括：

- `ingest_fast_parse`
- `digest_kg`
- `digest_docgen`
- `digest_unified`
- `interact_chat`
- `examine_question_build`
- `examine_exam_grade`
- `profile_pipeline`

这些 graph 由 `langgraph.json` 直接指向各自 workflow 模块内的图定义或轻量调试工厂函数，不替换原有 FastAPI / service 调用链，也不需要再维护一个单独的汇总入口文件。

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

### LangSmith

如果希望在 LangSmith 中直接查看 workflow 与 LLM 调用链路，可额外配置：

```env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_xxx
LANGSMITH_PROJECT=AITeachMe
# 自建或 EU 区域实例时再配置：
# LANGSMITH_ENDPOINT=https://api.smith.langchain.com
```

当前约定下，workflow 统一运行入口和共享 infra trace 边界会自动继承 tracing 上下文，因此不需要在每个业务节点里重复手写观测代码。
trace 内容预览策略统一由运行时 settings 控制：默认值在代码默认值中定义，也可通过 `PROJECT_SETTINGS_PATH` 指向的外部 override 文件或本地设置页覆盖 `observability.langsmith_capture_inputs / langsmith_capture_outputs / langsmith_max_text_chars`。`null` 表示 `APP_MODE=local` 时保留输入/输出预览，非本地模式默认脱敏。严格隐私场景可额外使用 LangSmith 官方 `LANGSMITH_HIDE_INPUTS / LANGSMITH_HIDE_OUTPUTS`。

## 手动验证

查看以下文档：

- [docs/design.md](./docs/design.md)
- [docs/local-dev.md](./docs/local-dev.md)
- [docs/manual-testing.md](./docs/manual-testing.md)
- [docs/implementation-log.md](./docs/implementation-log.md)
- [playground/README.md](./playground/README.md)
