# 10. 仓库结构与运行时文件

最后更新：2026-04-15

这份文档回答四个问题：

1. 当前仓库里真正的应用代码主要放在哪里
2. 前端和后端分别应该怎么理解
3. 后端运行时文件现在真实落在哪
4. 当前知识文档主线从哪里开始读

如果想先建立全局心智模型，建议先读这份；更细的边界再看：

- [backend/app/shared/README.md](/c:/Project/Project0GIT/aiteachme/AiTeachMe-main/backend/app/shared/README.md)
- [backend/app/shared/infra/README.md](/c:/Project/Project0GIT/aiteachme/AiTeachMe-main/backend/app/shared/infra/README.md)
- [backend/app/workflows/README.md](/c:/Project/Project0GIT/aiteachme/AiTeachMe-main/backend/app/workflows/README.md)
- `docs/designs/refactor/*`

## 1. 先记住三件事

### 1.1 应用主体只有两块

- `frontend/`：React 前端
- `backend/`：FastAPI 后端

仓库根目录其他大多是文档、脚本、部署或辅助资料，不是业务主代码区。

### 1.2 根目录 `infra/` 不是后端里的 `shared/infra`

这两个目录很容易混：

- `infra/`
  仓库级部署、Compose、脚本、统计等工程目录
- `backend/app/shared/infra/`
  后端应用内的共享基础设施层

不要混用。

### 1.3 本地运行时数据统一落在 `backend/data/`

当前后端本地运行时文件统一以 `backend/data/` 为根目录，包括：

- SQLite 数据库
- subject 级原始资料与中间产物
- 知识文档构建状态
- debug / temp / exam 导出目录

## 2. 仓库顶层目录怎么理解

| 目录 | 作用 |
| --- | --- |
| `frontend/` | React 前端应用 |
| `backend/` | FastAPI 后端应用、测试与后端文档 |
| `docs/` | 设计文档、架构文档、重构记录 |
| `scripts/` | 仓库级开发辅助脚本 |
| `infra/` | 部署、Compose、CI 与工程运维材料 |
| `datasets/`、`models/`、`configs/` | 辅助资料或说明目录，不是后端 runtime 主入口 |

可以简单理解成：

```text
frontend + backend = 真正的应用代码
docs + scripts + infra = 配套工程与说明
```

## 3. 前端现在怎么读

### 3.1 技术栈

当前前端基于：

- React
- TypeScript
- Vite
- React Router
- TanStack Query
- Tailwind CSS
- Orval 生成的 API 客户端

### 3.2 `frontend/src/` 的主结构

| 目录 | 作用 |
| --- | --- |
| `pages/` | 页面级组件 |
| `components/` | 复用 UI 与布局组件 |
| `hooks/` | 前端业务 hooks |
| `lib/` | 页面无关的前端工具函数 |
| `api/client.ts` | Axios / SSE 封装入口 |
| `api/generated/` | Orval 生成代码，不手改 |
| `mocks/` | Mock 数据与 MSW handler |
| `App.tsx`、`main.tsx` | 前端主入口 |

### 3.3 当前前端协作约束

- `frontend/src/api/generated/` 是 Orval 生成目录，不手改
- 如果后端 OpenAPI 变化，优先重新生成，而不是直接补丁生成代码

## 4. 后端现在怎么读

### 4.1 技术栈

当前后端基于：

- FastAPI
- SQLModel / SQLAlchemy
- LangGraph
- LiteLLM
- LangSmith
- SQLite / PostgreSQL 双模式
- 本地存储 / S3 双模式

### 4.2 `backend/app/` 的主结构

| 目录 | 作用 |
| --- | --- |
| `api/` | FastAPI 路由层 |
| `shared/` | 共享基础层，下面分 `kernel` 与 `infra` |
| `workflows/` | 唯一业务层，承接业务用例、五大引擎编排与 support 模块 |
| `models/` | 持久化模型 |
| `repositories/` | 数据读写封装 |
| `schemas/` | API / service / workflow 边界数据结构 |
| `shared/infra/`、`shared/kernel/`、`utils/` | 共享基础设施、底层原语与通用辅助代码 |

### 4.3 推荐分工理解

```text
api        = 接 HTTP 请求
workflows  = 组织业务用例、编排业务主链、提供教学表达
shared     = 提供共享基础能力
```

## 5. 当前知识文档主线从哪里开始

这一轮最需要记住的是：当前知识文档主线已经不是旧文档里那种“直接 unified build 一条线”的表达方式。

更符合当前代码现状的主线是：

```text
backend/app/api/knowledge_docs.py
-> backend/app/workflows/digest/planner/sessions.py
-> backend/app/workflows/digest/planner/
-> confirmed_plan
-> backend/app/workflows/digest/docgen/builds.py
-> backend/app/workflows/digest.run_docgen_workflow
```

拆开看就是两段：

### 5.1 Planner 阶段

- API 先创建或修订 build planner session
- `planner/sessions.py` 调 `app.workflows.digest.planner`
- planner 产出规范化的 plan payload
- 用户确认后，固化成 confirmed plan

### 5.2 DocGen 阶段

- `docgen/builds.py` 读取 confirmed plan
- 校验 build lock、文件选择、向量状态
- 调 `app.workflows.digest.run_docgen_workflow`
- docgen graph 再去执行 research / writer / assemble / publish

对当前批次来说，这条 planner-confirm-docgen 主线才是需要优先阅读和维护的真实链路。

## 6. `digest` 其他子目录怎么理解

`backend/app/workflows/digest/` 下面还有：

- `events.py`、`exports.py`
  Digest 模块根级别入口。
- `docgen/__init__.py`、`knowledge_graph/__init__.py`
  Digest workflow runner 入口。
- `planner/`
  负责确认式构建方案生成。
- `docgen/`
  负责知识文档生成，真实 helper 位于 `docgen/lib/`，旧 `docgen/internal/` 已删除。
- `knowledge_graph/`
  负责知识图谱 lane，内部共享能力收口到 `knowledge_graph/lib/`。
- `common/`
  Digest 跨链路通用材料准备、模型、指标，以及教学语义入口（如 `runtime_config.py`、`pedagogy/`）。

这些目录当前仍在演进中，具体设计以代码、`backend/app/workflows/STRUCTURE.md` 和 `docs/designs/refactor/*` 为准。

这份总览文档不再把它们的内部阶段图写成当前批次的权威描述，避免旧文档比代码还“强势”。

## 7. 运行时文件现在真实落在哪

### 7.1 配置文件

当前主要配置文件：

- 仓库根 `.env`
- 仓库根 `.env.sample`
- 仓库根 `settings.yaml`

使用口径：

- 环境变量由 `backend/app/shared/infra/env_support.py` 读取
- 项目级运行配置由 `backend/app/shared/infra/settings/` 从 `settings.yaml` 读取

### 7.2 后端运行时根目录

本地运行时根目录由 `backend/app/shared/infra/runtime/paths.py` 统一给出，当前真实位置是：

- `backend/data/`

### 7.3 SQLite 数据库

默认 SQLite 路径：

- `backend/data/aiteachme.db`

### 7.3 补充：subject 级 infra 能力现在怎么放

`backend/app/shared/infra/` 里与学科向量相关的共享能力，当前已经收口到：

- `backend/app/shared/infra/subject/settings.py`
- `backend/app/shared/infra/subject/vectors.py`
- 稳定导入面：`app.shared.infra.subject`

这样做的目的是把：

- `Subject.settings_json` 的结构化绑定
- 运行时 embedding / vector capability 的只读判定

放进同一个浅层子包，而不是继续把 subject 级向量能力散落在 `shared/infra/` 根目录。

同时，交互链路里负责上下文窗口预算和消息截断的工具，当前位于：

- `backend/app/shared/infra/llm_support/context_window.py`

它属于 LLM 输入组织层，而不是 `shared/infra/` 根目录级别的通用杂项文件。

### 7.4 Subject 级运行时目录

每个学科通常落在：

- `backend/data/<subject>/`

当前常见子目录：

| 路径 | 用途 |
| --- | --- |
| `backend/data/<subject>/raw_files/` | 原始上传文件 |
| `backend/data/<subject>/raw_markdowns/` | ingest 后的原始 markdown |
| `backend/data/<subject>/assets/` | 图片、图表等素材 |
| `backend/data/<subject>/knowledge_markdowns/` | 已发布知识文档 |
| `backend/data/<subject>/knowledge_markdowns/_build/` | 构建中间态 |
| `backend/data/<subject>/debug/` | workflow 调试输出 |
| `backend/data/<subject>/temp/` | 临时文件 |
| `backend/data/<subject>/exam/` | 考试相关导出文件 |

### 7.5 知识文档构建状态文件

当前应以 `ContentStore` / `docgen_store` 的真实写入路径为准，关键文件包括：

| 路径 | 用途 |
| --- | --- |
| `backend/data/<subject>/knowledge_markdowns/_build/status.json` | 当前或最近一次构建状态 |
| `backend/data/<subject>/knowledge_markdowns/_build/manifest.json` | 构建 manifest |
| `backend/data/<subject>/knowledge_markdowns/.build.lock` | 构建锁 |
| `backend/data/<subject>/knowledge_markdowns/chunk_manifest.json` | chunk manifest |
| `backend/data/<subject>/cache/node_embedding_cache.json` | 节点 embedding 缓存 |

旧 helper 名称可能还在，但路径判断请优先以当前 storage / docgen store 实现为准。

### 7.6 课程包导入目录

共享课程包目录：

- `backend/data/_courses/`

### 7.7 前端构建产物

前端正式构建产物默认在：

- `frontend/dist/`

它属于前端打包结果，不属于后端运行时数据目录。

## 8. 哪些文件不要手改

### 8.1 生成代码

- `frontend/src/api/generated/`

### 8.2 Python 缓存

- `__pycache__/`
- `*.pyc`

### 8.3 运行时中间文件

这些通常是中间产物，不应作为长期设计依据：

- `backend/data/<subject>/knowledge_markdowns/_build/`
- `backend/data/<subject>/temp/`
- `backend/data/<subject>/debug/`

## 9. 当前本地开发约束

当前团队协作时建议统一遵守：

- Python 环境使用 `conda activate atm`
- 输入输出文件读写统一使用 UTF-8
- 修改前先确认是不是生成文件或兼容层
- 前端接口变化优先走 OpenAPI / Orval 重生成

## 10. 推荐阅读顺序

第一次接手当前主线，建议按下面顺序：

1. 仓库根 `README.md`
2. 本文
3. `backend/app/shared/README.md`
4. `backend/app/shared/infra/README.md`
5. `backend/app/workflows/README.md`
6. `backend/app/workflows/support/README.md`
7. `backend/app/api/knowledge_docs.py`
8. `backend/app/workflows/digest/planner/sessions.py`
9. `backend/app/workflows/digest/docgen/builds.py`
10. `backend/app/workflows/digest/planner/`
11. `backend/app/workflows/digest/docgen/`
12. `frontend/src/App.tsx` 与 `frontend/src/pages/*`

## 11. 一句话总结

这个仓库当前最重要的应用主体非常明确：

- `frontend/` 负责界面和交互
- `backend/` 负责业务、AI 与数据
- 当前知识文档主线优先看 planner-confirm-docgen
- 本地运行时文件统一落在 `backend/data/`
