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
- `KnowledgeNode`
- `KnowledgeEdge`

说明：

- `KnowledgeDocument` 负责对外阅读与章节包元数据
- `KnowledgeNode / KnowledgeEdge` 负责系统内部知识真相

### 2.4 课程层

- `TeachingUnit`
- `TaxonomyAnchor`
- `Curriculum`
- `ThemeTreeNode`
- `UnitDependency`

说明：

- `TeachingUnit` 是 digest / examine / profile 共同消费的稳定锚点
- `Curriculum` 是课程构建主表
- `ThemeTreeNode` 和 `UnitDependency` 直接挂在当前课程快照上

### 2.5 交互与评测层

- `ChatSession`
- `ChatMessage`
- `QuestionTemplate`
- `ExamPaper`
- `ExamPaperItem`
- `UserKnowledgeState`

说明：

- 聊天层消费知识层，不反向定义知识真相
- Examine 与 Profile 共享 `TeachingUnit / KnowledgeNode / Curriculum` 这些锚点

---

## 3. 当前兼容别名与过渡对象

### 3.1 兼容别名

当前代码里有一些名字仍然保留，但语义已经收敛：

- `CurriculumSnapshot = Curriculum`
- `CurriculumVersion = Curriculum`
- `ThemeTreeVersion = Curriculum`
- `PrereqDagVersion = Curriculum`

这些别名是为了兼容已有调用，不代表还存在独立主表。

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
- `curriculum_job_id`
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

当前系统采用“共享构建版号”：

- `curriculum.version_no`
- `knowledge_document.version_no`
- `knowledge_node.build_revision_no`
- `knowledge_edge.build_revision_no`

同一轮 digest 中，这几个版本必须对齐。

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
