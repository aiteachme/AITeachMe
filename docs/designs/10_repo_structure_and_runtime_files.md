# 10. 仓库结构与运行时文件布局

## 1. 目标与适用范围

本文档用于说明：

- 仓库顶层目录分别承担什么职责
- 哪些目录是源码真相源，哪些只是生成物
- 运行时数据默认写到哪里
- 当前开发阶段哪些本地产物是正式业务产物，哪些是调试产物

这篇文档和 `11_database_and_storage_architecture.md` 互补：

- 本文重点解释目录和文件布局
- `11` 重点解释数据库、向量索引和对象存储边界

---

## 2. 仓库顶层结构

AITeachMe 当前采用“前后端同仓库 + 本地优先运行时目录”的组织方式。

| 目录 | 作用 |
| --- | --- |
| `frontend/` | React 前端工程、页面、组件、前端 API、MSW mock |
| `backend/` | FastAPI 后端工程、service、workflow、repository、model、运行时数据 |
| `docs/` | 设计文档、说明材料、架构与开发约定 |
| `scripts/` | 仓库级辅助脚本 |
| `configs/` | 配置模板或说明，不能承载运行时业务数据 |
| `infra/` | 基础设施与部署相关内容 |
| `datasets/` | 样例数据、实验数据或测试材料 |
| `models/` | 外部模型相关资源或说明，不等于后端 `backend/app/models/` |

核心原则是把三类东西分开：

- 源码与设计文档
- 生成物
- 运行时数据

---

## 3. 前端目录职责

### 3.1 `frontend/src/`

| 目录 | 作用 |
| --- | --- |
| `pages/` | 页面入口与用户流程编排 |
| `components/` | 可复用 UI 和业务语义组件 |
| `api/` | 手写 facade、HTTP client、生成代码入口 |
| `mocks/` | MSW mock 与联调辅助 |
| `lib/` | 前端通用工具 |

### 3.2 前端真相源与生成物

前端真相源主要是：

- `frontend/src/pages/*`
- `frontend/src/components/*`
- `frontend/src/api/*`
- `frontend/src/lib/*`
- `frontend/src/mocks/*`

前端生成物主要是：

- `frontend/openapi.json`
- `frontend/src/api/generated/*`
- `frontend/dist/*`

如果生成物和后端实现冲突，优先修后端真相源，再重新生成。

---

## 4. 后端目录职责

### 4.1 `backend/app/`

| 目录 | 作用 |
| --- | --- |
| `api/` | HTTP 路由、资源组、请求/响应边界 |
| `services/` | 用例入口、后台触发、聚合读取与返回封装 |
| `workflows/` | 业务编排中心，负责状态流、LangGraph 图和节点执行 |
| `repositories/` | 数据访问与批量写入逻辑 |
| `models/` | SQLModel 关系模型 |
| `schemas/` | API schema 与传输结构 |
| `core/` | 配置、数据库、LLM、Embedding、日志、异常 |
| `utils/` | 共用工具函数 |

### 4.2 为什么 `workflows/` 是当前关键目录

旧设计文档经常把 `agents/*` 视作主编排层，但当前真相已经变成：

- `services/*` 负责触发和封装
- `workflows/*` 负责真正的流程编排
- `repositories/*` / `models/*` 负责最终持久化

因此阅读复杂业务时，优先沿着：

`api -> service -> workflow -> repository/model`

这条链路走。

### 4.3 后端其他重要目录

| 目录 | 作用 |
| --- | --- |
| `backend/scripts/` | OpenAPI 导出、工作流图导出等工程脚本 |
| `backend/playground/` | 手工实验和局部验证，不是正式业务路径 |
| `backend/data/` | 默认本地运行时数据根目录 |

---

## 5. 运行时数据目录

### 5.1 数据根目录

当前默认通过 `Settings.data_dir` 配置运行时数据根目录，开发时通常是：

`backend/data/`

根目录下主要包含：

- `aiteachme.db`
- `<subject>/...`

### 5.2 学科级目录

当前每个学科目录通常位于：

`backend/data/<subject>/`

其中常见子目录包括：

| 目录 | 作用 | 当前属性 |
| --- | --- | --- |
| `raw/` | 原始上传文件 | 正式业务产物 |
| `markdown/` | Ingest 解析后的 Markdown | 正式业务产物 |
| `assets/` | 文档中提取的图片与资源 | 正式业务产物 |
| `temp/` | 临时处理目录 | 可重建 |
| `knowledge_docs/` | 面向用户的知识文档 Markdown | 正式业务产物 |
| `docgen_intermediate/` | 知识文档生成过程中的中间产物 | 开发/调试友好产物 |
| `debug/` | 开发阶段的统一调试快照目录 | 调试产物 |

推荐把新的调试快照统一写到：

`backend/data/<subject>/debug/<workflow>/<run_or_job_id>/`

---

## 6. 典型生成链路

### 6.1 文件上传后

上传一份资料后，系统通常会同时产生：

- 数据库：`raw_file` 记录
- 本地文件：`raw/<file_id>.<ext>`

### 6.2 Ingest 完成后

解析成功后，系统通常会同时产生：

- 数据库：
  - `raw_file.markdown_path`
  - `raw_file.asset_dir`
  - 解析元信息字段
- 本地文件：
  - `markdown/<raw_file_id>.md`
  - `assets/<raw_file_id>/...`

### 6.3 材料桥接后

Digest 图谱构建前会把解析结果桥接到材料层：

- 数据库：
  - `document`
  - `document_chunk`
  - `chunk_embeddings`

### 6.4 知识构建后

Digest 完成后，数据库会新增或更新：

- `graph_digest_job`
- `knowledge_*`
- `evidence_link`
- `curriculum_derive_job`
- `teaching_unit*`
- `theme_tree*`
- `prereq_dag*`
- `curriculum_snapshot`

### 6.5 知识文档生成后

DocGen workflow 完成后会产生：

- 数据库：
  - `docgen_job`
  - `knowledge_doc`
- 本地文件：
  - `knowledge_docs/*.md`
  - `knowledge_docs/merged_knowledge_base.md`
  - `docgen_intermediate/*.md`
  - `docgen_intermediate/*.json`

---

## 7. 真相源、生成物与运行时产物

### 7.1 真相源

当前真相源包括：

- `backend/app/api/*`
- `backend/app/services/*`
- `backend/app/workflows/*`
- `backend/app/repositories/*`
- `backend/app/models/*`
- `backend/app/schemas/*`
- `backend/app/core/*`
- `frontend/src/pages/*`
- `frontend/src/components/*`
- `frontend/src/api/*`
- `docs/designs/*`

### 7.2 生成物

生成物包括：

- `frontend/openapi.json`
- `frontend/src/api/generated/*`
- `frontend/dist/*`
- `backend/scripts/.generated_workflow_diagrams/*`

### 7.3 运行时产物

运行时产物包括：

- `backend/data/aiteachme.db`
- `backend/data/<subject>/raw/*`
- `backend/data/<subject>/markdown/*`
- `backend/data/<subject>/assets/*`
- `backend/data/<subject>/knowledge_docs/*`
- `backend/data/<subject>/docgen_intermediate/*`
- `backend/data/<subject>/debug/*`

---

## 8. 删除与重建约定

### 8.1 一般可重建

- `temp/`
- 大部分 `docgen_intermediate/`
- `debug/`

### 8.2 谨慎删除

- `markdown/`
- `assets/`
- `knowledge_docs/`

这些目录理论上可以重建，但会影响当前调试状态和页面展示。

### 8.3 非常谨慎删除

- `aiteachme.db`
- 整个 `backend/data/<subject>/`

删除后会清空结构化业务状态，通常等价于重置本地工作空间。

---

## 9. 当前开发约定

### 9.1 调试阶段允许双写

开发阶段默认接受：

- 数据库存结构化真相
- 本地文件存正式产物与调试摘要

这是当前研发效率和可观察性的必要平衡，不是架构污染。

### 9.2 新的本地调试文件统一入 `debug/`

今后新增的 workflow 调试快照不要继续散落到任意目录，统一放到：

`data/<subject>/debug/<workflow>/<run_or_job_id>/`

### 9.3 不要把运行时数据提交到仓库

运行时数据库、知识文档、调试快照都应该被 `.gitignore` 覆盖，而不是作为源码资产提交。

---

## 10. 总结

当前仓库结构已经形成清晰边界：

- 前端与后端源码分别落在 `frontend/` 与 `backend/`
- 复杂业务编排统一进入 `backend/app/workflows/`
- 生成物和真相源分离
- 运行时数据按 `Subject` 隔离落盘

只要持续维护好这张“仓库地图”，后续无论是继续强化本地优先体验，还是演进到中心化部署，团队都能更稳定地判断“应该改哪里、会写到哪里、哪些文件不能当真相源”。
