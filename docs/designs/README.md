# AITeachMe 开发设计文档

## 1. 文档定位
当前目录是一套面向开发的设计文档，用来回答三个问题：

- 这个项目的系统边界、核心模型和五大引擎分别是什么
- 前端、后端、Agent、数据层应该如何协同设计
- 后续开发时，哪些地方应当保持稳定，哪些地方适合扩展能力

本文档集只讨论工程设计、接口规范、AI 方案、开发方法，不包含商业、融资、定价、增长等敏感内容。

---

## 2. 使用原则

### 2.1 当前代码是实现真相源

文档必须和当前代码兼容。遇到以下内容冲突时，以代码为准：

- `backend/app/api/*`
- `backend/app/services/*`
- `backend/app/models/*`
- `backend/app/agents/*`
- `frontend/src/pages/*`
- `frontend/src/components/*`

### 2.2 设计文档不等于代码搬运

文档不追求逐行复述代码，而是要稳定说明：

- 模块职责
- 设计边界
- 数据流
- 适合采用的方法
- 可结合的技术
- 开发时应优先遵守的规范

### 2.3 五大引擎文档以设计方法为主

五大引擎文档重点讲：

- 这个引擎要解决什么问题
- 应该如何设计
- 典型 Pipeline 如何拆步骤
- 每个关键子模块的输入与输出是什么
- 适合使用哪些技术方法
- 可以继续长出哪些能力

具体接口定义集中放在 `03_api_contracts_and_dev_workflow.md`，引擎文档只保留必要的实现落点说明。

---

## 3. 文档目录

| 文档 | 作用 |
| --- | --- |
| `01_system_architecture.md` | 系统总览、前后端分层、五大引擎在整体架构中的位置 |
| `02_domain_model_and_state.md` | 领域模型、关键状态、对象关系、存储边界 |
| `03_api_contracts_and_dev_workflow.md` | 接口设计规范、统一响应规范、长流程规范、联调流程 |
| `04_ingest_engine.md` | Ingest 引擎设计：多格式资料接入、解析、规范化、材料化 |
| `05_digest_engine.md` | Digest 引擎设计：知识图谱、Teaching Unit、课程视图、证据链 |
| `06_interact_engine.md` | Interact 引擎设计：教学对话、RAG、上下文装配、流式输出 |
| `07_examine_engine.md` | Examine 引擎设计：出题、判卷、诊断、错题回流 |
| `08_profile_engine.md` | Profile 引擎设计：掌握度、报告、错题本、学习状态层 |
| `09_ai_stack_and_refactor_guide.md` | AI 技术栈、应用方法、评测与工程化方向 |

---

## 4. 推荐阅读顺序

### 4.1 新加入项目的开发者

1. `01_system_architecture.md`
2. `02_domain_model_and_state.md`
3. `03_api_contracts_and_dev_workflow.md`
4. 再按职责进入对应引擎文档

### 4.2 后端开发

1. `01_system_architecture.md`
2. `02_domain_model_and_state.md`
3. `03_api_contracts_and_dev_workflow.md`
4. `04` 到 `09`

### 4.3 前端开发

1. `01_system_architecture.md`
2. `03_api_contracts_and_dev_workflow.md`
3. `05_digest_engine.md`
4. `06_interact_engine.md`
5. `07_examine_engine.md`
6. `08_profile_engine.md`

---

## 5. 页面、引擎、实现落点

| 前端页面 | 主要引擎 | 后端资源组 | 主要服务与 Agent |
| --- | --- | --- | --- |
| `UploadPage` | Ingest | `files` | `file_service` + `agents/ingest/*` |
| `SummaryPage` | Digest | `knowledge` | `digest_service` / `curriculum_service` / `graph_query_service` + `agents/digest/*` |
| `ChatPage` | Interact | `chats` | `chats_service` + `agents/interact/*` |
| `ExamPage` | Examine | `exams` | `exams_service` + `agents/examine/*` |
| `AnalysisPage` | Profile | `profile` | `profile_service` + `agents/profile/*` |

这五个页面不是松散功能点，而是围绕同一条学习闭环展开：

`资料接入 -> 知识组织 -> 教学互动 -> 诊断测评 -> 学习画像`

---

## 6. 文档写作约定

为了让这套文档长期可维护，后续新增内容建议遵守以下写法：

- 先写职责，再写实现落点
- 先写稳定原则，再写可选技术
- 先写设计方法，再写当前开发注意点
- 少写历史迁移叙事，多写当前可执行的方法和边界

---

## 7. 当前开发最重要的约束

- 后端源码是接口真相源，`frontend/openapi.json` 和 `frontend/src/api/generated/*` 目前只能视为生成产物
- 当前业务接口以 `POST` 为主，聊天流式输出采用 `POST + SSE`
- 文件解析和知识构建属于长流程，设计上应保持“触发 + 状态查询 + 后台执行”的统一模式
- 项目是本地优先架构，SQLite、本地文件系统和 sqlite-vec 是当前重要基础设施
- 前端仍存在手写调用、生成调用、MSW mock 并存的问题，开发时必须先确认真实后端口径

---

## 8. 一句话总纲

这套文档的目标不是复述代码，而是把 AITeachMe 的开发设计讲清楚：系统如何分层、五大引擎如何协作、接口如何规范、AI 技术如何落地，以及后续开发应当沿着什么方法继续推进。
