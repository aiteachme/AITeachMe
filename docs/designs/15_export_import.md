# 导入导出设计（当前实现）

当前导入导出以现有数据库和 content store 为准，不导出已经移除的课程结构表。

## 导出范围

导出入口由 `backend/app/workflows/support/export_import/exports.py` 的 `TABLE_REGISTRY` 驱动。当前包含：

- `subject`
- `raw_file`
- `subject_file`
- `retrieval_chunk`
- `knowledge_document`
- `knowledge_unit`
- `knowledge_edge`
- `question_type_registry`
- `question_template`
- `exam_paper`
- `exam_paper_item`
- `user_knowledge_state`
- `chat_session`
- `chat_message`
- `confirmed_build_plan`

知识图谱当前由 `knowledge_unit + knowledge_edge` 表达；旧设计中的 `knowledge_node` 不再作为导出表名。

## 不导出的表

以下结构不是当前实现的业务表，因此不会出现在导出包中：

- `curriculum`
- `teaching_unit`
- `taxonomy_anchor`
- `theme_tree_node`
- `unit_dependency`
- `graph_digest_job / curriculum_derive_job / question_build_job / exam_generate_job / exam_grade_job`

如果未来恢复课程结构能力，需要同步扩展数据库迁移、导出清单、导入重映射和 API 契约。

## 文件资产

导出会打包学科相关 content store 文件，但会跳过运行时和临时构建产物：

- `.build.lock`
- `build_status.json`
- `_build/`
- `versions/`

导入时会清理路径型字段和向量字段，由目标环境重新解析或重建需要的派生数据。

## ID 与外键重映射

导入流程需要保证以下依赖顺序：

`subject -> raw_file -> subject_file -> retrieval_chunk -> knowledge_document -> knowledge_unit -> knowledge_edge -> question_type_registry -> question_template -> exam_paper -> exam_paper_item -> user_knowledge_state -> chat_session -> chat_message -> confirmed_build_plan`

重点规则：

- `subject.slug` 可按导入策略保留或生成新 slug。
- `raw_file.uid`、`confirmed_build_plan.id` 等外部标识需要保持可追溯。
- `retrieval_chunk.document_id`、`knowledge_edge.source_node_id / target_node_id`、试题和画像中的 `knowledge_unit_id` 必须按新 ID 重映射。
- `confirmed_build_plan.selected_file_ids_json` 需要按 `raw_file` 新 ID 重映射。

## MVP 约束

- `KnowledgeUnit` 的 alias、evidence 和轻量 revision 仍保存在 JSON 字段内，导入导出不拆分子表。
- 导入后不自动创建课程结构表。
- 向量索引属于可重建派生数据，不作为跨环境强一致资产处理。
