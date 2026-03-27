# AITeachMe 开发设计文档

## 1. 文档定位

`docs/designs/` 用来描述当前项目的工程真相、架构边界和后续演进方向。它回答的是：

- 当前系统分层、数据流和工作流到底长什么样
- 哪些代码目录是真相源，哪些只是生成物或运行时产物
- 五大引擎如何读写数据库、本地文件和向量索引
- 后续从本地优先演进到中心化部署时，哪些边界必须保持稳定

这套文档以当前仓库代码为准，不以历史设计、旧分支、生成文件或过期页面实现为准。

---

## 2. 真相源约定

发生冲突时，优先级如下：

1. `backend/app/api/*`
2. `backend/app/services/*`
3. `backend/app/workflows/*`
4. `backend/app/repositories/*`
5. `backend/app/models/*`
6. `backend/app/schemas/*`
7. `backend/app/core/*`
8. `frontend/src/pages/*`、`frontend/src/components/*`、`frontend/src/api/*`

特别说明：

- `backend/app/workflows/README.md` 是后端工作流编排规范真相源。
- `frontend/openapi.json` 与 `frontend/src/api/generated/*` 是生成产物，不是接口真相源。
- `backend/data/*` 是运行时数据，不是源码。

---

## 3. 当前架构总览

当前项目的主骨架是：

`React 前端 -> FastAPI 资源接口 -> services 触发与编排入口 -> workflows 状态流 -> repositories/models 持久化 -> SQLite + sqlite-vec + 本地文件系统`

系统围绕学习闭环组织，而不是围绕单一聊天能力组织：

`资料接入 -> 知识整理 -> 教学对话 -> 测评诊断 -> 学习状态`

当前后端仍是本地优先架构：

- 关系数据：SQLite
- 向量索引：sqlite-vec
- 原始资料与调试产物：本地文件系统
- 长流程：service 触发 + workflow 编排 + 最终业务表 / 文件产物

---

## 4. 文档目录

| 文档 | 作用 |
| --- | --- |
| `01_system_architecture.md` | 系统分层、资源边界、页面与工作流映射 |
| `02_domain_model_and_state.md` | 领域对象、状态对象、当前新旧模型并存关系 |
| `03_api_contracts_and_dev_workflow.md` | API 契约、统一响应、联调与生成流程 |
| `04_ingest_engine.md` | 资料接入、解析、材料化、解析产物边界 |
| `05_digest_engine.md` | Digest 总控文档：统一编排、质量门控、发布语义与速度/质量分层 |
| `05a_digest_knowledge_document.md` | 知识文档设计：讲义模式、章节蓝图、文档包与教学审校 |
| `05b_digest_knowledge_graph.md` | 知识图谱设计：主题图谱、依赖关系、curriculum 信号与影响域 |
| `06_interact_engine.md` | 教学对话、检索、流式输出、引用来源 |
| `07_examine_engine.md` | 测评蓝图、组卷、判卷、试卷快照与状态回流 |
| `08_profile_engine.md` | 用户级画像、学科级画像、掌握度与复习调度 |
| `09_ai_stack_and_refactor_guide.md` | AI 技术栈、工程化方法与重构指导 |
| `10_repo_structure_and_runtime_files.md` | 仓库目录、生成物、运行时目录与本地文件布局 |
| `11_database_and_storage_architecture.md` | 本地部署、中心化部署、存储抽象、URI 统一与向量实现 |
| `12_api_refactor_plan.md` | API 接口收敛、全量返回、知识图谱三 Tab 接口重构计划 |
| `13_database_schema_inventory.md` | 数据库唯一主文档：目标主树、目标表职责、profile 分层、收敛映射、重构边界 |

---

## 5. 推荐阅读顺序

### 5.1 新加入项目的开发者

1. `01_system_architecture.md`
2. `10_repo_structure_and_runtime_files.md`
3. `13_database_schema_inventory.md`
4. `11_database_and_storage_architecture.md`
5. `02_domain_model_and_state.md`
6. `03_api_contracts_and_dev_workflow.md`
7. `05_digest_engine.md`
8. `05a_digest_knowledge_document.md`
9. `05b_digest_knowledge_graph.md`
10. 再进入对应引擎文档

### 5.2 后端开发

1. `01_system_architecture.md`
2. `13_database_schema_inventory.md`
3. `11_database_and_storage_architecture.md`
4. `02_domain_model_and_state.md`
5. `10_repo_structure_and_runtime_files.md`
6. `03_api_contracts_and_dev_workflow.md`
7. `05_digest_engine.md`
8. `05a_digest_knowledge_document.md`
9. `05b_digest_knowledge_graph.md`
10. `04` 到 `09`

### 5.3 前端开发

1. `01_system_architecture.md`
2. `03_api_contracts_and_dev_workflow.md`
3. `10_repo_structure_and_runtime_files.md`
4. `05_digest_engine.md`
5. `05a_digest_knowledge_document.md`
6. `05b_digest_knowledge_graph.md`
7. `06_interact_engine.md`
8. `07_examine_engine.md`
9. `08_profile_engine.md`

---

## 6. 页面、资源组与工作流映射

| 前端页面 | 主要资源组 | 当前主要 service | 当前主要 workflow / 后端主链路 |
| --- | --- | --- | --- |
| `UploadPage` | `files` | `file_service` | `workflows/ingest/*` |
| `KnowledgeDocsPage` | `knowledge` | `knowledge/digest_service`、`knowledge/curriculum_service` | `workflows/digest/docs/*`、`workflows/digest/kg/*`、`workflows/digest/curriculum/*` |
| `SummaryPage` | `knowledge` | `knowledge/graph_query_service`、`knowledge/curriculum_service` | 消费 digest 产出的图谱与课程版本 |
| `ChatPage` | `chats` | `chats_service` | `workflows/interact/*` |
| `ExamPage` | `exams` | `exams_service` | `workflows/examine/*` |
| `AnalysisPage` | `profile` | `profile_service` | `workflows/profile/*` |

其中 `exams/profile` 仍是当前对外可用接口的一部分，但数据库目标设计已经明确要向 `exam_paper / exam_paper_item / user.profile_json / subject.profile_json / user_knowledge_state` 这条压缩主线收敛。

---

## 7. 当前开发最重要的约束

- 后端路由、schema、workflow 才是接口和状态真相源。
- `services/*` 负责触发与结果封装，复杂业务流程以 `workflows/*` 为主编排中心。
- 项目当前是本地优先架构，SQLite、本地文件与 sqlite-vec 仍是默认基础设施。
- 数据库主设计以 [13_database_schema_inventory.md](./13_database_schema_inventory.md) 为唯一真相源。
- 部署与存储设计以 [11_database_and_storage_architecture.md](./11_database_and_storage_architecture.md) 为唯一真相源。

---

## 8. 文档写作约定

- 先写职责边界，再写当前实现落点。
- 先写数据与状态，再写技术手段。
- 只在必要时列文件，优先讲行为与边界。
- 涉及数据库和本地文件时，优先写清“写到哪里、谁负责写、什么时候写”。
- 涉及 workflow 时，优先写清节点顺序和节点持久化责任。

---

## 9. 一句话总纲

这套文档的目标不是复述代码，而是把当前 AITeachMe 的工程真相讲清楚：前端如何触发学习流程，后端如何用 workflows 编排五大引擎，数据库主树应该如何收敛，存储层如何支持本地与中心化部署，以及未来如何在不引入新垃圾层的前提下继续演进。
