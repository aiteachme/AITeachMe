# 10. 仓库结构与运行时文件

最后更新：2026-04-19

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
2. `backend/app/workflows/digest/planner/README.md`
3. `backend/app/workflows/digest/planner/graph.py`
4. `backend/app/workflows/digest/docgen/README.md`
5. `backend/app/workflows/digest/docgen/graph.py`
6. `backend/app/workflows/digest/docgen/lib/models.py`

## 5. 运行时文件

本地运行时根目录：

```text
backend/data/
```

默认 SQLite：

```text
backend/data/aiteachme.db
```

Subject 级目录：

```text
backend/data/<subject>/
  raw_files/
  raw_markdowns/
  assets/
  knowledge_markdowns/
    _build/
    versions/
  cache/
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

课程包共享目录：

```text
backend/data/_courses/
```

前端构建产物：

```text
frontend/dist/
```

## 7. 配置文件

根目录：

- `.env`
- `.env.sample`
- `PROJECT_SETTINGS_PATH` 指向的可选外部 settings override 文件

使用口径：

- 环境变量由 `backend/app/shared/infra/env_support.py` 读取。
- 非敏感项目默认配置由代码默认值提供；如有需要，可通过 `PROJECT_SETTINGS_PATH` 叠加外部 override。
- 用户级非敏感 settings 覆盖存用户数据库。
- 密钥、连接串、SMTP、对象存储等敏感配置不写用户 settings 数据库。

## 8. 不要手改的内容

- `frontend/src/api/generated/`
- `__pycache__/`
- `*.pyc`
- `backend/data/<subject>/knowledge_markdowns/_build/`
- `backend/data/<subject>/temp/`
- `backend/data/<subject>/debug/`

## 9. 本地开发约束

- Python 环境：`conda activate atm`
- 文件读写统一 UTF-8。
- 修改前确认目标不是生成文件。
- 架构判断优先看当前代码、`backend/app/workflows/*.md`、`backend/app/shared/infra/*.md`。

## 10. 推荐阅读顺序

1. 仓库根 `README.md`
2. 本文
3. `docs/designs/01_system_architecture.md`
4. `docs/designs/09_ai_stack_and_infra_guide.md`
5. `backend/app/workflows/README.md`
6. `backend/app/workflows/STRUCTURE.md`
7. `backend/app/shared/infra/README.md`
8. 进入具体 engine README
