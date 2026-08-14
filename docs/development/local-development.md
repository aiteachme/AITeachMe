# 本地开发

本文是 AITeachMe 本地开发入口。更细的后端、前端和工作流调试说明分别见对应模块 README。

## 环境要求

- Windows 优先支持。
- Python `3.11+`；可以使用 Conda、venv 或其他环境管理器。
- Node.js 建议 `18+`。
- 文件读写和终端输出尽量使用 UTF-8。

## 后端

```powershell
cd backend
$env:PYTHONUTF8 = "1"
pip install -e .
uvicorn app.main:app --reload --reload-dir app --port 9020
```

默认本地数据目录：

```text
backend/data/
```

默认 SQLite：

```text
backend/data/aiteachme.db
```

本地 SQLite 会在 schema drift 时做开发便利处理；云端 PostgreSQL 必须走 Alembic migration，见 [云端数据库迁移](../deployment/cloud-db-migrations.md)。

## 前端

```powershell
cd frontend
npm install
npm run dev
```

默认前端端口是 `5180`。开发模式通过 Vite 代理把 `/api` 转发到 `http://127.0.0.1:9020`。

后端 OpenAPI 变化后，通过 Orval 重新生成前端客户端；不要手改：

```text
frontend/src/api/generated/
```

## 一键脚本

仓库根目录提供 Windows 开发脚本：

```powershell
.\dev.bat
```

脚本会优先复用已有端口，也支持通过 `.env` 或环境变量覆盖：

```env
AITEACHME_BACKEND_PORT=9020
AITEACHME_FRONTEND_PORT=5180
AITEACHME_CONDA_ENV=<your-conda-env>
```

## 环境变量

本地用户侧变量以根目录 `.env.sample` 为主；开发、部署、验证码、通知等变量参考 `.env.developer.sample`。

最小本地示例：

```env
APP_MODE=local
AUTH_ENABLED=false
LLM_API_KEY=<model-api-key>
LLM_BASE_URL=https://api.example.com/v1
```

未开启鉴权的本地模型网关可以不填 `LLM_API_KEY`。实际模型槽位可在设置页或项目 settings override 中配置。
`LLM_API_KEY` / `LLM_BASE_URL` 支持英文逗号配置多组主用 endpoint：等长时按顺序配对，单地址多 key 或单 key 多地址会自动扩展。
备用模型网关可配置 `LLM_FALLBACK_API_KEY` / `LLM_FALLBACK_BASE_URL`，主用 endpoint 失败时接管；备用地址会自动识别 provider，模型默认继承 `models.reason / primary / light`，也可通过 `fallback_models.*` 分别覆盖。

### 模型原生工具

AITeachMe 的课程 RAG 默认使用自管 KnowledgeUnit / 知识图谱 / 本地向量检索，检索结果会进入 prompt 并落入可追踪引用。对于支持 OpenAI Responses built-in tools 的上游，可以在设置页 `模型接入 -> 模型原生工具` 启用 provider 原生工具作为增强：

- `原生联网检索`：把外部/最新信息查询交给 Responses `web_search`。`Auto` 会随 OpenAI / OpenAI-compatible Responses 路线发送，不支持时按接口模式回退；`Force` 用于明确要求兼容网关接收该参数。
- `原生文件检索`：把额外文件检索交给 Responses `file_search`。只有配置 OpenAI `vector_store_id` 列表后才会发送；`Auto` 只在课程工具链且本地 RAG 没有高相关证据时作为补充，`Force` 才会显式强制参与。

`llm.api_mode=auto` 的接口选择是确定性的：`backend/app/shared/infra/llm_support/model_catalog.py` 中 `RESPONSES_API_MODELS` 的文本模型优先走 Responses，名单外文本模型走 Chat Completions；音频、Realtime、图像和视频模型由各自专用集成处理，不属于该文本名单。只有首次 Responses 调用明确表现为网关不支持时，系统才会自动回退一次 Chat Completions。

三层文本模型可分别配置 `llm.reasoning_efforts.light / primary / reason`，`null` 使用模型默认值。设置页会根据已保存的有效模型名动态显示对应下拉框和合法强度；未知的 OpenAI-compatible 自定义模型不会猜测能力，需要时可在 YAML 中显式配置。`extract` 槽位继承 `light` 的强度，备用网关沿用对应逻辑槽位的配置。

建议策略：课程私有资料仍优先使用自管 RAG；需要 provider 托管检索时，再显式配置 `file_search` vector store。

分层约束：项目函数工具（如 `search_kb`、`web_search`、`recall_info`）由本系统执行；模型原生工具由上游 Responses API 执行。Agent tool-call 请求会剥离 `provider_native_tools` hint，最终普通回答和空工具流兜底路径再交给 Responses adapter 转换。

## 常用检查

```powershell
python scripts\check_mojibake.py docs
```

手动接口验证见 [manual-testing.md](./manual-testing.md)。
