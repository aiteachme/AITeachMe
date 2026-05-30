# 10. 仓库结构与运行时文件

最后更新：2026-05-13

本文说明当前仓库怎么读、运行时文件落在哪里、哪些目录不要手改。

## 1. 顶层目录

| 目录 | 作用 |
| --- | --- |
| `frontend/` | React 前端 |
| `backend/` | FastAPI 后端 |
| `docs/` | 当前事实源、标准、开发和部署说明 |
| `scripts/` | 仓库级辅助脚本 |
| `infra/` | 部署、Compose、CI、工程运维 |
| `packaging/` | 打包与发布入口；桌面端实现位于 `packaging/desktop/` |

注意：

- 根目录 `infra/` 不是 `backend/app/shared/infra/`。
- 真正应用代码主要是 `frontend/` 和 `backend/`。
- 根 `README.md` 是公开项目首页，负责展示、快速启动和贡献入口；事实边界仍以 `docs/` 与模块 README 为准。
- `.github/`、`.githooks/` 等点目录属于仓库工程配置，不是应用分层的一部分。

## 2. 前端结构

`frontend/` 根目录当前同时承接 Web 前端和桌面端入口：

| 路径 | 作用 |
| --- | --- |
| `frontend/src/` | React 应用源码 |
| `frontend/public/` | Vite public 静态资源；根 README 当前引用 `logo.svg` |
| `frontend/electron/` | Electron 主进程、启动和打包辅助 |
| `frontend/src-tauri/` | Tauri v2 配置、Rust 入口和 local/remote 构建配置 |
| `frontend/openapi.json` | 后端 OpenAPI 快照，供 Orval 生成客户端 |
| `frontend/package.json` | 前端、Electron、Tauri 命令和依赖入口 |

React 源码主结构：

```text
frontend/src/
  api/
    client.ts
    generated/      # Orval 生成，不手改
  components/
  hooks/
  lib/
  pages/
  App.tsx
  main.tsx
```

约束：

- `frontend/src/api/generated/` 不手改。
- 后端 OpenAPI 变化时重新生成，而不是补丁生成代码。
- 设置页本机环境变量只存浏览器 localStorage。
- `frontend/public/logo.svg` 是根 README 当前引用的项目 Logo。

## 3. 后端结构

`backend/` 根目录包含服务入口、迁移、测试、LangGraph 调试和桌面端后端打包辅助：

| 路径 | 作用 |
| --- | --- |
| `backend/app/` | FastAPI 应用源码和业务分层 |
| `backend/migrations/` | Alembic 数据库迁移 |
| `backend/tests/` | 后端测试 |
| `backend/scripts/` | 后端维护和生成脚本 |
| `backend/toolpacks/` | 开发者/管理员可选工具扩展点 |
| `backend/langgraph.json` | LangGraph Dev 调试配置 |
| `backend/data/` | 本地运行时数据目录，不能作为源码层处理 |
| `backend/pyproject.toml` / `backend/uv.lock` | 后端包元数据和锁定依赖 |
| `backend/desktop_server.py` / `backend/*.spec` | 桌面端本地后端打包入口 |

`backend/app/` 是后端应用代码主结构：

```text
backend/app/
  api/
  workflows/
    common/
  shared/
    infra/
    kernel/
  models/
  repositories/
  schemas/
  agent_tools/
  utils/
```

职责：

- `api/`：HTTP 路由。
- `workflows/`：唯一业务层。
- `workflows/common/`：跨 workflow 的轻量业务辅助层，不承接具体业务 graph。
- `shared/infra/`：基础设施能力。
- `models/`：持久化模型。
- `repositories/`：数据库读写。
- `schemas/`：API / workflow 边界结构。
- `agent_tools/`：运行时 agent/tool 查询能力的后端落点。
- `utils/`：纯工具。

已删除且不恢复：

- 旧 services 源层
- 旧 teaching 源层
- `backend/app/shared/infra/facade`
- `backend/app/shared/infra/guardrails`

## 4. 当前知识文档主线

```text
backend/app/api/knowledge_docs.py
  -> app.workflows.digest.planner
  -> confirmed_plan
  -> backend/app/workflows/digest/docgen/lib/build_lifecycle.py
  -> app.workflows.digest.run_docgen_workflow
```

读代码顺序：

1. `backend/app/api/knowledge_docs.py`
2. `backend/app/workflows/digest/planner/README.md`
3. `backend/app/workflows/digest/planner/graph.py`
4. `backend/app/workflows/digest/docgen/README.md`
5. `backend/app/workflows/digest/docgen/graph.py`
6. `backend/app/workflows/digest/docgen/state.py`
7. `backend/app/workflows/digest/docgen/lib/models.py`

其中 `planner/`、`docgen/` 和 `kg_doc_sync/` 目录当前都以各自 `README.md`
为主文档。入口说明和流程判断都以对应目录内的主文档为准。

## 5. 当前学习闭环读代码顺序

如果要理解 README 中描述的五大引擎闭环，建议按下面顺序读：

1. `backend/app/workflows/README.md`
2. `backend/app/workflows/ingest/README.md`
3. `backend/app/workflows/digest/README.md`
4. `backend/app/workflows/interact/README.md`
5. `backend/app/workflows/examine/README.md`
6. `backend/app/workflows/profile/README.md`
7. `backend/app/shared/infra/README.md`

## 6. 运行时文件

本地运行时根目录：

```text
backend/data/
```

默认 SQLite：

```text
backend/data/aiteachme.db
```

Course 级目录：

```text
backend/data/users/<user_id>/courses/<course>/
  raw_files/
  raw_markdowns/
  assets/
  knowledge_markdowns/
    _build/
    versions/
  cache/
```

本地运行时临时目录仍可能位于 course 根目录：

```text
backend/data/<course>/
  debug/
  temp/
  exam/
```

## 7. 关键构建文件

知识文档构建相关：

| 路径 | 作用 |
| --- | --- |
| `knowledge_markdowns/_build/status.json` | 当前或最近一次构建状态 |
| `knowledge_markdowns/_build/manifest.json` | 构建中间 manifest |
| `knowledge_markdowns/.build.lock` | 构建锁 |
| `knowledge_markdowns/docgen_manifest.json` | 发布 manifest |
| `knowledge_markdowns/versions/vXXXX/` | 历史版本 |

演示课程主源：

```text
assets 仓库 -> https://github.com/aiteachme/assets
固定课程索引 -> https://raw.githubusercontent.com/aiteachme/assets/main/demo-courses/catalog/v1/index.json
```

演示课程是公开发行物，放在独立 `aiteachme/assets` 仓库，不和用户私有 OSS 混放。

存储层不提供通用 public URL。用户资料、课程资产和知识文档必须走后端鉴权接口代理返回。

演示课程页面有两条运行时路径：

- 展示课程：后端读取 assets 仓库 index；目录不可用时 `GET /api/v1/demo-courses` 返回空列表。
- 导入当前环境：`POST /api/v1/demo-courses/{identifier}/import` 由当前连接的后端临时下载 `.atmx` 并导入；成功后出现在左侧课程列表。
- 离线分发：运维侧用私有脚本下载 `.atmx`，用户侧再通过“上传导入”入口导入。

前端构建产物：

```text
frontend/dist/
```

## 8. 配置文件

根目录：

- `.env`
- `.env.sample`
- `.env.developer.sample`
- `PROJECT_SETTINGS_PATH` 指向的可选外部 settings override 文件
- `settings.private.yaml`：线上私有 settings override 文件，放项目根目录并由 `.git/info/exclude` 本机排除；Render 线上可用同名 Secret File 提供。

使用口径：

- 环境变量由 `backend/app/shared/infra/env_support.py` 读取。
- `.env.sample` 作为本地用户与设置页主入口；开发 / 部署 / 验证码 / 通知变量放在额外 sample 中供人工合并。
- 本地默认不需要额外 settings 文件；非敏感项目默认配置由代码默认值提供，本地用户可通过设置页写入本地数据库。
- 线上如需固定 `models.reason / primary / light` 等策略，可通过 `PROJECT_SETTINGS_PATH` 指向根目录 `settings.private.yaml` 或 Render 同名 Secret File；私有 YAML 应写全当前 `Settings` schema。
- 用户级非敏感 settings 覆盖存用户数据库。
- 密钥、连接串、SMTP、对象存储等敏感配置不写用户 settings 数据库。

## 9. 不要手改的内容

- `frontend/src/api/generated/`
- `__pycache__/`
- `*.pyc`
- `backend/data/<course>/knowledge_markdowns/_build/`
- `backend/data/<course>/temp/`
- `backend/data/<course>/debug/`
- README 中的 `<!-- CODE_STATS_START -->` 到 `<!-- CODE_STATS_END -->` 区块由 `infra/code_stats/auto_update_readme.py` 维护，手改后可能被脚本覆盖。

## 10. 本地开发约束

- Python 环境：使用 Python 3.11+，先激活自己的项目环境。
- 文件读写统一 UTF-8。
- 修改前确认目标不是生成文件。
- 架构判断优先看当前代码、`backend/app/workflows/*.md`、`backend/app/shared/infra/*.md`。
- `docs/README.md` 是文档导航；模块落点以代码目录 README 为准。

## 11. 推荐阅读顺序

1. 仓库根 `README.md`
2. 本文
3. `docs/architecture/system-architecture.md`
4. `docs/architecture/ai-stack-and-infra.md`
5. `backend/app/workflows/README.md`
6. `backend/app/shared/infra/README.md`
7. 进入具体 engine 或 support README
