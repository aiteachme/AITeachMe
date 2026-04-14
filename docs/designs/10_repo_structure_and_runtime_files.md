# 10. 仓库结构与运行时文件

最后更新：2026-04-15

这份文档回答四个问题：

1. 当前仓库的代码主体到底在哪里。
2. 前端和后端分别怎么理解。
3. 后端运行时文件现在真实落在哪。
4. 团队协作时哪些目录和文件不能误改。

如果只想先建立整体心智模型，先看这份。
更细的边界说明再看：

- [backend/app/shared/README.md](/c:/Project/Project0GIT/aiteachme/AiTeachMe-main/backend/app/shared/README.md)
- [backend/app/shared/infra/README.md](/c:/Project/Project0GIT/aiteachme/AiTeachMe-main/backend/app/shared/infra/README.md)
- [backend/app/teaching/README.md](/c:/Project/Project0GIT/aiteachme/AiTeachMe-main/backend/app/teaching/README.md)
- [backend/app/workflows/README.md](/c:/Project/Project0GIT/aiteachme/AiTeachMe-main/backend/app/workflows/README.md)
- `docs/designs/refactor/*`

## 1. 先记住三件事

### 1.1 这个项目的应用主体只有两个

- `frontend/`：React 前端
- `backend/`：FastAPI 后端

其他根目录大多是文档、部署、脚本或辅助资料，不是业务主代码区。

### 1.2 仓库根目录的 `infra/` 不是后端里的 `shared/infra`

这是最容易混淆的命名：

- `infra/`
  仓库级部署、CI、统计脚本目录。
- `backend/app/shared/infra/`
  后端应用内部的共享基础设施层。

两者不要混用。

### 1.3 运行时数据现在统一收敛到 `backend/data/`

后端本地运行时的文件、SQLite、学科级中间产物、课程导入目录，当前都以：

- `backend/data/`

为根目录。

## 2. 仓库顶层目录怎么理解

当前最重要的顶层目录如下：

| 目录 | 作用 |
| --- | --- |
| `frontend/` | React 前端应用 |
| `backend/` | FastAPI 后端应用、测试、后端文档 |
| `docs/` | 设计文档、架构文档、交接文档 |
| `configs/` | 配置说明类目录，不是运行时代码主入口 |
| `datasets/` | 数据集或离线资源 |
| `scripts/` | 仓库级开发辅助脚本 |
| `infra/` | 部署、Docker、Compose、CI、代码统计 |
| `models/` | 仓库级建模文档，不是后端 ORM 模型主目录 |

可以把顶层理解成：

```text
frontend + backend = 真正的应用代码
infra + docs + scripts = 配套工程与文档
```

## 3. 前端现在怎么读

### 3.1 前端技术栈

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
| `pages/` | 页面级组件，例如首页、构建页、知识文档页、考试页、画像页 |
| `components/` | 复用 UI、布局组件、页面片段组件 |
| `hooks/` | 前端业务 hooks，例如聊天、知识构建、设置 |
| `lib/` | 页面无关的前端工具函数 |
| `api/client.ts` | Axios / SSE 封装和错误处理入口 |
| `api/generated/` | Orval 生成代码，**不要手改** |
| `mocks/` | Mock 数据与 MSW handler |
| `main.tsx` | 前端入口 |
| `App.tsx` | 路由主入口 |

### 3.3 当前前端路由主线

从 `App.tsx` 看，当前主页面集中在：

- 首页 `HomePage`
- 构建规划页 `BuildPlanPage`
- 知识文档页 `KnowledgeDocsPage`
- 考试页 `ExamsPage`
- 画像页 `ProfilePage`

布局外壳在：

- `components/layout/Layout.tsx`

### 3.4 前端里最重要的协作约束

- `frontend/src/api/generated/` 是 Orval 生成目录，不要手动修改。
- 如果后端 OpenAPI 变化，应该重新生成，而不是去补丁式修改生成文件。

## 4. 后端现在怎么读

### 4.1 后端技术栈

当前后端基于：

- FastAPI
- SQLModel / SQLAlchemy
- LiteLLM
- LangGraph
- LangSmith
- 本地文件存储 / S3 存储双模式
- SQLite / PostgreSQL 双模式

### 4.2 `backend/app/` 的主结构

| 目录 | 作用 |
| --- | --- |
| `api/` | FastAPI 路由层 |
| `services/` | 面向 API 的业务组合层 |
| `shared/` | 共享基础层，下面有 `kernel` 和 `infra` |
| `teaching/` | 教学语义层 |
| `workflows/` | 业务编排层 |
| `models/` | 持久化模型 |
| `repositories/` | 数据库读写封装 |
| `schemas/` | API / service / workflow 边界数据结构 |
| `utils/` | 与单一业务层不完全绑定的辅助代码 |
| `core/` | 项目级核心逻辑和启动相关约束 |

### 4.3 后端各层怎么分工

当前推荐理解方式：

```text
api        = 接 HTTP 请求
services   = 组合流程与返回结果
workflows  = 编排业务主链
teaching   = 表达教学语义
shared     = 提供共享基础能力与 workflow 共用支撑
```

具体边界说明见：

- [backend/app/shared/README.md](/c:/Project/Project0GIT/aiteachme/AiTeachMe-main/backend/app/shared/README.md)
- [backend/app/teaching/README.md](/c:/Project/Project0GIT/aiteachme/AiTeachMe-main/backend/app/teaching/README.md)
- [backend/app/workflows/README.md](/c:/Project/Project0GIT/aiteachme/AiTeachMe-main/backend/app/workflows/README.md)

其中当前要特别记住两点：

- `backend/app/shared/infra/observability/` 是唯一的底层 trace / track 实现层
- `backend/app/shared/infra/workflow/` 是 workflow 共用的 authoring / runtime 支撑层，不是业务引擎目录

## 5. 当前知识构建主链从哪开始

对 AITeachMe 来说，最重要的后端链路之一是知识构建。

当前真实入口大致如下：

1. `backend/app/api/knowledge.py`
   接收前端构建请求。
2. `backend/app/services/knowledge/digest_service.py`
   负责构建前检查、锁、状态写入和后台任务派发。
3. `backend/app/workflows/digest/unified/runtime.py`
   当前 `build_type=all` 的统一构建主入口。
4. `backend/app/workflows/digest/docgen/`
   负责文档侧。
5. `backend/app/workflows/digest/kg/`
   负责图谱侧。
6. `backend/app/workflows/digest/curriculum/`
   负责课程结构侧。

如果新同学要理解“上传资料后最终怎么变成知识文档和知识图谱”，建议从这条链开始读。

## 6. 运行时文件现在真实落在哪

下面这部分非常重要，因为很多架构判断都和运行时文件位置有关。

### 6.1 配置文件

当前主要配置文件：

- 仓库根 `.env`
- 仓库根 `.env.sample`
- 仓库根 `config.yaml`

使用口径：

- 环境变量由 `backend/app/shared/infra/env_support.py` 读取
- 项目级运行配置由 `backend/app/shared/infra/config/` 从 `config.yaml` 读取

### 6.2 后端运行时根目录

当前本地运行时根目录由：

- `backend/app/shared/infra/runtime/paths.py`

统一给出，真实位置是：

- `backend/data/`

### 6.3 SQLite 数据库文件

当前 SQLite 默认路径是：

- `backend/data/aiteachme.db`

这也是 `runtime_paths.get_sqlite_db_path()` 的返回值。

### 6.4 学科级运行时目录

对每个 subject，运行时数据通常收敛到：

- `backend/data/<subject>/`

当前最重要的子目录和文件包括：

| 路径 | 用途 |
| --- | --- |
| `backend/data/<subject>/raw_files/` | 原始上传文件 |
| `backend/data/<subject>/raw_markdowns/` | ingest 后得到的原始 markdown |
| `backend/data/<subject>/assets/` | 解析出的图片、图表等素材 |
| `backend/data/<subject>/knowledge_markdowns/` | 已发布知识文档 |
| `backend/data/<subject>/knowledge_markdowns/_build/` | 构建中的中间文档与构建态文件 |
| `backend/data/<subject>/debug/` | workflow 调试输出 |
| `backend/data/<subject>/temp/` | 临时文件 |
| `backend/data/<subject>/exam/` | 试卷导出等考试相关文件 |

### 6.5 知识文档构建态相关文件

当前以 `ContentStore` 和 `docgen_store` 的真实写入路径为准，关键文件是：

| 路径 | 当前用途 |
| --- | --- |
| `backend/data/<subject>/knowledge_markdowns/_build/status.json` | 当前或最近一次构建的运行时状态 |
| `backend/data/<subject>/knowledge_markdowns/_build/manifest.json` | 构建期 manifest |
| `backend/data/<subject>/knowledge_markdowns/.build.lock` | 构建锁文件 |
| `backend/data/<subject>/knowledge_markdowns/chunk_manifest.json` | chunk manifest |
| `backend/data/<subject>/cache/node_embedding_cache.json` | KG 节点 embedding 持久化缓存 |

这里要特别说明：

- `app.utils.path_helpers` 里仍然保留了一些旧路径 helper。
- 但当前构建状态、manifest、embedding cache 的真实读写，已经以 `ContentStore` / `docgen_store` 为准。
- 所以这几个文件的“权威路径”以上表为准，而不要只看旧 helper 名字猜路径。

### 6.6 课程导入目录

当前一键导入课程包使用的共享目录是：

- `backend/data/_courses/`

这是 `build_courses_dir()` 返回的位置。
前端首页的“导入课程”功能会读取这里的 `.atmx` 文件。

### 6.7 前端构建产物

前端正式构建产物默认在：

- `frontend/dist/`

它属于前端打包结果，不属于后端运行时数据目录。

## 7. 当前哪些文件是生成物或不建议手改

### 7.1 前端生成物

- `frontend/src/api/generated/`：Orval 生成，禁止手改。

### 7.2 Python 字节码缓存

- `__pycache__/` 和 `*.pyc` 是运行时缓存，不是业务源代码。
- 阅读架构时请忽略这些目录。

### 7.3 运行时中间文件

下列路径通常是中间产物，不应作为长期设计依据：

- `backend/data/<subject>/knowledge_markdowns/_build/`
- `backend/data/<subject>/temp/`
- `backend/data/<subject>/debug/`

## 8. 本地开发约定

当前团队协作时建议统一遵守：

- Python 环境使用 `conda activate atm`
- 输入输出文件读写统一使用 UTF-8
- 修改前先确认是不是生成文件或兼容层
- 前端接口变化优先走 OpenAPI / Orval 重新生成，不直接补丁式修改生成代码

## 9. 当前最容易混淆的几个点

### 9.1 `infra/` 和 `backend/app/shared/infra/`

- 前者是仓库部署与工程基础设施
- 后者是后端应用内部共享基础设施

### 9.2 根目录 `models/` 和 `backend/app/models/`

- 根目录 `models/` 不是后端 ORM 主目录
- 真正的持久化模型在 `backend/app/models/`

### 9.3 `digest/build/` 和 `digest/unified/`

- `digest/unified/` 是当前统一构建主链所在目录
- `digest/build/` 现在更偏统一构建相关的兼容与协调层，不是新的主 runtime 主体

### 9.4 旧 helper 路径和当前真实写入路径不完全一致

运行时文件定位时，优先信任：

- `runtime/paths.py`
- `storage/content_store.py`
- `utils/docgen_store.py`

不要只根据旧 `path_helpers.py` 的函数名推断构建态文件位置。

## 10. 阅读顺序建议

第一次接手整个项目，建议按这个顺序读：

1. 仓库根 `README.md`
2. 本文
3. `backend/app/shared/README.md`
4. `backend/app/shared/infra/README.md`
5. `backend/app/teaching/README.md`
6. `backend/app/workflows/README.md`
7. `backend/app/api/knowledge.py`
8. `backend/app/services/knowledge/digest_service.py`
9. `backend/app/workflows/digest/unified/runtime.py`
10. `frontend/src/App.tsx` 与 `frontend/src/pages/*`

## 11. 一句话总结

这个仓库现在的应用主体非常明确：

- `frontend/` 负责界面和交互
- `backend/` 负责业务、AI 与数据
- 本地运行时文件统一收敛到 `backend/data/`

理解清楚这一点，后面再看 `shared / teaching / workflows` 的分层就不会乱。
