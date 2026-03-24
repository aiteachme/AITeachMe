# 13. 数据库表清单与工作流写入地图

## 1. 文档目标

本文档只讲“当前真实代码里有哪些表、谁在写、什么时候写”。

适用场景：

- 新人快速理解数据库
- 排查某个 workflow 到底落了哪些表
- 规划中心化部署前的数据边界

---

## 2. 当前表清单

### 2.1 工作空间与材料层

| 表 | 主要职责 | 主要写入方 |
| --- | --- | --- |
| `subject` | 学科工作空间元数据 | `subject_service` |
| `raw_file` | 上传文件、解析状态、路径、解析元数据 | `file_service`、`workflows/ingest/*` |
| `document` | digest graph 使用的标准文档 | `workflows/digest/kg/support.py` |
| `document_chunk` | 文档切块 | `workflows/digest/kg/support.py` |
| `chunk_embeddings` | `document_chunk` 向量 | `knowledge_repo.bulk_insert_embeddings()` |
| `knowledge_doc` | 已发布知识文档章节索引 | `workflows/digest/docs/nodes/finalize_node.py` |

### 2.2 知识图谱层

| 表 | 主要职责 | 主要写入方 |
| --- | --- | --- |
| `knowledge_node` | 图谱节点身份层 | `workflows/digest/kg/mutations.py` |
| `knowledge_revision` | 节点正文版本 | `workflows/digest/kg/mutations.py` |
| `knowledge_alias` | 节点别名 | `workflows/digest/kg/mutations.py` |
| `knowledge_edge` | 图谱边身份层 | `workflows/digest/kg/resolve_nodes.py` |
| `edge_revision` | 边版本 | `workflows/digest/kg/resolve_nodes.py` |
| `evidence_link` | 节点/边到 chunk 的证据链 | `workflows/digest/kg/mutations.py` |

### 2.3 课程结构层

| 表 | 主要职责 | 主要写入方 |
| --- | --- | --- |
| `teaching_unit` | 教学单元身份层 | `curriculum/services/unit_builder.py` |
| `teaching_unit_revision` | 教学单元版本 | `curriculum/services/unit_builder.py` |
| `teaching_unit_membership` | 知识点归属教学单元 | `curriculum/services/unit_builder.py` |
| `taxonomy_anchor` | 分类锚点 | `curriculum/services/theme_tree_builder.py`、`curriculum_service` |
| `theme_tree_version` | 主题树版本 | `curriculum/services/theme_tree_builder.py` |
| `theme_tree_node` | 主题树节点 | `curriculum/services/theme_tree_builder.py` |
| `unit_tree_membership` | 教学单元挂树关系 | `curriculum/services/theme_tree_builder.py` |
| `prereq_dag_version` | 先修 DAG 版本 | `curriculum/services/prereq_dag_builder.py` |
| `unit_dependency` | 教学单元依赖边 | `curriculum/services/prereq_dag_builder.py` |
| `curriculum_snapshot` | 当前课程结构快照 | `curriculum/nodes.py::finalize_curriculum_node` |

### 2.4 对话、测评与学习状态

| 表 | 主要职责 | 主要写入方 |
| --- | --- | --- |
| `chat_session` | 会话元信息 | `chats_service` |
| `chat_message` | 聊天消息 | `chats_service` |
| `question_template` | 题目模板 | assessment / examine 链路 |
| `question_template_node_link` | 题目模板与知识点映射 | assessment / examine 链路 |
| `exam_paper` | 新 assessment 试卷 | assessment / examine 链路 |
| `exam_paper_item` | 试题快照 | assessment / examine 链路 |
| `user_answer_attempt` | 用户作答记录 | assessment / examine 链路 |
| `user_knowledge_state` | 掌握度状态 | assessment / profile 链路 |
| `review_task` | 复习任务 | assessment / profile 链路 |
| `exam_paper_generation_context` | 组卷上下文 | assessment / examine 链路 |

### 2.5 Legacy 兼容表

| 表 | 备注 |
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
