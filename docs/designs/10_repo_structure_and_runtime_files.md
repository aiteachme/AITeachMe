# 10. 仓库结构与运行时文件布局

## 1. 目标与适用范围

本文档用于补齐 `docs/designs` 中“代码仓库怎么组织、运行时文件放在哪里、哪些文件能直接改、哪些文件只是生成物”的说明空缺，重点回答：

- 仓库顶层目录分别承担什么职责
- 前端和后端分别如何分层
- 运行时数据、生成产物和源码真相源分别放在哪里
- 用户上传资料后，会在磁盘和数据库中生成哪些内容

这篇文档不追求逐文件罗列，也不替代源码本身。遇到实现细节与文档不一致时，仍以当前代码为准，尤其是以下目录：

- `frontend/src/*`
- `backend/app/*`
- `backend/scripts/*`
- `backend/data/*`

---

## 2. 从宏观看仓库

AITeachMe 当前采用“前后端分仓式同仓库组织 + 本地优先运行时目录”的结构。可以把整个仓库粗略看成四层：

1. 产品与应用层  
   `frontend/` 与 `backend/`，承载真实业务能力。
2. 设计与知识层  
   `docs/`，承载架构、接口、引擎设计和开发方法。
3. 工具与支撑层  
   `scripts/`、`configs/`、`infra/`、`datasets/`、`models/`，承载脚本、配置、部署和实验性辅助内容。
4. 运行时数据层  
   默认位于 `backend/data/`，承载数据库、本地资料文件、Markdown 产物和解析资源。

这种组织方式的核心价值，不是把所有内容都塞进一个应用目录，而是明确区分：

- 哪些是要提交到仓库、长期维护的源码和设计资产
- 哪些是开发、构建、联调时才会生成的派生产物
- 哪些是运行过程中落地到本地磁盘的业务数据

---

## 3. 仓库顶层目录说明

### 3.1 核心应用目录

- `frontend/`
  React 前端工程，负责页面、组件、前端 API 调用、联调 mock 和构建产物。
- `backend/`
  FastAPI 后端工程，负责接口、业务编排、AI 能力、数据库与运行时数据。
- `docs/`
  面向开发的设计文档与说明材料，当前 `docs/designs/` 是主设计文档集合。

### 3.2 工具与支撑目录

- `scripts/`
  仓库级脚本入口，适合放跨前后端的辅助命令、自动化任务或工具脚本。
- `configs/`
  预留给集中式配置说明或模板，不应承载运行时业务数据。
- `infra/`
  基础设施与部署相关内容，当前更接近运维或工程化支撑区。
- `datasets/`
  预留给样例数据、实验数据或训练/验证材料，不属于正式业务运行时数据。
- `models/`
  预留给模型相关说明或外部模型资源组织，不等于后端 `backend/app/models/`。

### 3.3 设计原则

- 业务代码优先落在 `frontend/` 与 `backend/`
- 设计说明优先落在 `docs/designs/`
- 运行时数据不要写回源码目录，而应进入 `backend/data/`
- 顶层支撑目录可以扩展，但应避免与前后端应用边界混淆

---

## 4. 前端架构与目录职责

### 4.1 前端在系统里的角色

前端不是一个单纯的“聊天壳子”，而是学习闭环的交互入口。当前主要页面对应五大引擎：

- `UploadPage` 对应 Ingest
- `SummaryPage` 对应 Digest
- `ChatPage` 对应 Interact
- `ExamPage` 对应 Examine
- `AnalysisPage` 对应 Profile

因此，前端架构的重点不是堆很多零散页面，而是把“资料接入 -> 知识查看 -> 教学互动 -> 诊断测评 -> 学习画像”组织成连续体验。

### 4.2 `frontend/src/` 的主要目录

- `src/pages/`
  页面级入口与路由落点。这里更偏“用户流程编排”，不宜堆太多底层细节。
- `src/components/`
  可复用组件层。通常可以继续区分：
  - 通用 UI 组件
  - 贴近业务语义的复杂组件，例如图谱视图、主题树、证据弹窗
- `src/api/`
  前端请求层。这里同时容纳手写封装和生成代码，是前端与后端接口的连接区。
- `src/mocks/`
  MSW mock 与联调辅助层，只用于开发和验证，不应被误认为后端真相源。
- `src/lib/`
  前端通用工具和辅助方法。

### 4.3 前端目录中哪些是源码，哪些是生成物

- 真正可维护的前端源码主要是：
  - `src/pages/*`
  - `src/components/*`
  - `src/api/client.ts`
  - `src/api/graphApi.ts`
  - `src/lib/*`
  - `src/mocks/*`
- 派生产物主要包括：
  - `frontend/openapi.json`
  - `frontend/src/api/generated/*`
  - `frontend/dist/`

这里最重要的一条边界是：

- `frontend/openapi.json` 与 `frontend/src/api/generated/*` 是根据后端接口导出的派生产物，不是接口真相源
- `dist/` 是构建产物，只服务于部署或静态预览，不参与设计真相

换句话说，前端如果发现接口定义有问题，首先应该回到后端 `api/` 与 `schemas/`，而不是把生成物当作真实规范去修。

---

## 5. 后端架构与目录职责

### 5.1 后端在系统里的角色

后端是当前系统的业务中枢，负责三件事：

- 提供稳定的资源型 API 与长流程接口
- 把业务流程、AI 能力和数据持久化编排成完整用例
- 管理本地运行时数据，包括结构化数据库和文件系统资产

当前技术骨架是 `FastAPI + SQLModel + SQLite + sqlite-vec + 本地文件系统 + Agent 工作流`。

### 5.2 `backend/app/` 的主要目录

- `app/api/`
  路由入口层。负责 HTTP 资源分组、请求参数接收、统一响应包装和异常映射。
- `app/services/`
  业务编排层。负责把上传、解析、检索、图谱构建、考试回流等步骤串成完整业务流程。
- `app/repositories/`
  数据访问层。负责操作 SQLModel、原生 SQL 和部分检索相关查询。
- `app/agents/`
  AI 能力层。负责 Ingest、Digest、Interact、Examine、Profile 等引擎内部的实际能力实现。
- `app/models/`
  持久化领域模型。这里定义的是 SQLite 中的核心表结构和业务对象。
- `app/schemas/`
  API 请求、响应和公共传输结构。
- `app/core/`
  基础设施层。负责配置、数据库初始化、日志、LLM、Embedding、异常等。
- `app/utils/`
  辅助函数和公共工具。

### 5.3 后端其他重要目录

- `backend/scripts/`
  后端工程脚本，例如导出 OpenAPI、辅助开发和验证。
- `backend/playground/`
  手工实验、局部验证和样例输入输出区域。它属于验证区，不属于正式业务路径。
- `backend/docs/`
  后端局部说明文档，和仓库级 `docs/` 形成互补。

### 5.4 后端分层的核心边界

- `api` 负责“接口边界”
- `services` 负责“用例编排”
- `agents` 负责“AI 和知识处理能力”
- `repositories` 负责“持久化读写”
- `models` 负责“结构化业务对象”
- `core` 负责“全局基础设施”

如果后续继续扩展功能，通常应优先把新能力放进已有分层，而不是直接在 `api` 里堆复杂逻辑，或把业务流程散落到多个脚本中。

---

## 6. 数据与运行时文件布局

### 6.1 `backend/data/` 是什么

`backend/data/` 是当前项目默认的运行时数据根目录。它不是源码目录，也不是设计文档目录，而是应用运行后产生的本地业务数据区。

当前本地开发约定下：

- `backend/.env` 中的 `DATA_DIR` 默认是 `./data`
- 后端通常从 `backend/` 目录启动
- 因此默认运行时数据会落到 `backend/data/`

如果未来修改了 `DATA_DIR`，实际路径可以变化，但“运行时数据与源码分离”的原则建议继续保持。

### 6.2 `backend/data/aiteachme.db`

`aiteachme.db` 是当前系统的本地结构化业务库，不是缓存。它主要保存：

- 学科空间
- 上传文件元数据
- `Document` 与 `DocumentChunk`
- 知识图谱结构与构建任务
- Theme Tree、Prereq DAG、Curriculum Snapshot
- 聊天记录、考试记录、画像数据

它的角色更像“本地总库”而不是“临时状态桶”。如果需要重置整个本地业务状态，删除它往往会带来显著影响。

### 6.3 `chunk_embeddings`

`sqlite-vec` 的 `chunk_embeddings` 虚拟表属于检索层运行时数据。它与 `DocumentChunk` 形成一一对应的向量索引关系，主要服务于：

- RAG 检索
- 语义相似度召回
- 后续可能的局部知识发现与聚类

它仍然属于运行时数据的一部分，但语义上更偏“检索基础设施”，不是面向产品直接展示的业务对象。

### 6.4 为什么运行时文件按学科分目录

`Subject` 是当前系统的顶层工作空间边界。文件、图谱、聊天、考试、画像都按学科隔离，因此本地运行时文件也自然按学科分目录。

当前代码里的路径辅助逻辑，会在 `backend/data/<subject>/` 下继续拆成多个子目录。

### 6.5 `backend/data/<subject>/` 的目录结构

每个学科目录通常包含：

- `raw/`
  原始上传文件。这里保存用户最初上传的 PDF、DOCX、PPTX 等资料。
- `markdown/`
  Ingest 解析后得到的 Markdown 产物。它是原始资料转成可继续处理材料后的关键中间层。
- `assets/`
  解析时提取出的图片、附件或其他资源。Markdown 中通常会引用这里的文件。
- `temp/`
  临时处理目录。适合放解析或转换过程中产生的短生命周期文件。

这几个目录的典型职责是：

- `raw` 保存原件
- `markdown` 保存标准化文本材料
- `assets` 保存伴随资源
- `temp` 保存短期中间产物

### 6.6 哪些运行时文件可以删除，哪些要谨慎

- `temp/` 通常可以视为可重建目录
- `markdown/` 与 `assets/` 在重新解析资料后通常可以重建，但删除前要确认不会影响当前调试状态
- `aiteachme.db` 是核心业务状态库，删除会重置大量结构化数据
- 整个 `backend/data/<subject>/` 删除，通常意味着该学科的本地运行状态被整体清空

开发阶段可以更激进地重建本地数据，但仍建议先明确“要重置的是单个学科、单条资料，还是整个工作区”。

---

## 7. 真相源、生成物与运行时产物

为了避免开发时改错地方，建议始终先判断一个文件属于哪一类。

### 7.1 真相源

真相源是应该被直接维护、并决定系统实际行为的内容，当前主要包括：

- 后端源码
  - `backend/app/api/*`
  - `backend/app/services/*`
  - `backend/app/repositories/*`
  - `backend/app/agents/*`
  - `backend/app/models/*`
  - `backend/app/schemas/*`
  - `backend/app/core/*`
- 前端源码
  - `frontend/src/pages/*`
  - `frontend/src/components/*`
  - `frontend/src/api/client.ts`
  - `frontend/src/api/graphApi.ts`
  - `frontend/src/lib/*`
  - `frontend/src/mocks/*`
- 设计文档
  - `docs/designs/*`

### 7.2 生成物

生成物是根据真相源导出的内容，通常不应被当作首要修改入口：

- `frontend/openapi.json`
- `frontend/src/api/generated/*`
- `frontend/dist/`

如果这些文件与真实实现冲突，优先修真相源，再重新生成。

### 7.3 运行时产物

运行时产物是应用启动、联调或处理资料过程中产生的数据：

- `backend/data/aiteachme.db`
- `backend/data/<subject>/raw/*`
- `backend/data/<subject>/markdown/*`
- `backend/data/<subject>/assets/*`
- `backend/data/<subject>/temp/*`

它们属于“本地工作区状态”，不是设计文档，也不是接口规范。

---

## 8. 三条典型生成链路

### 8.1 用户上传文件后

当用户在前端上传资料后，系统通常会发生两类落地：

1. 数据库新增 `RawFile` 记录  
   记录文件名、文件类型、所属 `Subject`、原始文件路径、状态等元数据。
2. 磁盘写入原始文件  
   文件通常会进入 `backend/data/<subject>/raw/`。

此时系统已经知道“有这份资料”，但还不代表它已经变成可被知识处理消费的标准材料。

### 8.2 Ingest 完成后

当 Ingest 完成一次成功解析后，通常会新增或更新：

- 磁盘侧
  - `backend/data/<subject>/markdown/<raw_file_id>.md`
  - `backend/data/<subject>/assets/<raw_file_id>/...`
- 数据库侧
  - `raw_file.markdown_path`
  - `raw_file.asset_dir`
  - 解析状态与质量元数据
  - `Document`
  - `DocumentChunk`
  - `chunk_embeddings`

这一步的本质，是把原始资料转换成后续 Digest、Interact 都能消费的“标准化学习材料层”。

### 8.3 Digest 构建后

当 Digest 对某个学科构建知识结构后，数据库中通常会新增或更新：

- `GraphDigestJob`
- `KnowledgeNode`
- `KnowledgeEdge`
- `KnowledgeRevision`
- `EdgeRevision`
- `EvidenceLink`
- `CurriculumDeriveJob`
- `TeachingUnit`
- `ThemeTreeVersion` / `ThemeTreeNode`
- `PrereqDagVersion` / `UnitDependency`
- `CurriculumSnapshot`

这一步通常不再强调磁盘新文件，而是把材料层进一步组织成“知识层”和“教学层”的结构化对象。

---

## 9. 如何理解“项目架构”

如果只用一句话来概括当前项目架构，可以这样理解：

AITeachMe 不是“前端调一个聊天接口”的简单应用，而是一个以 `Subject` 为工作空间、以 `DocumentChunk` 为材料桥接层、以 Digest 组织知识和课程结构、再由 Interact / Examine / Profile 消费这些结构的本地优先教学系统。

因此，架构上最值得长期保持的几条主线是：

- 前端按学习闭环组织，而不是按零散功能堆积
- 后端按接口、编排、能力、持久化分层
- `Subject` 始终是顶层工作空间边界
- `Document` / `DocumentChunk` 是 Ingest 与下游能力之间的重要桥接层
- 运行时数据进入 `backend/data/`，不污染源码目录

---

## 10. 后续扩展约定

为了让这份文档和仓库结构都能继续扩展，而不是越写越死板，后续建议遵守以下约定。

### 10.1 新增前端页面时

- 优先放入 `frontend/src/pages/`
- 页面只承载用户流程和页面级编排
- 复杂业务视图优先拆入 `components/`
- 如果页面对应五大引擎中的某一环，优先复用现有资源组与 API 边界

### 10.2 新增后端能力时

- 新接口优先进入 `app/api/` 下已有资源组
- 新业务流程优先进入 `app/services/`
- 新 AI / 知识处理能力优先进入 `app/agents/`
- 新持久化结构优先进入 `app/models/` 与 `app/repositories/`
- 不建议把长流程逻辑直接堆在路由函数里

### 10.3 新增生成物时

- 如果它来自后端接口导出或代码生成，应明确标注为派生产物
- 如果它来自前端构建，应放入构建目录，不回写源码目录
- 如果生成链路重要，建议在对应文档中补一小段说明，而不是只让读者猜

### 10.4 新增运行时文件时

- 优先考虑放入 `backend/data/<subject>/...`，保持学科隔离
- 只有明确属于全局基础设施的数据，才放入 `backend/data/` 根下
- 一旦新增新的运行时文件类型，建议同时补充这篇文档中的对应目录说明

这样做的好处是，仓库结构可以继续生长，但不会失去“源码、生成物、运行时数据”三者之间的边界感。

---

## 11. 总结

这篇文档补的不是某个具体引擎的实现细节，而是整个项目的“地图”：

- 哪些目录负责产品能力
- 哪些目录负责设计与支撑
- 哪些文件是源码真相源
- 哪些文件是生成物
- 哪些路径承载运行时数据
- 一份资料进入系统后，会在数据库和本地磁盘上留下什么痕迹

只要这张地图是清晰的，后续无论继续扩展 Ingest、Digest，还是重构前后端协作方式，团队都会更容易判断“应该改哪里、不要改哪里、生成的文件应该放哪里”。
