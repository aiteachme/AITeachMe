# 01. 系统架构

## 1. 文档定位

本文档只回答当前系统最重要的三件事：

- AITeachMe 现在的主链路到底是什么
- 前端、API、service、workflow、repository、model 各自负责什么
- 本轮 merge 之后，远程 ingest 加速方法和本地数据库重构是如何并到一起的

---

## 2. 系统主链路

当前系统围绕 `Subject` 这个工作空间边界组织，正式主链路可以概括为：

`RawFile -> raw_markdowns / assets -> RetrievalChunk -> KnowledgeDocument + KnowledgeNode/KnowledgeEdge -> TeachingUnit -> Curriculum -> Chat / Exams / Profile`

补充约束：

- Ingest 负责把原始资料变成“可消费材料层”。
- Digest 同时构建知识文档和知识图谱。
- Knowledge Document、Knowledge Graph、Curriculum 在同一轮 digest 中共享同一个构建版号。
- Interact、Examine、Profile 都消费同一套知识层和课程层锚点，而不是各自维护一套平行模型。

---

## 3. 系统分层

### 3.1 前端层

当前主要页面位于 `frontend/src/pages/`：

- `HomePage`
- `FilesPage`
- `KnowledgeDocsPage`
- `KnowledgeGraphPage`
- `ChatPage`
- `ExamsPage`
- `ProfilePage`

前端的职责是：

- 组织学习闭环页面
- 发起 API 请求
- 展示 workflow 推进后的结果

前端不承担复杂的知识处理或构建逻辑。

### 3.2 API 层

`backend/app/api/*` 是对外 HTTP 资源入口，负责：

- 资源分组
- 请求参数接收
- 响应结构封装
- 异常转换

当前正式资源组以这些为主：

- `subjects`
- `files`
- `knowledge`
- `chats`
- `exams`
- `profile`

### 3.3 Service 层

`backend/app/services/*` 是用例入口层，负责：

- 触发 workflow
- 做轻量参数整理
- 读取聚合数据并封装返回

复杂长流程不再堆在 service 中。

### 3.4 Workflow 层

`backend/app/workflows/*` 是真正的编排中心，负责：

- LangGraph 节点与状态流
- 跨节点状态推进
- 事件发布
- 构建失败恢复

这一层是当前复杂业务流程的真相源。

### 3.5 Repository / Model 层

`repositories/*` + `models/*` 负责结构化持久化：

- SQLite 业务表
- sqlite-vec 向量表
- 查询与批量更新

### 3.6 Core 层

`backend/app/core/*` 提供应用基础设施能力：

- 配置（`config.py`）
- 数据库初始化（`database.py`）
- 异常定义（`exceptions.py`）
- 日志（`logger.py`）
- 运行时路径（`runtime_paths.py`）

Core 只包含 5 个纯基础模块，不承载任何 AI 或业务逻辑。

### 3.7 Infra 层

`backend/app/infra/*` 提供 AI 平台引擎能力：

- LLM / Embedding / Model Router
- Agent Loop / Strategies / MCP
- Memory / Search / Skills / Tools
- Context / Checker / Teaching / Events
- Security / Sandbox / Guardrails
- Token Budget / Cache / Prompt Loader / Tracing / Reasoning

它服务五大引擎，但不直接承载业务真相。

### 3.8 Utils 层

`backend/app/utils/*` 提供各层共用的纯工具函数：

- `path_helpers.py`：运行时路径构建（核心路径 helper）
- `presenters.py`：格式化与校验辅助
- `time.py` / `subject.py` / `job_helpers.py` / `kg_helpers.py`

Utils 只依赖 `core/`，可被任何层引用。

### 分层依赖方向

`api → services → workflows → infra → core`，`utils/` 可被任何层横向引用。

---

## 4. 五大引擎的职责

### 4.1 Ingest

Ingest 现在采用“远程分支的方法层 + 本地分支的数据层”合并结果：

- 方法层保留两阶段加速思路
- 数据落点、表结构、目录边界仍按本地重构收敛

当前真实流程：

1. `file_service` 创建 `raw_file`、保存原始文件、排队解析
2. Phase 1 Fast Parse 产出 `raw_markdowns/<file_id>.md`
3. Phase 2 Deep Enhance 在后台做质量重解析和可选 OCR
4. 只有 `ready_for_digest` 的文件才进入 Digest 主链路

### 4.2 Digest

Digest 负责三类正式结果：

- `knowledge_document`
- `knowledge_node / knowledge_edge`
- `curriculum / theme_tree_node / unit_dependency`

当前版本语义已经统一收敛为：

- `curriculum.version_no`
- `knowledge_document.version_no`
- `knowledge_node.build_revision_no`
- `knowledge_edge.build_revision_no`

不再以独立的 `theme_tree_version / prereq_dag_version / curriculum_version` 三套表作为目标态。

### 4.3 Interact

Interact 负责教学型对话，消费：

- `retrieval_chunk`
- `knowledge_document`
- `knowledge_node / knowledge_edge`
- `teaching_unit / curriculum`
- `user.profile_json / subject.profile_json / user_knowledge_state`

### 4.4 Examine

Examine 负责：

- 题模板
- 组卷
- 判卷
- 回写学习状态

正式主线收口到：

- `question_template`
- `exam_paper`
- `exam_paper_item`
- `user_knowledge_state`

### 4.5 Profile

Profile 负责：

- 用户级画像
- 学科级画像
- 细粒度掌握状态

当前主锚点是：

- `user.profile_json`
- `subject.profile_json`
- `user_knowledge_state`

---

## 5. 数据与存储真相

### 5.1 当前默认运行底座

当前默认底座仍然是：

`SQLite + sqlite-vec + 本地文件系统`

### 5.2 Subject 是顶层边界

`Subject` 同时决定：

- API 路由边界
- 本地运行时目录边界
- workflow 的隔离范围

### 5.3 当前数据库主线

当前数据库重构后的主线是“少表、强锚点、字段表达版本”：

- `curriculum` 是课程构建主表
- `theme_tree_node.tree_version_id` 实际指向 `curriculum.id`
- `unit_dependency.dag_version_id` 实际指向 `curriculum.id`
- `raw_file_asset` 不再是目标态业务表，运行时由 `RawFileAsset` 兼容对象和文件系统动态表达

---

## 6. 运行时目录

当前真实目录由 `backend/app/utils/path_helpers.py` 定义：

```text
backend/data/<subject>/
├─ raw_files/
├─ raw_markdowns/
├─ assets/
│  └─ <file_id>/
├─ knowledge_markdowns/
│  └─ _build/
├─ temp/
└─ debug/
```

目录职责：

- `raw_files/`：原始上传文件
- `raw_markdowns/`：ingest 材料层 Markdown
- `assets/<file_id>/`：单文件资产目录
- `knowledge_markdowns/`：已发布知识文档
- `knowledge_markdowns/_build/`：知识文档 staging

---

## 7. 当前关键设计原则

1. 方法层优先复用远程 ingest 加速思路，但不回退本地数据库收敛。
2. 复杂流程以 workflow 为真相，不回流到 route / service 堆逻辑。
3. Subject 是外部模块最稳定的集成边界。
4. 版本优先用字段表达，不先拆一组 history / version 表。
5. 文档必须跟真实目录、真实表语义、真实流程保持一致。

---

## 8. 一句话结论

这次合并后的系统架构可以简单理解为：

- ingest 方法层吸收远程的两阶段加速
- digest / curriculum / exams / profile 继续沿用本地收敛后的数据库主线
- workflow 仍是复杂业务的编排中心
- 当前正式运行底座仍然是本地优先的 SQLite + sqlite-vec + 文件系统
## Canonical Layering Notes

- `core/` remains the minimal foundation layer. Canonical AI runtime modules now live in `infra/`, not in `core/`.
- `infra/` is the canonical home for `llm`, `tracing`, `model_router`, and `prompt_loader`.
- `utils/` is the canonical home for cross-layer pure helpers such as `path_helpers`, `presenters`, and `docgen_store`.
- No new top-level `app/common` layer is introduced. Shared orchestration helpers continue to live under `workflows/common`.
- Cross-layer helper shims are intentionally not retained under `services/`; canonical helper imports should go directly to `app.infra.*` and `app.utils.*`.
