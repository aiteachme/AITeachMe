# 01. 系统架构

## 1. 文档定位

本文档只回答当前系统最核心的三个问题：

- AITeachMe 当前主链路怎么走；
- 前端、API、service、workflow、repository、model 的职责边界是什么；
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

### 3.3 Service 层（用例入口）

`backend/app/services/*` 负责：

- 用例级编排入口；
- 事务边界与锁控制；
- workflow 调用和响应对象封装。

当前是 `services + workflows` 混合编排：复杂链路大头在 workflows，但 service 仍承载事务与聚合逻辑。

### 3.4 Workflow 层（五大引擎编排中心）

`backend/app/workflows/*` 负责：

- LangGraph 状态推进；
- 节点并发与降级策略；
- 事件发布、失败恢复、观测摘要。

这是当前复杂业务流程的第一真相源。

### 3.5 Repository / Model 层

`repositories/* + models/*` 负责结构化持久化：

- 业务表读写；
- 批量查询与更新；
- 兼容字段映射。

### 3.6 Core / Infra / Utils

- `core/*`：配置、数据库初始化、日志、异常、应用级后台任务注册器。
- `infra/*`：LLM、memory、search、tools、checker、teaching、guardrails 等 AI 基础能力。
- `utils/*`：路径、展示、时间等跨层纯工具（如 `path_helpers`、`docgen_store`）。

---

## 4. 分层依赖方向

推荐依赖方向：

`api -> services -> workflows -> infra -> core`

补充：

- `repositories/models` 为持久化支撑层，主要被 services/workflows 消费；
- `utils` 为横切纯工具层，可被上层调用；
- 当前工程里存在少量历史兼容调用，重构时优先向上述方向收敛。

---

## 5. 五大引擎当前落地

### 5.1 Ingest（透视引擎）

- 入口：`services/file_service.py` + `workflows/ingest/runtime.py`
- 核心：两阶段解析（Fast Parse + Deep Enhance）
- 产物：`raw_files/`、`raw_markdowns/`、`assets/`、`raw_file` 元数据

### 5.2 Digest（织网引擎）

- 入口：`services/knowledge/digest_service.py` + `workflows/digest/unified/runtime.py`
- 核心：shared prepare、doc/kg 并行、consistency、repair、curriculum、统一发布
- 产物：`knowledge_document`、`knowledge_node/edge`、`curriculum/theme_tree_node/unit_dependency`

### 5.3 Interact（伴读引擎）

- 入口：`api/chats.py`（`POST + SSE`）+ `workflows/interact/runtime.py`
- 核心：history/retrieval/strategy/prompt/stream/persist 节点链路
- 产物：`chat_session`、`chat_message`、可追踪 contexts

### 5.4 Examine（诊断引擎）

- 入口：`services/exams_service.py` + `workflows/examine/*`
- 核心：风格画像、题模板生成、组卷、判卷、回写 profile
- 产物：`question_template`、`exam_paper`、`exam_paper_item`

### 5.5 Profile（显影引擎）

- 入口：`services/profile_service.py` + `workflows/profile/*`
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
- `knowledge/build` 触发后台 unified digest；
- 进程关闭时统一取消与回收。

这让“长流程执行”与“HTTP 接口返回”解耦，但没有新增复杂 job API 面。

---

## 8. 当前架构边界与未来演进

### 8.1 当前边界

1. exam 生成/判卷仍是同步 HTTP 触发。
2. observability 已有 runtime summary，但未统一对外 API 暴露。
3. services 与 workflows 仍是混合编排，不是纯 workflow 化。

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

- `core/` 仍然保持为最小基础层，规范的 AI 运行时模块统一放在 `infra/`，不再回落到 `core/`。
- `infra/` 是 `llm_support`、`tracing`、`tools`、`skills`、`prompt_loader` 这类基础模块的规范归属位置；`llm_support/routing.py` 是当前模型路由的唯一推荐入口。
- `utils/` 负责跨层纯工具能力，例如 `path_helpers`、`presenters`、`docgen_store`。
- 不新增顶层 `app/common` 目录；共享 workflow 编排辅助能力统一放在 `shared/infra/workflow`。
- 不再在 `services/` 下保留跨层 helper shim；规范导入应直接指向 `app.shared.infra.*` 与 `app.utils.*`。
