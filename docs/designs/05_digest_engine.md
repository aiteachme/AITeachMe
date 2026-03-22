# 05. Digest 引擎

## 1. 目标与职责

Digest 是 AITeachMe 的知识组织层，负责把材料层转换成两类可消费结构：

- 面向用户的可读知识文档
- 面向系统的知识图谱与课程结构

它位于 Ingest 和 Interact / Examine / Profile 之间，是全局知识中枢。

---

## 2. 当前实现落点

- 前端消费页面：`KnowledgeDocsPage`、`SummaryPage`
- 后端资源组：`knowledge`
- 业务入口：
  - `services/knowledge/digest_service.py`
  - `services/knowledge/curriculum_service.py`
  - `services/knowledge/graph_query_service.py`
- 工作流编排：
  - `backend/app/workflows/digest/docs/*`
  - `backend/app/workflows/digest/kg/*`
  - `backend/app/workflows/digest/curriculum/*`

当前 Digest 的编排真相已经是 `workflows/*`，不再以旧 `agents/digest/*` 为中心。

---

## 3. 当前主 Pipeline

### 3.1 知识文档 Pipeline

| 步骤 | 当前主模块 | 输入 | 输出 |
| --- | --- | --- | --- |
| 1. 任务创建 | `digest_service` | `subject`、文件集合 | `docgen_job` |
| 2. 文件加载 | `workflows/digest/docs/nodes/load_files_node.py` | `raw_file.markdown_path` | 原始 Markdown 列表；批量查库 + 并发读本地文件 |
| 3. 清洗与标准化 | `cleanse_node.py` | Markdown 列表 | 规则清洗后的文本；默认不做全文 LLM 自愈，仅对严重 OCR 噪声执行条件式修复；`docgen_intermediate/clean_*` |
| 4. 大纲生成 | `outline_map_node.py`、`outline_reduce_node.py` | 清洗文本 | 标题候选、内容预览、全局章节树、章节分配；先走轻量规则抽取，再由单次全局 LLM 统筹分章 |
| 5. 分章撰写与复核 | `draft_node.py`、`review_node.py`、`metadata_node.py` | 章节内容 | 章节 Markdown、摘要、标签；默认“一章一次正式生成”，review 以结构/公式审计为主，仅异常时触发定向修订；metadata 走规则快路径 |
| 6. 最终组装 | `finalize_node.py` | 章节结果 | `knowledge_doc`、`knowledge_docs/*.md` |

### 3.2 图谱与课程结构 Pipeline

| 步骤 | 当前主模块 | 输入 | 输出 |
| --- | --- | --- | --- |
| 1. 图谱任务创建 | `digest_service` | `subject`、文件集合 | `graph_digest_job` |
| 2. 材料准备 | `workflows/digest/kg/prepare_nodes.py` | `raw_file`、Markdown | `document`、`document_chunk`、待处理 chunk |
| 3. 候选抽取与聚类 | `prepare_nodes.py` | `document_chunk` | 节点/边候选 |
| 4. 实体对齐与证据挂接 | `resolve_nodes.py`、`mutations.py` | 候选集合 | `knowledge_*`、`evidence_link` |
| 5. 图谱收尾 | `finalize_nodes.py` | 图谱增量结果 | 完成态 `graph_digest_job`、派生 `curriculum_derive_job` |
| 6. 课程派生 | `curriculum/nodes.py` | 当前图谱与影响集 | `teaching_unit*`、`theme_tree*`、`prereq_dag*`、`curriculum_snapshot` |

---

## 4. 核心设计原则

### 4.1 Digest 同时服务用户与系统

Digest 的产出必须分两层理解：

- 用户可读层：知识文档
- 系统真相层：图谱、课程结构、证据链、版本快照

### 4.2 图谱是真相层，文档是消费层

知识文档适合阅读和交互，但它不替代图谱和课程结构的真相角色。

### 4.3 Teaching Unit 是图谱到教学的桥梁

不要直接拿细粒度知识节点去承担章节、课程和测评编排职责；这正是 `TeachingUnit` 存在的意义。

### 4.4 Theme Tree 与 Prereq DAG 各司其职

- Theme Tree：表达展示归属与章节组织
- Prereq DAG：表达学习顺序与依赖关系

### 4.5 证据链与版本化必须长期保留

Digest 不是一次性脚本，而是持续演进的知识构建系统。节点、边、单元、快照都要能追溯到：

- 哪些 chunk
- 哪次作业
- 当前是否处于发布版本

### 4.6 DocGen 要优先保证“章节顺 + 速度快 + 公式正确”

知识文档不是普通摘要，而是用户直接拿来学习和复习的讲义型产物。`docgen` 必须同时守住：

- 章节组织顺：先基础、后方法、再应用，不做材料拼盘
- 速度快：减少细碎 LLM 往返，优先用规则抽取和单次全局统筹
- 概念与公式正确：公式优先保真，不允许为了文风牺牲准确性

---

## 5. 数据库写入对象

### 5.1 知识文档链路

直接写入：

- `docgen_job`
- `knowledge_doc`

### 5.2 图谱链路

直接写入：

- `graph_digest_job`
- `subject_build_lock`
- `document`
- `document_chunk`
- `chunk_embeddings`
- `knowledge_node`
- `knowledge_edge`
- `knowledge_revision`
- `edge_revision`
- `evidence_link`
- `knowledge_alias`

### 5.3 课程结构链路

直接写入：

- `curriculum_derive_job`
- `teaching_unit`
- `teaching_unit_revision`
- `teaching_unit_membership`
- `taxonomy_anchor`
- `theme_tree_version`
- `theme_tree_node`
- `unit_tree_membership`
- `prereq_dag_version`
- `unit_dependency`
- `curriculum_snapshot`

---

## 6. 本地落盘对象

Digest 当前明确写本地文件的部分主要是知识文档链路：

- `data/<subject>/knowledge_docs/*.md`
- `data/<subject>/knowledge_docs/merged_knowledge_base.md`
- `data/<subject>/docgen_intermediate/*.md`
- `data/<subject>/docgen_intermediate/*.json`

图谱与课程结构当前以数据库为主；如果后续补更多调试摘要，应统一写入：

- `data/<subject>/debug/digest.graph/<job_id>/`
- `data/<subject>/debug/digest.curriculum/<job_id>/`
- `data/<subject>/debug/digest.docs/<job_id>/`

---

## 7. 关键状态推进

### 7.1 图谱构建

`graph_digest_job` 负责表达：

- pending
- processing
- completed / failed

并维护：

- `progress`
- `current_step`
- `input_chunk_count`
- `curriculum_job_id`

### 7.2 课程派生

`curriculum_derive_job` 负责表达：

- 受影响单元派生
- 主题树版本生成
- 先修图版本生成
- `curriculum_snapshot` 发布

### 7.3 知识文档生成

`docgen_job` 负责表达：

- loading
- cleansing
- outlining
- drafting
- reviewing
- metadata
- assembling
- done / failed

其中 `reviewing` 与 `metadata` 阶段当前以规则快路径为主，只在结构异常、公式覆盖不足或质量明显不稳时再升级到额外 LLM 修订。

---

## 8. 节点到表责任

### 8.1 Digest Docs

| 节点 / 模块 | 读 DB | 写 DB | 写 FS |
| --- | --- | --- | --- |
| `load_files_node.py` | `raw_file` | `docgen_job` | 读取 Markdown 文件 |
| `cleanse_node.py` | `docgen_job` | `docgen_job` | `docgen_intermediate/clean_*`；规则清洗优先，仅严重 OCR 噪声时触发 LLM 修复 |
| `outline_map_node.py` | `docgen_job` | `docgen_job` | 无；抽取标题候选与内容预览，默认不做逐块 LLM |
| `outline_reduce_node.py` | `docgen_job` | `docgen_job` | `docgen_intermediate/*.json`；单次全局统筹分章，生成章节分配并切到 `drafting` |
| `draft_node.py` | `docgen_job` | 无 | `docgen_intermediate/draft_*`；默认“一章一次” LLM 撰写，减少 section 级碎片化调用 |
| `review_node.py` | 无 | 无 | 无；先做结构/公式规则审计，仅在硬失败时做定向修订 |
| `metadata_node.py` | 无 | 无 | 无；从最终 Markdown 规则提取摘要与标签，不再依赖额外慢调用 |
| `collect_drafts` / `collect_reviews` | `docgen_job` | `docgen_job` | 无；汇总更新 `reviewing` / `metadata` 进度 |
| `finalize_node.py` | `docgen_job` | `knowledge_doc`、`docgen_job` | `knowledge_docs/*.md`、merged 文档；本地文件并发写入 + 单次批量落库，生成可直接阅读的总讲义入口 |

### 8.2 Digest Graph

| 节点 / 模块 | 读 DB | 写 DB | 写 FS |
| --- | --- | --- | --- |
| `prepare_nodes.py` | `raw_file`、`document`、`document_chunk` | `graph_digest_job`、`document`、`document_chunk`、`chunk_embeddings` | 读取 Markdown |
| `resolve_nodes.py` | `knowledge_*`、`document_chunk` | `knowledge_*`、`evidence_link`、`knowledge_alias` | 无 |
| `finalize_nodes.py` | `graph_digest_job` | `graph_digest_job`、`curriculum_derive_job`、构建锁释放 | 无 |

### 8.3 Digest Curriculum

| 节点 / 模块 | 读 DB | 写 DB | 写 FS |
| --- | --- | --- | --- |
| `curriculum/nodes.py` | `knowledge_*`、旧版本课程对象 | `curriculum_derive_job`、`teaching_unit*`、`theme_tree*`、`prereq_dag*`、`curriculum_snapshot` | 无 |

---

## 9. 开发关注点

### 9.1 文档要承认 Digest 已经是“三条 workflow”

当前 Digest 不是单一“图谱构建器”，而是 docs / graph / curriculum 三条工作流组合。

### 9.2 知识文档不是可有可无的附属能力

`knowledge_doc` 和 `knowledge_docs/` 已经是正式业务产物，设计文档必须把它们写成一等对象。

### 9.3 图谱与课程结构要继续保持数据库真相优先

本地调试文件可以加，但不能反过来取代 `graph_digest_job`、`knowledge_*`、`curriculum_snapshot` 这些结构化真相。

---

## 10. 总结

Digest 是项目最核心的知识中枢，当前已经形成清晰分工：

- docs workflow：生成用户可读知识文档
- kg workflow：构建知识图谱与证据链
- curriculum workflow：派生教学单元、主题树、先修图和课程快照

只要持续守住“文档是消费层、图谱是知识真相层、课程结构是教学组织层”这三个边界，Digest 就能持续为 Interact、Examine 和 Profile 提供稳定底座。
