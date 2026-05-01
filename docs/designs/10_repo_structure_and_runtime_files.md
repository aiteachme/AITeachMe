# 10. 仓库结构与运行时文件

最后更新：2026-04-27

本文说明当前仓库怎么读、运行时文件落在哪里、哪些目录不要手改。

## 1. 顶层目录

| 目录 | 作用 |
| --- | --- |
| `frontend/` | React 前端 |
| `backend/` | FastAPI 后端 |
| `docs/` | 当前设计文档、标准和说明 |
| `scripts/` | 仓库级辅助脚本 |
| `infra/` | 部署、Compose、CI、工程运维 |
| `datasets/` / `models/` / `configs/` | 辅助资料或说明目录 |

注意：

- 根目录 `infra/` 不是 `backend/app/shared/infra/`。
- 真正应用代码主要是 `frontend/` 和 `backend/`。

## 2. 前端结构

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

## 3. 后端结构

```text
backend/app/
  api/
  workflows/
  shared/
    infra/
    kernel/
  models/
  repositories/
  schemas/
  utils/
```

职责：

- `api/`：HTTP 路由。
- `workflows/`：唯一业务层。
- `shared/infra/`：基础设施能力。
- `models/`：持久化模型。
- `repositories/`：数据库读写。
- `schemas/`：API / workflow 边界结构。
- `utils/`：纯工具。

已删除且不恢复：

- `backend/app/services`
- `backend/app/teaching`
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
2. `backend/app/workflows/digest/planner/FLOW_DESIGN.md`
3. `backend/app/workflows/digest/planner/graph.py`
4. `backend/app/workflows/digest/docgen/FLOW_DESIGN.md`
5. `backend/app/workflows/digest/docgen/graph.py`
6. `backend/app/workflows/digest/docgen/state.py`
7. `backend/app/workflows/digest/docgen/lib/models.py`

其中 `planner/`、`docgen/`、`kg_doc_sync/` 三条 digest 链路目录当前都只保留 `FLOW_DESIGN.md` 这一份主文档；入口说明和流程判断都以各自 `FLOW_DESIGN.md` 为准。

## 5. 运行时文件

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

## 6. 关键构建文件

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
S3_PUBLIC_BASE_URL -> https://<your-cdn-domain>
固定课程索引 -> <S3_PUBLIC_BASE_URL>/demo-courses/catalog/v1/index.json
```

其中 `S3_PUBLIC_BASE_URL` 是发行/部署侧配置，不应出现在普通本地用户设置页；本地开发如需调试演示课程，可在 `.env` 配置同一变量。`index.json` 由本机私有脚本 `scripts/private/demo_course_package.py` 维护。脚本支持上传、下载和删除 `.atmx` 演示课程包，并通过 `.git/info/exclude` 保持不入库。

演示课程页面有两条运行时路径：

- 展示课程：配置 `S3_PUBLIC_BASE_URL` 后读取 OSS index；未配置时后端 `GET /api/v1/demo-courses` 返回空列表。
- 导入当前环境：`POST /api/v1/demo-courses/{identifier}/import` 在配置 `S3_PUBLIC_BASE_URL` 后可用，由当前连接的后端临时下载 `.atmx` 并导入；成功后出现在左侧课程列表。
- 离线分发：运维侧用私有脚本下载 `.atmx`，用户侧再通过“上传导入”入口导入。

前端构建产物：

```text
frontend/dist/
```

## 7. 配置文件

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

## 8. 不要手改的内容

- `frontend/src/api/generated/`
- `__pycache__/`
- `*.pyc`
- `backend/data/<course>/knowledge_markdowns/_build/`
- `backend/data/<course>/temp/`
- `backend/data/<course>/debug/`

## 9. 本地开发约束

- Python 环境：`conda activate atm`
- 文件读写统一 UTF-8。
- 修改前确认目标不是生成文件。
- 架构判断优先看当前代码、`backend/app/workflows/*.md`、`backend/app/shared/infra/*.md`。
- `docs/designs/README.md` 是设计文档导航；模块落点以代码目录 README 为准。

## 10. 推荐阅读顺序

1. 仓库根 `README.md`
2. 本文
3. `docs/designs/01_system_architecture.md`
4. `docs/designs/09_ai_stack_and_infra_guide.md`
5. `backend/app/workflows/README.md`
6. `backend/app/shared/infra/README.md`
7. 进入具体 engine 或 support README / FLOW_DESIGN
