# 13. 数据库结构方案

## 1. 设计原则

- 本文档只写正式方案，不做旧方案兼容设计。
- 主干归属统一到 `user_id` / `subject_id`。
- 所有主表统一使用数值主键 `id`。
- `subject.slug` 只作为外部路由标识，不作为内部主关系。
- 文件存储统一使用 `storage_backend + storage_key`。
- 原始资料直接存解析结果，不再额外保留 `raw_file -> document` 这种 1:1 中间主表。
- 向量层只保留一张表：`chunk_embeddings`，但它服务统一检索分块 `retrieval_chunk`，而不是只服务原始资料。
- 标题路径、章节名、主题词只作为弱元信息；统一检索层以语义内容、结构邻接、证据引用为主，不做关键词驱动设计。
- 不再单独拆版本表、快照表、上下文表；能并回主表就并回主表。
- `chat_session` / `chat_message` 保持当前已定稿结构，不在本轮改字段形态。

## 2. 顶层关系

```text
user
  └─ 1:N subject
        ├─ 1:N raw_file
        │     └─ 1:N raw_file_asset
        ├─ 1:N knowledge_document
        ├─ 1:N knowledge_node
        │     ├─ 1:N knowledge_alias
        │     ├─ 1:N knowledge_edge
        │     └─ 1:N knowledge_evidence
        ├─ 1:N teaching_unit
        │     └─ 1:N teaching_unit_membership
        ├─ 1:N curriculum_version
        │     ├─ 1:N curriculum_tree_node
        │     ├─ 1:N curriculum_unit_link
        │     └─ 1:N curriculum_dependency
        ├─ 1:N question_template
        │     └─ 1:N question_template_node_link
        ├─ 1:N exam_paper
        │     └─ 1:N exam_paper_item
        │           └─ 1:N user_answer_attempt
        ├─ 1:N user_knowledge_state
        ├─ 1:N review_task
        ├─ 1:N retrieval_chunk
        │     └─ 1:N chunk_embeddings
        └─ 1:N chat_session
              └─ 1:N chat_message
```

- `retrieval_chunk` 是统一检索层，来源可以是 `raw_file`、`knowledge_document`、`knowledge_node`、`knowledge_edge`、`question_template`、`exam_paper_item`。

## 3. 表设计

### `user`

- 用途：用户主表。

| 字段 | 说明 |
| --- | --- |
| `exam` / `question` / `exam_submission` / `answer_record` / `mistake` | 旧 exam 链路仍保留 |
| `user_profile` | 旧 profile 链路仍保留 |

---

## 3. Ingest LangGraph 写入地图

### 3.1 上传入口

模块：`backend/app/services/file_service.py`

写入：

- `raw_file`

本地文件：

- `raw/<raw_file_id>.<ext>`

说明：

- `save_uploaded_file()` 先创建 `raw_file`
- 然后把上传内容移动到 `raw/`

### 3.2 `build_classify_file_node`

文件：`backend/app/workflows/ingest/nodes/file.py`

写入表：

- `raw_file`

更新字段：

- `estimated_pages`
- `detected_language`
- `classification_result`
- `ingest_status = parsing`

### 3.3 `build_parse_file_node`

文件：`backend/app/workflows/ingest/nodes/parse.py`

直接写入表：

- `raw_file`：把 `ingest_status` 推到 `validating`

本地文件：

- `raw_markdown/<raw_file_id>.md`
- `assets/<asset_name_prefix>__*.png|jpg|...`

说明：

- parser 会把 markdown canonicalize
- 会对提取图片做 asset OCR 补强
- 会把 `intentionally omitted` 这类图片占位符替换成真实图片引用和 OCR 正文

### 3.4 `build_finalize_success_node`

文件：`backend/app/workflows/ingest/nodes/finalize.py`

写入表：

- `raw_file`

更新字段：

- `markdown_path`
- `asset_dir`
- `status = completed`
- `error_message = null`
- `content_hash`
- `file_size_bytes`
- `estimated_pages`
- `detected_language`
- `classification_result`
- `parse_metadata`
- `image_count`
- `ingest_status = ready_for_digest`

---

## 4. Digest Docs LangGraph 写入地图

### 4.1 `load_files_node`

文件：`backend/app/workflows/digest/docs/nodes/load_files_node.py`

读取：

- `raw_file`

说明：

- 只收集已具备 `markdown_path` 的输入文件
- 不写表

### 4.2 `cleanse_node` / `outline_*` / `draft_node` / `review_node` / `metadata_node`

写表：

- 无正式数据库写入

本地文件：

- `knowledge_markdown/_build/clean_*`
- `knowledge_markdown/_build/outline_tree.json`
- `knowledge_markdown/_build/chapter_assignments.json`
- `knowledge_markdown/_build/draft_*.md`

### 4.3 `finalize_node`

文件：`backend/app/workflows/digest/docs/nodes/finalize_node.py`

写入表：

- `knowledge_doc`

写入本地：

- `knowledge_markdown/_build/chapter_XX_*.md`
- `knowledge_markdown/_build/merged_knowledge_base.md`
- 发布后移动到 `knowledge_markdown/*.md`
- `knowledge_markdown/manifest.json`
- `knowledge_markdown/.build.lock`

说明：

- 先清空旧 `knowledge_doc`
- 再批量写入新的章节记录
- `merged_knowledge_base.md` 目前主要作为阅读页主入口

---

## 5. Digest Graph LangGraph 写入地图

### 5.1 `prepare_node`

文件：`backend/app/workflows/digest/kg/prepare_nodes.py`

核心写入在：

- `backend/app/workflows/digest/kg/support.py::prepare_chunk_ids_for_files`

写入表：

- `document`
- `document_chunk`
- `chunk_embeddings`

说明：

- 如果 `raw_file` 还没有对应的 `document/document_chunk`，这里会补材料化
- 这一步是 `raw_markdown -> document -> chunk -> embedding` 的真正桥梁

### 5.2 `resolve_nodes_node`

文件：`backend/app/workflows/digest/kg/resolve_nodes.py`

写入表：

- `knowledge_node`
- `knowledge_revision`
- `knowledge_alias`
- `evidence_link`

说明：

- 新节点会创建 `knowledge_node + revision`
- 已有节点会按需要追加 revision 或 alias
- 证据统一落在 `evidence_link`

### 5.3 `resolve_edges_node`

文件：`backend/app/workflows/digest/kg/resolve_nodes.py`

写入表：

- `knowledge_edge`
- `edge_revision`
- `evidence_link`

说明：

- 新边会创建 `knowledge_edge + edge_revision`
- 已有边会刷新置信度并补证据

### 5.4 `build_finalize_graph_node`

文件：`backend/app/workflows/digest/kg/finalize_nodes.py`

写入表：

- `knowledge_node`
- `knowledge_edge`
- `knowledge_revision`
- `edge_revision`
- `evidence_link`

实际动作：

- 激活本轮 pending 图谱实体
- 清理失败分支上的 pending 数据
- 触发 curriculum workflow

### 5.5 关于 “job_id”

当前 graph workflow 里仍有 `job_id/run_id` 这个运行时概念，但：

- 相关 repository 更新函数已经是 compatibility shim
- 现在没有真正持久化的 `graph_digest_job` 表

因此数据库真相仍然是上面的业务表，而不是 job 表。

---

## 6. Digest Curriculum LangGraph 写入地图

### 6.1 `derive_units_node`

文件：`backend/app/workflows/digest/curriculum/nodes.py`

核心写入在：

- `backend/app/workflows/digest/curriculum/services/unit_builder.py`

写入表：

- `teaching_unit`
- `teaching_unit_revision`
- `teaching_unit_membership`

### 6.2 `derive_theme_tree_node`

核心写入在：

- `backend/app/workflows/digest/curriculum/services/theme_tree_builder.py`

写入表：

- `taxonomy_anchor`
- `theme_tree_version`
- `theme_tree_node`
- `unit_tree_membership`

### 6.3 `derive_prereq_dag_node`

核心写入在：

- `backend/app/workflows/digest/curriculum/services/prereq_dag_builder.py`

写入表：

- `prereq_dag_version`
- `unit_dependency`

### 6.4 `finalize_curriculum_node`

文件：`backend/app/workflows/digest/curriculum/nodes.py`

写入表：

- `curriculum_snapshot`
- `theme_tree_version` 状态发布/归档
- `prereq_dag_version` 状态发布/归档
- `teaching_unit` 状态更新

说明：

- 这里负责把“草稿版本”切成当前 published 版本
- `curriculum_snapshot` 是前端读取课程结构时最重要的稳定锚点之一

### 6.5 关于 curriculum 的运行时 ID

和 graph 一样，当前 `curriculum_job_id` 更偏运行时 / 日志语义：

- repository 里的 `create/update_curriculum_job()` 已是 compatibility shim
- 当前数据库设计不以 `curriculum_derive_job` 表为真相

---

## 7. 其他服务层写入

### 7.1 Chat

主要写入：

- `chat_session`
- `chat_message`

### 7.2 Assessment / Examine

主要写入：

- `question_template`
- `question_template_node_link`
- `exam_paper`
- `exam_paper_item`
- `user_answer_attempt`
- `exam_paper_generation_context`

### 7.3 Profile / Mastery

主要写入：

- `user_knowledge_state`
- `review_task`

---

## 8. 当前结论

当前数据库最重要的主线其实很清楚：

`raw_file -> document -> document_chunk -> chunk_embeddings -> knowledge_* -> teaching_unit* -> curriculum_snapshot`

再往上，Docs workflow 会把面向用户的最终讲义写成：

- `knowledge_doc` 表
- `knowledge_markdown/*.md` 文件

后续如果继续扩架构，这条主线应继续保持稳定，不要再把临时 job 表重新变成系统真相源。

---

## 9. 完整 1:N 外键关系图

### 材料层

```
raw_file ──(1:N)──> document                    [document.source_file_id → raw_file.id]
document ──(1:N)──> document_chunk              [document_chunk.document_id → document.id]
document_chunk ──(1:1)──> chunk_embeddings      [虚拟表, chunk_id → document_chunk.id]
knowledge_doc                                    [孤岛表，source_file_ids 为 JSON 字符串]
```

### 知识图谱层

```
knowledge_node ──(1:N)──> knowledge_alias       [knowledge_alias.node_id → knowledge_node.id]
knowledge_node ──(1:N)──> knowledge_revision    [knowledge_revision.node_id → knowledge_node.id]
knowledge_node ──(self)──> knowledge_node       [merged_into_node_id → knowledge_node.id]
knowledge_node ──(1:N src)──> knowledge_edge    [knowledge_edge.source_node_id → knowledge_node.id]
knowledge_node ──(1:N tgt)──> knowledge_edge    [knowledge_edge.target_node_id → knowledge_node.id]
knowledge_edge ──(1:N)──> edge_revision         [edge_revision.edge_id → knowledge_edge.id]
document ──(1:N)──> evidence_link               [evidence_link.document_id → document.id]
document_chunk ──(1:N)──> evidence_link         [evidence_link.chunk_id → document_chunk.id]
evidence_link ──(poly)──> node | edge           [entity_type + entity_id，无 DB FK]
```

### 课程层

```
teaching_unit ──(1:N)──> teaching_unit_revision     [unit_id → teaching_unit.id]
teaching_unit ──(1:N)──> teaching_unit_membership   [unit_id → teaching_unit.id]
knowledge_node ──(1:N)──> teaching_unit_membership  [knowledge_node_id → knowledge_node.id]
taxonomy_anchor ──(self)──> taxonomy_anchor          [parent_anchor_id → taxonomy_anchor.id]
theme_tree_version ──(1:N)──> theme_tree_node       [tree_version_id → theme_tree_version.id]
taxonomy_anchor ──(1:N)──> theme_tree_node          [anchor_id → taxonomy_anchor.id, nullable]
theme_tree_node ──(self)──> theme_tree_node          [parent_tree_node_id → theme_tree_node.id]
theme_tree_version ──(1:N)──> unit_tree_membership  [tree_version_id → theme_tree_version.id]
theme_tree_node ──(1:N)──> unit_tree_membership     [tree_node_id → theme_tree_node.id]
teaching_unit ──(1:N)──> unit_tree_membership       [teaching_unit_id → teaching_unit.id]
prereq_dag_version ──(1:N)──> unit_dependency       [dag_version_id → prereq_dag_version.id]
teaching_unit ──(1:N src)──> unit_dependency        [source_unit_id → teaching_unit.id]
teaching_unit ──(1:N tgt)──> unit_dependency        [target_unit_id → teaching_unit.id]
theme_tree_version ──(1:N)──> curriculum_snapshot   [theme_tree_version_id → theme_tree_version.id]
prereq_dag_version ──(1:N)──> curriculum_snapshot   [prereq_dag_version_id → prereq_dag_version.id]
```

### 测评层

```
teaching_unit ──(1:N)──> question_template              [teaching_unit_id → teaching_unit.id]
curriculum_snapshot ──(1:N)──> question_template         [source_snapshot_id → curriculum_snapshot.id, nullable]
question_template ──(1:N)──> question_template_node_link [question_template_id → question_template.id]
knowledge_node ──(1:N)──> question_template_node_link   [knowledge_node_id → knowledge_node.id]
curriculum_snapshot ──(1:N)──> exam_paper                [curriculum_snapshot_id → curriculum_snapshot.id]
exam_paper ──(1:N)──> exam_paper_item                   [exam_paper_id → exam_paper.id]
question_template ──(1:N)──> exam_paper_item            [question_template_id → question_template.id]
exam_paper_item ──(1:N)──> user_answer_attempt          [exam_paper_item_id → exam_paper_item.id]
exam_paper ──(1:1)──> exam_paper_generation_context     [exam_paper_id → exam_paper.id, unique]
theme_tree_node ──(1:N)──> exam_paper_generation_context [target_theme_tree_node_id, nullable]
user_knowledge_state ──(1:N)──> review_task             [source_state_id → user_knowledge_state.id, nullable]
exam_paper ──(1:N)──> review_task                       [source_exam_paper_id → exam_paper.id, nullable]
user_knowledge_state ──(poly)──> teaching_unit | knowledge_node  [granularity + target_id，无 DB FK]
review_task ──(poly)──> teaching_unit | knowledge_node           [target_granularity + target_id，无 DB FK]
```

### 对话层

```
chat_session ──(1:N)──> chat_message   [chat_message.session_id → chat_session.id]
```

### Legacy 层

```
exam ──(1:N)──> question                [question.exam_id → exam.id]
exam ──(1:N)──> exam_submission         [exam_submission.exam_id → exam.id]
exam_submission ──(1:N)──> answer_record  [answer_record.submission_id → exam_submission.id]
question ──(1:N)──> answer_record       [answer_record.question_id → question.id]
answer_record ──(1:N)──> mistake        [mistake.answer_record_id → answer_record.id]
user_profile                             [孤岛表，无 FK]
```

---

## 10. 已知设计取舍与待改进项

### 已知取舍（当前可接受）

| 取舍 | 原因 |
| --- | --- |
| `subject` 在所有表中为字符串而非 FK | 充当分区键，简化查询，避免 join；迁移 PostgreSQL 时再改为 FK |
| `evidence_link` 多态 `entity_type + entity_id` | 避免为 node/edge 各建一张证据表；完整性由服务层保证 |
| `user_knowledge_state` / `review_task` 多态 `target_id` | 同上，粒度为 unit 或 node 两种 |
| 无 ORM `Relationship()` 声明 | 全项目统一手动 join，保持模型为纯数据类 |
| `current_revision_id` 未声明为 FK | 避免 node ↔ revision 循环 FK 问题 |

### 待改进项

| 优先级 | 项目 | 说明 |
| --- | --- | --- |
| P1 | ~~`chat_message.session_id` 缺 FK~~ | 已修复，加 `foreign_key="chat_session.id"` |
| P1 | ~~assessment 模型 `datetime.utcnow`~~ | 已修复，统一为 `utcnow` |
| P2 | `knowledge_doc.source_file_ids` JSON 字符串 | 建议新增 `knowledge_doc_source` 联结表 |
| P2 | 版本表可合并 | `theme_tree_version` + `prereq_dag_version` + `curriculum_snapshot` 可合为 `curriculum_version` |
| P3 | Legacy 表清理 | 6 张遗留表待加入 `_LEGACY_DROP_DDLS` |
| P3 | `subject` 改为 FK | 等 PostgreSQL 迁移时统一处理 |
