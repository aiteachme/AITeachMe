# 15. 课程项目导入与导出

**状态**: 已实现（后端，ContentStore 统一，导入安全边界已加固）
**最后更新**: 2026-04-27

---

## 1. 文档目标

本文档定义 AITeachMe 的课程级导入与导出能力：

- 将一个 Course 下的已生成产物打包成单个 `.atmx` 文件。
- 导入后尽量复用已构建内容，直接进入交互、测验、知识文档与图谱浏览。
- 同时覆盖本地部署、未来中心化部署和演示课程分发。

当前实现以现有数据库和 content store 为准，不导出已经移除或尚未恢复的课程结构表。

---

## 2. 导出文件格式

`.atmx` 是一个 ZIP 压缩包，内部使用 JSON 序列化数据库数据，并可携带少量课程级资产。当前导出器不打包原始上传文件，也不打包解析后的 raw markdown 文件；解析正文和检索 chunk 通过数据库记录进入导出包。

```text
course_export.atmx
├── manifest.json
├── db/
│   ├── course.json
│   ├── raw_file.json
│   ├── course_file.json
│   ├── retrieval_chunk.json
│   ├── knowledge_document.json
│   ├── knowledge_unit.json
│   ├── knowledge_edge.json
│   ├── knowledge_graph_sync_run.json
│   ├── knowledge_graph_source_ref.json
│   ├── question_type_registry.json
│   ├── question_template.json
│   ├── exam_paper.json
│   ├── mastery_drill_session.json
│   ├── exam_paper_item.json
│   ├── mastery_drill_attempt.json
│   ├── user_knowledge_state.json
│   ├── chat_session.json
│   └── chat_message.json
├── knowledge/
│   └── cover.<ext>              # 可选，当前 DocGen 封面稳定资产
└── files/                       # 当前导出器不写入；导入器保留兼容读取能力
```

`manifest.json` 读取端必须允许未知字段。新增字段应优先放在 `package`、`tables` 或 `extensions` 下，避免未来扩展时破坏旧包导入。

---

## 3. 当前导出范围

导出入口由 `backend/app/workflows/support/export_import/exports.py` 的 `TABLE_REGISTRY` 驱动。当前包含：

- `course`
- `raw_file`
- `course_file`
- `retrieval_chunk`
- `knowledge_document`
- `knowledge_unit`
- `knowledge_edge`
- `knowledge_graph_sync_run`
- `knowledge_graph_source_ref`
- `question_type_registry`
- `question_template`
- `exam_paper`
- `mastery_drill_session`
- `exam_paper_item`
- `mastery_drill_attempt`
- `user_knowledge_state`
- `chat_session`
- `chat_message`

知识图谱当前由 `knowledge_unit + knowledge_edge` 表达，并通过 `knowledge_graph_sync_run + knowledge_graph_source_ref` 保留同步批次和章节/源文件溯源。旧设计中的 `knowledge_node` 不再作为导出表名。
Planner 已确认构建方案随 `chat_session.meta_json.confirmed_plan` 导出；导入器仍兼容读取旧包中的 `db/confirmed_build_plan.json`。

---

## 4. 不导出的表与数据

以下结构不是当前实现的业务表，因此不会出现在导出包中：

- `curriculum`
- `teaching_unit`
- `taxonomy_anchor`
- `theme_tree_node`
- `unit_dependency`
- `graph_digest_job / curriculum_derive_job / question_build_job / exam_generate_job / exam_grade_job`

以下数据属于运行时、可重建派生数据或不随课程包迁移的数据：

- `chunk_embeddings`
- `user`
- 原始上传二进制文件
- raw markdown 存储文件
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

当前导出器只打包必要且稳定的课程展示资产：

- DocGen 发布封面：`knowledge/cover.<ext>`

当前导出器不会打包：

- 原始上传文件：`files/raw_files/...`
- raw markdown 存储文件：`files/raw_markdowns/...`
- raw file assets：`files/assets/...`
- 合并后的知识文档 markdown：`merged_knowledge_base.md`
- 构建中间态和历史版本：`_build/`、`versions/`、`temp/`、`debug/`

原因：

- `.atmx` 的 MVP 目标是迁移可学习内容和结构化产物，不是完整文件系统备份。
- 原始资料可能包含隐私、版权或过大的二进制文件。
- 解析正文已经落在 `raw_file.markdown_content`、`retrieval_chunk` 和知识文档相关表中。

导入器仍保留对 `files/raw_files`、`files/raw_markdowns`、`files/assets` 的兼容读取能力，便于未来重新支持富资产包或读取旧包。导入时会清理路径型字段和向量字段，在目标环境下重建新的 storage key。

---

## 6. ID 与外键重映射

导入流程需要保证以下依赖顺序：

```text
course
-> raw_file
-> course_file
-> retrieval_chunk
-> knowledge_document
-> knowledge_unit
-> knowledge_edge
-> knowledge_graph_sync_run
-> knowledge_graph_source_ref
-> question_type_registry
-> question_template
-> exam_paper
-> mastery_drill_session
-> exam_paper_item
-> mastery_drill_attempt
-> user_knowledge_state
-> chat_session
-> chat_message
```

重点规则：

- `course.id` 导入时始终生成新的 `course_id`，避免覆盖现有课程。
- `raw_file.uid` 会重新生成，避免跨环境唯一约束冲突。
- Planner 已确认计划内联在 `chat_session.meta_json.confirmed_plan`，导入时会重新生成 `confirmed_plan_id`。
- `retrieval_chunk.document_id`、`knowledge_edge.source_node_id / target_node_id`、试题和画像中的 `knowledge_unit_id` 必须按新 ID 重映射。
- `knowledge_graph_source_ref.sync_run_id / knowledge_document_id / entity_id / source_file_ids_json` 必须按导入后的同步记录、知识文档、节点/关系和源文件 ID 重映射。
- `chat_session.meta_json.confirmed_plan.selected_file_ids_json` 需要按 `raw_file` 新 ID 重映射。
- 所有 `user_id` 字段映射为导入端当前用户。

---

## 7. API

```text
POST /api/v1/courses/{course}/export/preview
POST /api/v1/courses/{course}/export
POST /api/v1/courses/import
GET  /api/v1/demo-courses
POST /api/v1/demo-courses/{identifier}/import
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

## 8. 导入安全边界

`.atmx` 是外部输入，导入端必须按不可信文件处理。

当前后端边界：

- 只接受 `.atmx` 和兼容 `.zip` 后缀。
- 上传复制过程分块写入临时文件，超过 `MAX_IMPORT_PACKAGE_SIZE_MB` 直接拒绝。
- 解压前校验 archive member 数量和总解压体积。
- 拒绝绝对路径、`../` 和其他会逃出目标目录的 archive path。
- `manifest.json` 缺失、格式不合法、版本不支持时返回业务错误。
- 每个 `db/<table>.json` 必须是 `{ "records": [...] }` 形态。
- 导入必须实际生成且只生成一个 `course`，否则回滚并返回无效课程包错误。
- 导入后 retrieval chunk embedding 会按目标环境 best-effort 重建；向量索引不作为包内强一致资产。

当前错误语义：

| 场景 | HTTP | 错误码 |
| --- | --- | --- |
| 包格式错误、manifest/table 不合法、缺少 course | 422 | `INVALID_IMPORT_PACKAGE` |
| 上传包或解压包超过限制 | 413 | `IMPORT_PACKAGE_TOO_LARGE` |
| 演示课程目录不可用 | 502 | `DEMO_COURSE_CATALOG_UNAVAILABLE` |

---

## 9. 演示课程分发建议

首页“演示课程”统一由后端读取项目公开 assets 仓库目录。前端不要直接硬编码远程路径，而是统一请求后端课程目录接口；公开目录暂不可用时返回空列表，也不影响手动上传 `.atmx` 导入。

推荐在 `aiteachme/assets` 仓库中固定一套公开前缀：

```text
demo-courses/
├── catalog/
│   └── v1/
│       └── index.json
├── atmx/
│   └── <course_slug>.atmx
└── covers/
    └── <course_slug>.png
```

运行时职责：

- 后端读取 `https://raw.githubusercontent.com/aiteachme/assets/main/demo-courses/catalog/v1/index.json`。
- 后端读取 catalog 时必须带 no-cache 请求头和一次性 query，避免拿到旧索引。
- 前端只消费统一后的演示课程目录 API，并在返回课程后展示演示课程区。
- 真正导入时，由后端下载到临时目录后复用同一套 `import_course()` 逻辑。
- 后端只允许课程包 URL 位于固定 `aiteachme/assets` 演示课程前缀下。
- 下载时同时检查 catalog 声明大小、HTTP `Content-Length` 和实际流式写入字节数。
- catalog 可提供 `sha256`，后端下载后校验，不匹配则拒绝导入。
- 云端页面导入的是当前云端账号；本地用户如需导入课程包，走上传 `.atmx` 入口。
- 需要离线分发时，运维侧下载 `.atmx` 后通过前端“上传导入”入口导入。

一句话原则：

> 演示课程主源统一为项目公开 assets 仓库；私有 OSS 不参与公开分发，手动 `.atmx` 导入仍复用同一套导入执行器。

---

## 10. 格式演进规则

数据库后续如果有大改，`.atmx` 兼容性按以下原则处理：

- 不破坏旧 reader 的新增信息，优先放入 manifest 的 `extensions` 或新增可选表。
- 表结构字段新增时，优先保持旧字段可为空或可由导入端补默认值。
- 表名、主键语义、外键语义发生破坏性变化时，需要新增导入兼容分支或升级 `format_version`。
- `format_version` 只在旧 reader 无法安全读取时升级；普通新增字段不应随意升级。
- 不把数据库备份语义塞进 `.atmx`。完整环境迁移应走数据库和对象存储备份链路。

---

## 11. MVP 约束

- `KnowledgeUnit` 的 alias、evidence 和轻量 revision 仍保存在 JSON 字段内，导入导出不拆分子表。
- 导入后不自动创建课程结构表。
- 向量索引属于可重建派生数据，不作为跨环境强一致资产处理。
- 原始上传文件不随 `.atmx` 导出；用户需要跨设备迁移原始资料时，应单独备份文件或重新上传。
