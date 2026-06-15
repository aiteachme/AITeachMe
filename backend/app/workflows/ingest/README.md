# Ingest 工作流

最后更新：2026-06-15

`ingest/` 负责透视引擎：把用户上传的原始资料变成 Digest 可读取、可预览、可检索的 Markdown 和资产目录。

```text
UploadFile
  -> intake
  -> parsing fast_parse
  -> optional deep enhance
  -> retrieval indexing
  -> Digest planner / docgen
```

## 目录

```text
ingest/
  intake/     # 上传、列表、删除、解析派发
  parsing/    # 单文件 fast parse LangGraph
  common/     # Ingest 节点 tracing 等共享辅助
```

对应文档：

- [intake/README.md](intake/README.md)
- [parsing/README.md](parsing/README.md)

## 两层职责

| 层 | 是否 LangGraph | 作用 |
| --- | --- | --- |
| `intake` | 否 | 管理 `RawFile` 生命周期，把文件交给解析链路 |
| `parsing` | 是 | 读取单个 `RawFile`，解析成 Markdown、assets 和元数据 |

## 总流程

## 1. 上传与建档

入口：`save_uploaded_file`, `save_uploaded_files`

输入：`course_id`, `owner_user_id`, `UploadFile`, `parse_request_metadata`

动作：校验扩展名和大小，计算 `content_hash`，写 ContentStore，创建 `RawFile`。

输出：

```text
RawFile.id
RawFile.file_path
RawFile.markdown_path
RawFile.asset_dir
RawFile.status = pending
RawFile.ingest_status = pending
```

## 2. 解析派发

入口：`_start_parse_for_files`, `run_parse_files_background`

输入：`user_id`, `course_id`, `file_ids`

动作：把文件状态推进到解析中，并按并发限制调用 `run_parse_file_workflow`。

输出：

```text
RawFile.status = processing
RawFile.ingest_status = classifying
RawFile.digest_current_step = ingest.parse.queued
```

## 3. 单文件 fast parse

入口：`run_parse_file_workflow`

输入：

```text
user_id
course_id
file_id
```

动作：物化原始文件，文本快通道或分类/计划/解析，最后持久化 Markdown 和 assets。

输出：

```text
parser_used
parse_plan
needs_enhance
error
```

落库字段：

```text
RawFile.parsed_markdown
RawFile.markdown_path
RawFile.asset_dir
RawFile.classification_json
RawFile.parse_metadata_json
RawFile.parser_used
RawFile.quality_score
RawFile.image_count
```

## 4. 后台增强

入口：`parsing/nodes/enhance.py`

输入：Phase 1 产出的 Markdown、assets、分类结果和 `ParsePlan`

动作：对复杂图片/扫描资料做可选 OCR 增强；失败保留 Phase 1 结果。

输出：

```text
RawFile.ingest_status = ready_for_digest 或 enhance_failed
RawFile.digest_current_step = ingest.enhance.completed 或 ingest.enhance.failed
```

## 5. 检索索引

入口：`spawn_index_course_files_background`

输入：解析完成且可检索的 `file_ids`

动作：调用 Digest 侧索引能力，把文件 Markdown 切成检索 chunk。

输出：课程检索索引，可供 Planner、DocGen、Interact 使用。

## 状态约定

Digest 可消费的 `ingest_status`：

```text
fast_parsed
enhancing
ready_for_digest
enhance_failed
```

`ingest` 不做教学规划、不生成知识文档、不构建知识图谱；这些分别属于 `digest/planner`、`digest/docgen`、`digest/kg_doc_sync`。
