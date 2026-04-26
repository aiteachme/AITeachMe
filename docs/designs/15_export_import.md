# 15. 学科项目导入与导出

**状态**: 已实现（后端，ContentStore 统一）
**最后更新**: 2026-04-26

---

## 1. 文档目标

本文档定义 AITeachMe 的学科级导入与导出能力：

- 将一个 Subject 下的已生成产物打包成单个 `.atmx` 文件。
- 导入后尽量复用已构建内容，直接进入交互、测验、知识文档与图谱浏览。
- 同时覆盖本地部署、未来中心化部署和演示课程分发。

当前实现以现有数据库和 content store 为准，不导出已经移除或尚未恢复的课程结构表。

---

## 2. 导出文件格式

`.atmx` 是一个 ZIP 压缩包，内部使用 JSON 序列化数据库数据，并通过 ContentStore 打包学科相关文件资产。

```text
subject_export.atmx
├── manifest.json
├── db/
│   ├── subject.json
│   ├── raw_file.json
│   ├── subject_file.json
│   ├── retrieval_chunk.json
│   ├── knowledge_document.json
│   ├── knowledge_unit.json
│   ├── knowledge_edge.json
│   ├── knowledge_graph_sync_run.json
│   ├── knowledge_graph_source_ref.json
│   ├── question_type_registry.json
│   ├── question_template.json
│   ├── exam_paper.json
│   ├── exam_paper_item.json
│   ├── user_knowledge_state.json
│   ├── chat_session.json
│   ├── chat_message.json
│   └── confirmed_build_plan.json
└── files/
```

`manifest.json` 读取端必须允许未知字段。新增字段应优先放在 `package`、`tables` 或 `extensions` 下，避免未来扩展时破坏旧包导入。

---

## 3. 当前导出范围

导出入口由 `backend/app/workflows/support/export_import/exports.py` 的 `TABLE_REGISTRY` 驱动。当前包含：

- `subject`
- `raw_file`
- `subject_file`
- `retrieval_chunk`
- `knowledge_document`
- `knowledge_unit`
- `knowledge_edge`
- `knowledge_graph_sync_run`
- `knowledge_graph_source_ref`
- `question_type_registry`
- `question_template`
- `exam_paper`
- `exam_paper_item`
- `user_knowledge_state`
- `chat_session`
- `chat_message`
- `confirmed_build_plan`

知识图谱当前由 `knowledge_unit + knowledge_edge` 表达，并通过 `knowledge_graph_sync_run + knowledge_graph_source_ref` 保留同步批次和章节/源文件溯源。旧设计中的 `knowledge_node` 不再作为导出表名。

---

## 4. 不导出的表与数据

以下结构不是当前实现的业务表，因此不会出现在导出包中：

- `curriculum`
- `teaching_unit`
- `taxonomy_anchor`
- `theme_tree_node`
- `unit_dependency`
- `graph_digest_job / curriculum_derive_job / question_build_job / exam_generate_job / exam_grade_job`

以下数据属于运行时或可重建派生数据：

- `chunk_embeddings`
- `user`
- `.build.lock`
- `build_status.json`
- `_build/`
- `versions/`
- `temp/`
- `debug/`
- `merged_knowledge_base.md`

如果未来恢复课程结构能力，需要同步扩展数据库迁移、导出清单、导入重映射和 API 契约。

---

## 5. 文件资产

导出会打包学科相关 content store 文件，但会跳过运行时和临时构建产物：

- `.build.lock`
- `build_status.json`
- `_build/`
- `versions/`

导入时会清理路径型字段和向量字段，由目标环境重新解析或重建需要的派生数据。

---

## 6. ID 与外键重映射

导入流程需要保证以下依赖顺序：

```text
subject
-> raw_file
-> subject_file
-> retrieval_chunk
-> knowledge_document
-> knowledge_unit
-> knowledge_edge
-> knowledge_graph_sync_run
-> knowledge_graph_source_ref
-> question_type_registry
-> question_template
-> exam_paper
-> exam_paper_item
-> user_knowledge_state
-> chat_session
-> chat_message
-> confirmed_build_plan
```

重点规则：

- `subject.slug` 可按导入策略保留或生成新 slug。
- `raw_file.uid`、`confirmed_build_plan.id` 等外部标识需要保持可追溯。
- `retrieval_chunk.document_id`、`knowledge_edge.source_node_id / target_node_id`、试题和画像中的 `knowledge_unit_id` 必须按新 ID 重映射。
- `knowledge_graph_source_ref.sync_run_id / knowledge_document_id / entity_id / source_file_ids_json` 必须按导入后的同步记录、知识文档、节点/关系和源文件 ID 重映射。
- `confirmed_build_plan.selected_file_ids_json` 需要按 `raw_file` 新 ID 重映射。
- 所有 `user_id` 字段映射为导入端当前用户。

---

## 7. API

```text
POST /api/v1/subjects/{subject}/export/preview
POST /api/v1/subjects/{subject}/export
POST /api/v1/subjects/import
```

导出请求体：

```json
{
  "include_raw_files": false,
  "include_raw_markdowns": true,
  "include_knowledge_docs": true,
  "include_chat_history": true,
  "include_exam_history": true,
  "include_profile": true
}
```

常见用法：

- 教师分发预构建课程包：通常关闭 `include_chat_history` 和 `include_profile`。
- 设备迁移/完整备份：按需打开解析缓存、对话、考试与画像。
- 只分享构建结果：保持 `include_raw_files=false` 且可关闭 `include_raw_markdowns`。

---

## 8. 演示课程分发建议

后续如果首页增加“演示课程”Tab，前端不要直接硬编码 OSS 路径，而是统一请求后端课程目录接口；后端统一读取公开课程索引，本地模式与云端模式共用同一套课程源。

推荐在 OSS 中固定一套公开前缀：

```text
demo-courses/
├── catalog/
│   └── v1/
│       └── index.json
├── packages/
│   └── <course_slug>/
│       └── v<package_version>/
│           └── <course_slug>.atmx
└── covers/
    └── <course_slug>.png
```

运行时职责：

- 本地模式和云端模式都读取同一份 `demo-courses/catalog/v1/index.json`。
- 前端只消费统一后的课程目录 API，不感知当前后端跑在本地还是云端。
- 真正导入时，由后端下载到临时目录后复用同一套 `import_subject()` 逻辑。
- 云端页面导入的是当前云端账号；本地页面导入的是本机后端。
- 需要离线分发时，运维侧下载 `.atmx` 后通过前端“上传导入”入口导入。

一句话原则：

> 课程分发主源统一为 OSS；导入执行器始终只有一套。

---

## 9. MVP 约束

- `KnowledgeUnit` 的 alias、evidence 和轻量 revision 仍保存在 JSON 字段内，导入导出不拆分子表。
- 导入后不自动创建课程结构表。
- 向量索引属于可重建派生数据，不作为跨环境强一致资产处理。
