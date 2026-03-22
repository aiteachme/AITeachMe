# 02. 领域模型与状态

## 1. 文档目标

本文档用于说明 AITeachMe 当前真正重要的领域对象、状态对象和它们之间的边界。

这份文档重点回答 4 个问题：

- 系统里哪些对象是稳定的业务实体。
- 哪些对象只是工作流状态，不应该暴露成长期协议。
- 知识图谱、课程结构、知识文档各自处在什么层。
- 数据库与本地文件分别承担什么职责。

---

## 2. 边界总览

| 边界 | 核心对象 | 当前定位 |
| --- | --- | --- |
| 工作空间 | `Subject`、`RawFile` | 当前主路径 |
| 材料层 | `Document`、`DocumentChunk`、`chunk_embeddings` | 当前主路径 |
| 知识层 | `KnowledgeNode`、`KnowledgeEdge`、`EvidenceLink`、`GraphDigestJob`、`SubjectBuildLock` | 当前主路径 |
| 课程结构层 | `TeachingUnit*`、`ThemeTree*`、`PrereqDag*`、`CurriculumSnapshot`、`CurriculumDeriveJob` | 当前主路径 |
| 知识文档层 | `KnowledgeDoc` | 当前主路径 |
| 交互层 | `ChatMessage` | 当前主路径 |
| 测评与学习状态 | `QuestionBuildJob`、`ExamGenerateJob`、`ExamGradeJob`、`UserKnowledgeState`、`ReviewTask` | 演进主方向 |
| 旧测评层 | `Exam`、`Question`、`ExamSubmission`、`AnswerRecord`、`Mistake`、`UserProfile` | 仍在兼容期 |

关键更新：

- 知识文档链路已经不再使用 `DocGenJob`。
- 知识文档的外部协议中不再有 `job_id`、`status`、`progress`、`current_step`。
- 知识文档构建状态只存在于内部文件锁和工作流阶段日志中。

---

## 3. 核心对象

### 3.1 Subject

`Subject` 是顶层工作空间边界，同时决定：

- API 路由边界。
- 本地运行时目录边界。
- 后端多条工作流的隔离范围。

### 3.2 RawFile

`RawFile` 代表接入层文件对象，负责表达：

- 原始文件身份。
- 文件路径与类型。
- 解析状态。
- Markdown 产物与资源目录。

它回答的是“资料是否已经进入系统并可被 Digest 消费”。

### 3.3 Document / DocumentChunk / chunk_embeddings

这三者是材料层桥接对象：

- `Document` 表示 Digest 可消费的文档级材料。
- `DocumentChunk` 表示检索、证据引用、图谱抽取使用的块级材料。
- `chunk_embeddings` 是与 `DocumentChunk` 同步维护的向量索引。

它们是 Ingest、Digest、Interact 共同依赖的稳定材料层。

### 3.4 Knowledge Graph

知识层当前由下列对象组成：

- `KnowledgeNode` / `KnowledgeEdge`
- `KnowledgeRevision` / `EdgeRevision`
- `EvidenceLink`
- `KnowledgeAlias`
- `GraphDigestJob`
- `SubjectBuildLock`

这层回答“学科知识世界本身是什么样”。

### 3.5 Curriculum

课程结构层负责把知识图谱转换为教学组织视图，核心对象包括：

- `TeachingUnit`
- `TeachingUnitRevision`
- `TeachingUnitMembership`
- `ThemeTreeVersion`
- `ThemeTreeNode`
- `UnitTreeMembership`
- `PrereqDagVersion`
- `UnitDependency`
- `CurriculumSnapshot`
- `CurriculumDeriveJob`

这层回答“这些知识应该怎么组织、怎么展示、怎么安排学习顺序”。

### 3.6 KnowledgeDoc

知识文档层现在只有一个长期业务对象：`KnowledgeDoc`。

它对应的是已经发布的知识文档章节记录，而不是构建任务。

知识文档的发布形态明确为两层：

- 多个章节文档：`chapter_XX_*.md`
- 一个最终合并文档：`merged_knowledge_base.md`

知识文档层的重要结论：

- `KnowledgeDoc` 承载的是已发布章节。
- `merged_knowledge_base.md` 是面向阅读页的统一入口。
- 不再引入 `DocGenJob` 作为外部状态对象。
- 构建中的状态由 `.build.lock` 与 `_building/` staging 目录表达。
- 最近一版发布元信息由 `manifest.json` 表达。

### 3.7 ChatMessage

`ChatMessage` 表达对话真相，主要记录：

- 用户与助手消息。
- turn 对。
- 检索上下文。
- 创建时间。

它消费知识文档或 chunk 检索结果，但不反向承担知识真相层职责。

---

## 4. 状态对象

### 4.1 保留为显式作业状态的对象

当前仍保留显式 job 状态的链路只有：

- `GraphDigestJob`
- `CurriculumDeriveJob`
- 测评相关 jobs

这些对象适用于需要精确恢复、补偿、清理和串联后续任务的后台流程。

### 4.2 不再对外暴露作业状态的对象

知识文档 Docs 链路已经明确改为“去 job 化”：

- 没有 `DocGenJob`
- 没有 `job_id`
- 没有后端 `status/progress/current_step` 协议
- 没有查询任务状态的 API

### 4.3 Knowledge Docs 的内部状态表达

知识文档构建当前通过 3 类内部对象表达状态：

- `.build.lock`
  表示同一 subject 下当前已有一轮知识文档构建在进行。
- `_building/`
  表示 staging 目录，先写新章节和新 merged，再一次性发布。
- `manifest.json`
  表示最近一次已发布版本的元信息。

这些状态是内部实现细节，不应再扩散到公开 API。

---

## 5. 知识文档发布模型

### 5.1 发布单元

一次知识文档发布包含：

- 若干章节 Markdown 文件
- 一个 merged Markdown 文件
- 一份 manifest
- 一组 `KnowledgeDoc` 章节记录

### 5.2 构建与发布的边界

知识文档链路采用 staging 发布：

1. 先生成 `_building/chapter_XX_*.md`
2. 再生成 `_building/merged_knowledge_base.md`
3. 全部成功后覆盖正式目录
4. 同步覆盖 `manifest.json`
5. 同步重建 `KnowledgeDoc` published 记录

这保证了：

- 构建失败时旧版文档仍可读。
- 前端轮询 `knowledge/docs` 时只会看到已发布版本。
- 多章节和 merged 始终保持同一发布批次。

---

## 6. 存储边界

### 6.1 数据库存什么

数据库保存：

- 工作空间实体
- 原始文件元数据
- 材料层对象
- 知识图谱与课程结构
- 对话与测评结构化数据
- `KnowledgeDoc` 已发布章节记录

### 6.2 本地文件存什么

本地文件系统保存：

- 原始二进制文件
- Markdown 解析结果
- 图片与附件资源
- 已发布知识文档 Markdown
- 构建中的 staging 产物
- docgen 中间文件

### 6.3 谁是 canonical truth

对知识文档链路来说：

- 已发布章节的业务索引真相在数据库 `KnowledgeDoc`
- 已发布正文真相在 `knowledge_docs/*.md`
- 最近一版发布时间和来源元信息真相在 `manifest.json`

也就是说，这条链路是“数据库索引 + 本地 Markdown 正文 + manifest 元信息”的联合真相，而不是 `DocGenJob`。

---

## 7. 当前结论

当前 Docs 链路的领域边界已经明确：

- `KnowledgeDoc` 是业务对象。
- `.build.lock`、`_building/`、`manifest.json` 是内部运行时状态。
- 前端进度条是前端自己的体验层协议，不再依赖后端状态对象。
- Graph / Curriculum 仍保留 job 体系，不与 Docs 混淆。
