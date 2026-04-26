# 02. 领域模型与状态

## 1. 文档目标

本文档用于明确：

- 哪些是当前系统真正稳定的业务对象
- 哪些只是 workflow 运行时状态
- 哪些旧名字只是兼容别名，不再代表独立主表

---

## 2. 当前稳定业务对象

### 2.1 工作空间层

- `User`
- `Subject`

说明：

- `User` 负责用户级身份与跨学科画像
- `Subject` 负责学科级工作空间与隔离边界

### 2.2 材料层

- `RawFile`
- `RetrievalChunk`

说明：

- `RawFile` 表达“资料已经进入系统且可追踪”
- `RetrievalChunk` 是下游检索和消费的统一切片对象

`RawFile` 当前同时承担了远程 ingest 兼容字段映射，例如：

- `original_filename`
- `file_ext`
- `storage_key`
- `parsed_markdown`

这些是兼容接口，不代表我们重新回到旧 schema。

### 2.3 知识层

- `KnowledgeDocument`
- `KnowledgeUnit`
- `KnowledgeEdge`

说明：

- `KnowledgeDocument` 负责对外阅读与章节包元数据
- `KnowledgeUnit / KnowledgeEdge` 负责系统内部知识真相
- 历史文档中的 `KnowledgeNode` 对应当前物理表和 API 里的 `KnowledgeUnit`

### 2.4 未来课程层（当前未落地）

- `TeachingUnit`
- `TaxonomyAnchor`
- `Curriculum`
- `ThemeTreeNode`
- `UnitDependency`

说明：

- 这些不是当前数据库表，也不是当前公开 API 契约
- 后续如果 Examine/Profile 需要教学单元、课程版本或主题树，需要另起 schema 设计和迁移
- 当前主链路先以 `knowledge_document + knowledge_unit + knowledge_edge` 为 Digest 产物

### 2.5 交互与评测层

- `ChatSession`
- `ChatMessage`
- `QuestionTemplate`
- `ExamPaper`
- `ExamPaperItem`
- `UserKnowledgeState`

说明：

- 聊天层消费知识层，不反向定义知识真相
- Examine 与 Profile 当前主要共享 `KnowledgeUnit` 这些知识锚点

---

## 3. 当前兼容别名与过渡对象

### 3.1 兼容别名

当前代码里仍可能出现旧术语，但它们不代表独立主表：

- `KnowledgeNode`：历史术语，当前以 `KnowledgeUnit` 为准。
- `CurriculumSnapshot / CurriculumVersion / ThemeTreeVersion / PrereqDagVersion`：未来课程结构占位术语，当前不落表。

### 3.2 文件资产兼容对象

`RawFileAsset` 当前是兼容对象，不是目标态业务主表。

它主要用于：

- 远程 ingest / file service 的接口兼容
- 运行时按 `asset_dir` 动态组装资产信息

### 3.3 已被收敛的旧概念

下面这些不再是目标态长期业务对象：

- `raw_file_asset` 独立主表
- `curriculum_version` 独立主表
- `theme_tree_version` 独立主表
- `prereq_dag_version` 独立主表
- `DocGenJob` 之类的知识文档长期 job 表
- `assessment.py` 那套旧考试模型

---

## 4. 运行时状态对象

下面这些是运行时状态，而不是长期业务协议：

- workflow `State` TypedDict
- `graph_job_id`
- `build_session_id`
- ingest 事件与 digest 事件 payload
- `knowledge_markdowns/_build/`
- `.build.lock`
- `debug/` 快照

它们的职责是：

- 串 workflow 节点
- 做失败恢复
- 支持调试观察

它们不应该外溢成新的核心业务表。

---

## 5. 版本与状态语义

### 5.1 当前版本语义

当前系统采用“文档版本 + 图谱修订”的轻量语义：

- `knowledge_document.version_no`
- `knowledge_unit.build_revision_no`
- `knowledge_edge.build_revision_no`

`curriculum.version_no` 当前不存在。图谱构建运行态会通过 `graph_metrics.revision_no` 和
`graph_metrics.last_synced_doc_version_no` 记录图谱修订与被同步的知识文档版本。

### 5.2 当前 ingest 状态语义

Ingest 主状态为：

- `pending`
- `classifying`
- `fast_parsing`
- `fast_parsed`
- `enhancing`
- `ready_for_digest`
- `enhance_failed`
- `failed`

这里的状态属于 `RawFile` 生命周期，不是独立任务表。

---

## 6. 数据库与文件系统分工

### 6.1 数据库存什么

数据库负责：

- 工作空间实体
- 材料元数据
- 知识图谱与课程结构
- 聊天与考试结构化数据
- 学习状态

### 6.2 文件系统存什么

文件系统负责：

- 原始二进制文件
- 材料层 Markdown
- 单文件资产目录
- 已发布知识文档正文
- staging 与 debug 产物

### 6.3 当前目录真相

当前运行时目录真相是：

- `raw_files/`
- `raw_markdowns/`
- `assets/<file_id>/`
- `knowledge_markdowns/`

---

## 7. 一句话结论

当前领域模型的核心目标不是“再引入更多中间对象”，而是：

- 用少量稳定主对象支撑五大引擎
- 用 workflow state 承载运行时复杂性
- 用兼容别名平滑过渡旧调用
- 不再把历史版本表和旧考试模型继续扩散
