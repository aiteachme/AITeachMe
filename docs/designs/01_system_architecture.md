# 01. 系统架构

## 1. 目标与职责

本文档描述 AITeachMe 当前的系统骨架，重点说明：

- 前端、API、service、workflow、repository、model 各自负责什么
- 五大引擎在整套学习闭环中的位置
- 当前本地优先架构如何落到数据库、向量索引和本地文件系统
- 哪些路径是稳定真相源，哪些仍处于过渡态

---

## 2. 系统总览

AITeachMe 当前不是“前端调一个聊天接口”的轻应用，而是一个以 `Subject` 为工作空间边界的本地优先教学系统。主链路可以概括为：

`RawFile -> Raw Markdown / Assets -> RetrievalChunk -> Knowledge Document / Knowledge Graph -> Teaching Unit / Curriculum -> Chat / Exam / Profile`

按系统分层看，当前主要由五层组成：

1. 前端交互层  
   React 页面、业务组件、API facade、MSW mock。
2. 后端接口层  
   FastAPI 路由、请求 schema、统一响应与异常处理。
3. 后端用例入口层  
   `services/*`，负责 HTTP 触发、参数整理、后台分发、结果封装。
4. 后端工作流编排层  
   `workflows/*`，负责真正的状态推进、节点编排、事件发布和流程失败恢复。
5. 数据与运行时层  
   `repositories/*`、`models/*`、SQLite、sqlite-vec、本地文件系统、外部 LLM / Embedding 服务。

当前后端的编排真相源已经从旧 `agents/*` 迁移到 `workflows/*`。`services/*` 仍然重要，但它们的职责更接近“用例入口”和“触发器”，而不是复杂长流程的最终归宿。

---

## 3. 前端架构

### 3.1 页面主骨架

当前前端位于 `frontend/`，主要页面包括：

- `FilesPage`
- `KnowledgeDocsPage`
- `KnowledgeGraphPage`
- `ChatPage`
- `ExamsPage`
- `ProfilePage`

这些页面对应完整学习闭环：

- `FilesPage`：资料进入系统，并查看解析结果与解析元信息
- `KnowledgeDocsPage`：阅读 AI 整理后的知识文档
- `KnowledgeGraphPage`：查看图谱、主题树、先修图等结构化视图
- `ChatPage`：进行教学型对话
- `ExamsPage`：发起测评与查看试卷
- `ProfilePage`：查看掌握度、复习任务和薄弱点

### 3.2 前端分层方式

当前前端适合继续保持以下分层：

- `src/pages/`
  页面级编排与用户流程入口。
- `src/components/`
  复用组件与业务视图组件。
- `src/api/`
  手写 API facade、生成代码和请求工具。
- `src/mocks/`
  MSW 本地联调层。
- `src/lib/`
  通用工具与页面无关的前端基础逻辑。

### 3.3 前端设计原则

- 页面按学习闭环组织，而不是按零散功能堆积。
- 页面优先承担交互编排，不直接承载复杂知识处理逻辑。
- 页面层必须以真实后端路由为准，而不是以历史生成文件为准。
- 长流程页面统一遵守“触发 + 状态查询 + 结果消费”的交互模式。

---

## 4. 后端架构

### 4.1 后端分层

当前后端位于 `backend/app/`，核心分层如下：

- `api/`
  HTTP 入口、资源分组、参数接收、响应包装。
- `services/`
  业务入口层，负责触发 workflow、读取聚合数据、封装 API 返回。
- `workflows/`
  新的编排中心，负责 LangGraph 图、节点状态流、事件回流与流程失败处理。
- `repositories/`
  数据访问层，负责 SQLModel 查询、批量写入、向量表操作等。
- `models/`
  关系模型定义，包括主业务表、图谱表、课程表、聊天表、assessment 表。
- `schemas/`
  API 请求/响应模型和通用传输结构。
- `core/`
  配置、数据库初始化、日志、LLM、Embedding、异常等基础设施。

### 4.2 路由资源组

当前 `main.py` 注册的主要资源组包括：

- `health`
- `system`
- `auth`
- `subjects`
- `files`
- `knowledge`
- `chats`
- `exams`
- `profile`
- `assessment`

其中：

- `exams` / `profile` 代表旧对外接口路径，当前仍在使用。
- `assessment` 代表新的 assessment/profile 路径，已经落到新表与新 workflow 上。

### 4.3 workflows 的角色

`backend/app/workflows/README.md` 规定了当前工作流编排规范。其核心约束是：

- `services/*` 只做触发、参数整理、持久化适配和返回封装。
- 真正的状态流与节点编排放在 `workflows/*`。
- 各工作流优先保持统一骨架：`graph.py`、`runtime.py`、`state.py`、`events.py`、`exports.py`。

这意味着后续新功能应优先进入已有 workflow，而不是重新在路由或 service 中堆流程逻辑。

---

## 5. 五大引擎在系统中的位置

### 5.1 Ingest

负责接收原始资料、选择解析器、生成 Markdown 与资产目录，并把解析状态写回 `raw_file`。

### 5.2 Digest

负责两类结构化产出：

- 面向用户的知识文档
- 面向系统的知识图谱、Teaching Unit、Theme Tree、Prereq DAG、Curriculum Snapshot

### 5.3 Interact

负责把 `retrieval_chunk`、聊天历史、薄弱点、错题等上下文装配成教学型对话，并通过 SSE 流式返回结果。

### 5.4 Examine

负责测评蓝图、组卷、判卷、答题结果持久化。当前处于双轨期：

- 旧对外接口：`exams_service` + `exam/question/...`
- workflow-backed：`assessment_service` + `workflows/examine/*` + `exam_paper/...`

### 5.5 Profile

负责学习状态沉淀、薄弱分析、复习任务与学习画像。当前同样处于双轨期：

- 旧对外接口：`profile_service` + `user_profile/mistake`
- workflow-backed：`workflows/profile/*` + `user_knowledge_state/review_task`

---

## 6. 页面、资源组与后端主链路

| 页面 | 资源组 | 当前 service | 当前后端主链路 |
| --- | --- | --- | --- |
| `FilesPage` | `files` | `file_service` | `workflows/ingest/*` |
| `KnowledgeDocsPage` | `knowledge` | `knowledge/digest_service` | `workflows/digest/docs/*` |
| `KnowledgeGraphPage` | `knowledge` | `knowledge/graph_query_service`、`knowledge/curriculum_service` | 消费 `workflows/digest/kg/*` 与 `workflows/digest/curriculum/*` 产物 |
| `ChatPage` | `chats` | `chats_service` | `workflows/interact/*` |
| `ExamsPage` | `exams`、`assessment` | `exams_service`、`assessment_service` | 旧 exam API + workflow-backed assessment |
| `ProfilePage` | `profile`、`assessment` | `profile_service`、`assessment_service` | 旧 profile API + workflow-backed mastery/review |

---

## 7. 数据与运行时架构

### 7.1 存储层

当前系统使用三类核心存储：

- SQLite  
  保存主业务数据、作业状态、聊天记录、图谱、课程结构、assessment 数据。
- sqlite-vec  
  保存 `chunk_embeddings`，服务检索与召回。
- 本地文件系统  
  保存原始文件、Markdown、资产、知识文档和调试产物。

### 7.2 长流程模型

当前长流程分三类：

- 文件解析：由 `files` 资源组触发，Ingest workflow 推进
- 知识构建：由 `knowledge` 资源组触发，Digest graph / curriculum / docs workflow 推进
- 新测评链路：由 `assessment` 资源组触发，Examine / Profile workflow 推进

这些长流程都应有稳定持久化锚点，而不是只依赖内存态。当前锚点可能是：

- 最终业务表
- 文件锁 / manifest
- 本地正式产物
- 必要的运行时日志 / workflow state

### 7.3 开发期双写策略

开发阶段采用：

- 数据库保存结构化业务真相
- 本地文件保存正式产物与调试摘要

当前已经存在的本地产物包括：

- `raw_files/`
- `raw_markdowns/`
- `assets/`
- `knowledge_markdowns/`
- `knowledge_markdowns/_build/`

后续新增调试快照统一约定写入：

`data/<subject>/debug/<workflow>/<run_or_job_id>/`

---

## 8. 架构设计原则

### 8.1 本地优先

当前默认运行模式是本地部署，优先追求简单、低依赖、好调试，而不是一开始就做重型分布式架构。

### 8.2 Subject 是顶层工作空间边界

文件、图谱、课程、聊天、测评、画像都按 `Subject` 隔离；数据库查询、本地目录和 API 路径都围绕这个边界组织。

### 8.3 workflows 是复杂业务的编排中心

service 不是最终流程容器，复杂业务要以 workflow 状态流为准。这一点是当前架构和旧设计最大的区别。

### 8.4 知识层与学习者状态层分离

图谱与课程结构描述知识本身；聊天、测评、掌握度、复习任务描述学习者和知识的交互结果。两层通过稳定锚点关联，而不应相互污染。

### 8.5 结构化真相与可调试产物并存

数据库承担结构化真相；本地文件承担原始材料、正式文档和调试摘要。教学系统需要两者同时存在，才能兼顾产品能力和研发可观察性。

### 8.6 语义与证据优先，关键词只做弱提示

章节名、标题路径、主题词、检索词都不应成为各模块的主驱动信号。更合理的主链路应该是：

- 先看语义内容本身
- 再看结构位置、上下文邻接和证据引用
- 最后才把标题、章节名、关键词当作弱提示或导航信息

只有像“第 X 章”“定义”“定理”“证明”这类显式结构锚点，才适合作为较强信号参与流程判断。

---

## 9. 当前开发关注点

### 9.1 文档和生成物仍有历史漂移

当前仍存在旧 OpenAPI 产物、历史前端调用和旧文档口径，因此开发时必须优先核对后端源码。

### 9.2 assessment/profile 仍处于双轨期

旧 exam/profile API 仍在线；新的 assessment/profile 工作流和数据表已经落地。任何新设计都必须显式说明自己面向哪条链路。

### 9.3 本地优先不等于未来不能中心化

当前默认基础设施仍是 SQLite + sqlite-vec + 本地文件系统，但架构边界要为未来切换到 PostgreSQL + pgvector + OSS/MinIO 预留迁移空间。

---

## 10. 总结

AITeachMe 当前已经形成稳定骨架：

- 前端按学习闭环组织页面
- 后端按资源组、service、workflow、repository、model 分层
- 五大引擎围绕同一条教学主链路协作
- SQLite、sqlite-vec 和本地文件系统共同构成运行时底座

后续开发的重点不是另起一套架构，而是继续把这套骨架的边界、状态语义、持久化职责和调试路径写清楚、做扎实。
