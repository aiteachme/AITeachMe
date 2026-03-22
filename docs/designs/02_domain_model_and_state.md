# 02. 领域模型与状态

## 1. 目标与职责

本文档用于说明 AITeachMe 当前真正重要的领域对象、状态对象和过渡关系，重点回答：

- 当前数据库里有哪些核心对象
- 哪些对象是知识真相层，哪些是学习者状态层
- 哪些对象是 legacy，哪些已经迁移到 workflow-backed 新模型
- 哪些状态同时体现在数据库和本地文件系统中

---

## 2. 领域分层总览

当前系统最适合按 bounded context 来理解，而不是按单个表零散理解。

| 边界 | 主要对象 | 当前状态 |
| --- | --- | --- |
| 工作空间与接入 | `Subject`、`RawFile` | 当前主路径 |
| 材料层 | `Document`、`DocumentChunk`、`chunk_embeddings` | 当前主路径 |
| 对话层 | `ChatMessage` | 当前主路径 |
| 知识图谱层 | `KnowledgeNode`、`KnowledgeEdge`、`KnowledgeRevision`、`EdgeRevision`、`EvidenceLink`、`GraphDigestJob`、`SubjectBuildLock` | 当前主路径 |
| 课程结构层 | `CurriculumDeriveJob`、`TeachingUnit*`、`TaxonomyAnchor`、`ThemeTree*`、`PrereqDag*`、`CurriculumSnapshot` | 当前主路径 |
| 知识文档层 | `DocGenJob`、`KnowledgeDoc` | 当前主路径 |
| legacy exam/profile | `Exam`、`Question`、`ExamSubmission`、`AnswerRecord`、`Mistake`、`UserProfile` | 仍在线的旧路径 |
| workflow-backed assessment/profile | `QuestionBuildJob`、`QuestionTemplate*`、`ExamGenerateJob`、`ExamPaper*`、`ExamGradeJob`、`UserAnswerAttempt`、`UserKnowledgeState`、`ReviewTask` | 当前演进主方向 |

这意味着系统现在不是单一世界，而是：

- 一条稳定的 ingest / digest / interact 主链路
- 一条仍在服务前端的 legacy exam/profile 链路
- 一条已经落地到数据库的新 assessment/profile 工作流链路

---

## 3. 核心对象

### 3.1 Subject

`Subject` 是当前系统的一等实体，承担三类边界：

- API 路由边界
- 数据库查询边界
- 本地文件目录边界

它不是简单标签，而是顶层工作空间对象。

### 3.2 RawFile

`RawFile` 表示接入层材料对象，负责记录：

- 原始文件身份
- 文件路径与类型
- 解析状态
- Markdown 路径与资产目录
- 内容哈希、大小、估计页数、检测语言等元信息

`RawFile` 代表“资料进入系统”这件事，而不是知识内容本身。

### 3.3 Document / DocumentChunk / chunk_embeddings

这是当前最重要的材料桥接层：

- `Document`
  表示 Digest 可消费的文档级材料。
- `DocumentChunk`
  表示检索、证据引用、图谱抽取使用的块级材料。
- `chunk_embeddings`
  是与 `DocumentChunk` 同步维护的向量索引虚表。

当前 Ingest 的正式产出不是只停在 Markdown 文件，而是最终要稳定桥接到这一层。

### 3.4 Knowledge Graph

知识图谱层由以下对象组成：

- `KnowledgeNode` / `KnowledgeEdge`
  稳定身份对象。
- `KnowledgeRevision` / `EdgeRevision`
  内容修订对象。
- `EvidenceLink`
  证据链对象，把节点、边与 `DocumentChunk` 关联起来。
- `KnowledgeAlias`
  规范名与别名关系。
- `GraphDigestJob`
  图谱构建作业状态对象。
- `SubjectBuildLock`
  学科级构建互斥锁对象。

这层回答的是“学科知识世界长什么样”。

### 3.5 TeachingUnit / ThemeTree / PrereqDag / CurriculumSnapshot

课程结构层把知识图谱转成教学视图：

- `TeachingUnit`
  面向教学组织的稳定中间粒度。
- `TeachingUnitRevision` / `TeachingUnitMembership`
  单元版本与成员关系。
- `TaxonomyAnchor`
  树形挂载锚点。
- `ThemeTreeVersion` / `ThemeTreeNode` / `UnitTreeMembership`
  面向展示与章节组织的主题树。
- `PrereqDagVersion` / `UnitDependency`
  面向学习顺序的先修 DAG。
- `CurriculumSnapshot`
  面向消费侧的已发布课程快照。

这层回答的是“这些知识该怎么教、怎么展示、怎么排序”。

### 3.6 KnowledgeDoc / DocGenJob

知识文档层提供面向用户的可读产物：

- `DocGenJob`
  文档生成任务。
- `KnowledgeDoc`
  每章知识文档的数据库记录。

它与 `knowledge_docs/`、`docgen_intermediate/` 本地目录协同工作：数据库保存结构化索引与正文，本地文件保存 Markdown 文档和中间产物。

### 3.7 ChatMessage

`ChatMessage` 是当前对话真相表，记录：

- 用户与助手消息
- turn 对
- 引用 contexts JSON
- 创建时间

它消费 `DocumentChunk` 检索结果，但不直接修改知识结构对象。

### 3.8 legacy exam/profile 对象

当前仍在线的旧测评与画像对象包括：

- `Exam`
- `Question`
- `ExamSubmission`
- `AnswerRecord`
- `Mistake`
- `UserProfile`

这套模型主要由 `exams_service`、`profile_service` 和旧 API 路径消费。

### 3.9 workflow-backed assessment/profile 对象

新测评与学习状态层主要对象包括：

- 出题与题库：
  `QuestionBuildJob`、`QuestionTemplate`、`QuestionTemplateNodeLink`
- 组卷：
  `ExamGenerateJob`、`ExamPaper`、`ExamPaperItem`、`ExamPaperGenerationContext`
- 判卷：
  `ExamGradeJob`、`UserAnswerAttempt`
- 掌握度与复习：
  `UserKnowledgeState`、`ReviewTask`

这套模型由 `assessment_service`、`workflows/examine/*` 和 `workflows/profile/*` 消费，代表当前演进方向。

---

## 4. 主关系链路

### 4.1 资料与知识链路

`Subject -> RawFile -> Document -> DocumentChunk -> KnowledgeNode / KnowledgeEdge -> TeachingUnit -> ThemeTree / PrereqDag -> CurriculumSnapshot`

### 4.2 对话链路

`Subject -> DocumentChunk -> 检索结果 -> ChatMessage`

### 4.3 legacy 测评链路

`Subject -> Exam -> Question -> ExamSubmission -> AnswerRecord -> Mistake -> UserProfile`

### 4.4 workflow-backed 测评链路

`CurriculumSnapshot -> QuestionTemplate -> ExamPaper -> ExamPaperItem -> UserAnswerAttempt -> UserKnowledgeState -> ReviewTask`

当前开发必须明确自己改的是哪条链路，不能把两套模型混在一起理解。

---

## 5. 状态对象

### 5.1 接入状态

`RawFile` 是当前最重要的接入状态对象，主要体现：

- 上传成功
- 待解析
- 解析中
- 解析完成
- 解析失败
- ready for digest

同时它还关联本地正式产物路径：

- `file_path`
- `markdown_path`
- `asset_dir`

### 5.2 图谱构建状态

`GraphDigestJob` 负责表达图谱构建过程状态：

- `status`
- `progress`
- `current_step`
- `input_file_ids_json`
- `input_chunk_count`
- `error_message`

### 5.3 课程派生状态

`CurriculumDeriveJob` 负责表达主题树、先修图和快照派生状态。

### 5.4 文档生成状态

`DocGenJob` 负责表达知识文档构建状态，并与本地 `docgen_intermediate/` 中间文件协同。

### 5.5 对话状态

对话当前没有单独作业表，状态主要体现在：

- SSE 流式过程
- `ChatMessage` 成对落库结果

### 5.6 legacy exam/profile 状态

legacy 链路主要通过：

- `ExamSubmission`
- `AnswerRecord`
- `Mistake`
- `UserProfile`

表达测评结果和掌握度。

### 5.7 workflow-backed assessment/profile 状态

新链路使用显式作业表和状态表：

- `QuestionBuildJob`
- `ExamGenerateJob`
- `ExamGradeJob`
- `UserKnowledgeState`
- `ReviewTask`

这套设计比旧链路更适合长流程、幂等和可恢复任务。

---

## 6. 建模原则

### 6.1 材料层是所有下游能力的桥

`Document` / `DocumentChunk` 不是临时中间结果，而是 Ingest、Digest、Interact 共用的材料桥接层。

### 6.2 身份对象与内容对象分离

如果对象需要长期被引用和演进，就优先拆成稳定身份 + 修订内容，而不是直接覆盖更新。

### 6.3 知识层与学习者状态层分离

图谱、课程结构描述知识本身；聊天、测评、掌握度、复习任务描述学习者与知识的关系。两层必须通过稳定锚点关联，而不是直接混成一张状态表。

### 6.4 派生视图不替代真相层

Theme Tree、Prereq DAG、KnowledgeDoc 都是消费友好的派生视图，但不能反向替代图谱和材料层的真相角色。

### 6.5 必须显式承认双轨现状

当前 exam/profile 不是“一套旧模型已经没用了”，而是：

- 旧模型仍在线
- 新模型已落地
- 两套都必须在设计文档中被准确描述

---

## 7. 存储边界

### 7.1 数据库保存什么

数据库保存：

- 工作空间实体
- 资料元信息
- 文档与 chunk
- 向量对应关系
- 图谱与课程结构
- 聊天历史
- legacy exam/profile 数据
- workflow-backed assessment/profile 数据
- 各类作业状态

### 7.2 本地文件保存什么

本地文件系统保存：

- 原始二进制文件
- Markdown 解析结果
- 图片与附件资源
- 知识文档 Markdown
- 文档生成中间产物
- 开发期调试摘要

### 7.3 向量索引保存什么

`chunk_embeddings` 只保存 `DocumentChunk` 的向量表示，不承担业务元数据主存储职责。

---

## 8. 当前开发关注点

### 8.1 不要再把 07/08 文档写成单一旧模型

exam/profile 的文档和代码都必须显式标明 legacy 与 workflow-backed 两套模型。

### 8.2 UserProfile 不是唯一画像对象

当前更值得持续投资的是 `UserKnowledgeState` + `ReviewTask` 这套结构化学习状态层。

### 8.3 chunk_embeddings 是虚拟表，不是普通 ORM 表

它依赖 sqlite-vec，调试和迁移时必须单独考虑。

---

## 9. 总结

AITeachMe 当前的领域模型已经形成清晰骨架：

- `Subject` 管工作空间
- `RawFile / Document / DocumentChunk` 管材料
- 图谱与课程结构对象管知识和教学组织
- `ChatMessage` 管对话过程
- legacy exam/profile 与新 assessment/profile 并存，处于显式双轨期

后续开发的关键不是再发明更多对象，而是把这套对象的边界、状态语义和持久化职责保持清晰、稳定、可迁移。
