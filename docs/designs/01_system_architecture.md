# 01. 系统架构

## 1. 文档定位

本文档只回答当前系统最核心的三个问题：

- AITeachMe 当前主链路怎么走；
- 前端、API、workflow、repository、model、shared infra 的职责边界是什么；
- 在现有实现上，后续架构演进应该优先做什么。

---

## 2. 当前主链路

当前系统围绕 `Subject` 这个工作空间边界组织，主链路可概括为：

`RawFile -> raw_markdowns/assets -> RetrievalChunk -> KnowledgeDocument + KnowledgeNode/KnowledgeEdge -> TeachingUnit/Curriculum -> Chat/Exams/Profile`

关键约束：

1. Ingest 负责把原始资料变成可消费材料层。
2. Digest 统一构建文档、图谱、课程快照。
3. Examine 与 Profile 共用同一套教学锚点，不维护平行数据模型。
4. Interact、Examine、Profile 都消费同一学科下的知识与课程对象。

---

## 3. 分层与职责

### 3.1 前端层（React）

主要页面位于 `frontend/src/pages/`：

- `HomePage`
- `FilesPage`
- `KnowledgeDocsPage`
- `KnowledgeGraphPage`
- `ChatPage`
- `ExamsPage`
- `ProfilePage`

前端负责页面交互、请求编排和状态展示，不承载知识构建逻辑。

### 3.2 API 层（FastAPI）

`backend/app/api/*` 负责：

- 资源分组与鉴权上下文注入；
- 请求参数接收与响应封装；
- 错误码与异常转换。

当前接口形态是“POST 为主 + 少量 GET 读接口 + SSE”。

### 3.3 Workflow 层（唯一业务层）

`backend/app/workflows/*` 负责：

- API-facing 用例入口（模块根用例文件、具体 lane 与 `support/`）；
- LangGraph 状态推进；
- 节点并发与降级策略；
- 事件发布、失败恢复、观测摘要。

这是当前后端业务流程的第一真相源。旧 `backend/app/services` 源层已经移除，原服务能力迁入 `workflows/*` 或 `workflows/support/*`。

### 3.4 Repository / Model 层

`repositories/* + models/*` 负责结构化持久化：

- 业务表读写；
- 批量查询与更新；
- 兼容字段映射。

### 3.5 Shared Infra / Utils

- `shared/infra/*`：配置、数据库、存储、LLM、embedding、search、tools、skills、MCP、memory、workflow 支撑、observability 等共享基础能力。
- `shared/kernel/*`：异常、时间、ID、事件等最底层原语。
- `utils/*`：路径、展示、时间等跨层纯工具（如 `path_helpers`、`docgen_store`）。

---

## 4. 分层依赖方向

推荐依赖方向：

`api -> workflows -> repositories / shared.infra / models / schemas`

补充：

- `repositories/models` 为持久化支撑层，主要被 workflows 消费；
- `utils` 为横切纯工具层，可被上层调用；
- `shared.infra` 不反向依赖 `api`、`workflows` 或历史 `services/teaching` 语义。

---

## 5. 五大引擎当前落地

### 5.1 Ingest（透视引擎）

- 入口：`api/files.py` + `workflows/support/files` + `workflows/ingest/parse_files.py`
- 核心：两阶段解析（Fast Parse + Deep Enhance）
- 产物：`raw_files/`、`raw_markdowns/`、`assets/`、`raw_file` 元数据

### 5.2 Digest（织网引擎）

- 入口：`api/knowledge_docs.py` + `workflows/digest/planner` + `workflows/digest/docgen` + `workflows/digest/knowledge_graph`
- 核心：Planner 生成 confirmed plan；DocGen 独立生成知识文档；Knowledge Graph 独立生成图谱并触发 curriculum
- 产物：`knowledge_document`、`knowledge_node/edge`、`curriculum/theme_tree_node/unit_dependency`

### 5.3 Interact（伴读引擎）

- 入口：`api/chats.py`（`POST + SSE`）+ `workflows/interact/application` + `workflows/interact/chat/runtime.py`
- 核心：history/retrieval/strategy/prompt/stream/persist 节点链路
- 产物：`chat_session`、`chat_message`、可追踪 contexts

### 5.4 Examine（诊断引擎）

- 入口：`api/exams.py` + `workflows/examine/application` + `workflows/examine/*`
- 核心：风格画像、题模板生成、组卷、判卷、回写 profile
- 产物：`question_template`、`exam_paper`、`exam_paper_item`

### 5.5 Profile（显影引擎）

- 入口：`api/profile.py` + `workflows/profile/application` + `workflows/profile/*`
- 核心：掌握度更新、复习调度、学科画像聚合、用户画像聚合
- 产物：`user_knowledge_state`、`subject.profile_json`、`user.profile_json`

---

## 6. 运行时与存储真相

当前默认运行底座：

- DB：`SQLite`
- 向量：`sqlite-vec`
- 文件：本地文件系统

`Subject` 同时决定：

- API 路由边界；
- 运行时目录边界；
- workflow 隔离边界。

---

## 7. 当前已落地的长任务机制

应用级长任务由 `BackgroundTaskRegistry` 托管：

- `files/upload` 触发后台 parse；
- `knowledge/build` 按 `build_type` 触发后台 docs 或 graph 构建；
- 进程关闭时统一取消与回收。

这让“长流程执行”与“HTTP 接口返回”解耦，但没有新增复杂 job API 面。

---

## 8. 当前架构边界与未来演进

### 8.1 当前边界

1. exam 生成/判卷仍是同步 HTTP 触发。
2. observability 已有 runtime summary，但未统一对外 API 暴露。
3. services 源层已移除；后续重点是继续压实 `workflows/*` 与 `support/*` 的边界。

### 8.2 未来演进方向（保持接口简单）

1. 长任务统一队列化（先内部化，不先扩接口面）。
2. 统一 timing/token/cost 观测格式（Digest、Examine、Interact 对齐）。
3. 事务边界标准化（判卷回写、画像刷新、课程发布等关键链路）。
4. 渐进清理历史兼容字段与别名，继续收敛到 13 号数据库主设计。

---

## 9. 一句话结论

当前架构是"Subject 边界 + Workflow 编排 + 统一构建发布 + 本地优先运行底座"的稳定闭环。  
未来重点是事务边界标准化、观测格式对齐和历史兼容清理，而不是扩散新接口与新表。

### 9.1 规范分层补充说明

- `infra/` 是 `llm_support`、`tracing`、`tools`、`skills`、`prompt_loader` 这类基础模块的规范归属位置；`llm_support/routing.py` 是当前模型路由的唯一推荐入口。
- `utils/` 负责跨层纯工具能力，例如 `path_helpers`、`presenters`、`docgen_store`。
- 不新增顶层 `app/common` 目录；共享 workflow 编排辅助能力统一放在 `shared/infra/workflow`。
- 不再恢复 `services/` 或 `teaching/` 源层；规范导入应直接指向 `app.workflows.*`、`app.shared.infra.*` 与 `app.utils.*`。
