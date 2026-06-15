# Ingest Intake

最后更新：2026-06-15

职责：管理上传文件的接入层，包括上传、列表、删除、解析派发和解析后索引派发。

```text
输入: UploadFile / file_ids / course_id / user_id
输出: RawFile + FilesUploadData + parse background task
```

## 主流程

```text
validate_upload
  -> save_raw_file
  -> start_parse
  -> run_parse_files_background
  -> index_ready_files
```

## 1. 上传保存

入口：`save_uploaded_file`, `save_uploaded_files`

输入：

```text
course_id
owner_user_id
files
parse_request_metadata
origin_course_name
```

动作：校验扩展名、总大小和解析参数；读取上传内容；生成稳定 `file_id`；写入 ContentStore。

输出：

```text
RawFile.id
RawFile.filename
RawFile.content_hash
RawFile.file_path
RawFile.markdown_path
RawFile.asset_dir
RawFile.status = pending
RawFile.ingest_status = pending
```

关键字段：

| 字段 | 作用 |
| --- | --- |
| `parse_request_metadata` | 前端传入的解析偏好，例如 MinerU/PaddleOCR |
| `parse_request_signature` | 解析参数签名，用于判断是否可复用历史解析 |
| `file_id__safe_stem` | 存储路径片段，保证文件名可读且稳定 |

## 2. 解析排队

入口：`_start_parse_for_files`

输入：`owner_user_id`, `course_id`, `file_ids`

动作：校验文件属于当前用户/课程，并从 `pending` 推进到 `processing`。

输出：

```text
RawFile.status = processing
RawFile.ingest_status = classifying
RawFile.digest_current_step = ingest.parse.queued
```

## 3. 后台解析

入口：`run_parse_files_background`

输入：`user_id`, `course_id`, `file_ids`, `background_task_registry`

动作：按 `DEFAULT_PARSE_CONCURRENCY` 并发调用 `run_parse_file_workflow`。

输出：每个文件的 `IngestParseState`

失败处理：单文件失败会写回 `RawFile` 失败状态，不阻断同批其他文件。

## 4. 检索索引派发

入口：`spawn_index_course_files_background`

输入：`user_id`, `course_id`, `file_ids`, `reason`

动作：筛出已解析且有 Markdown 的文件，调用 Digest 索引能力。

输出：可被 RAG 使用的课程文件索引。

可索引状态：

```text
fast_parsed
enhancing
ready_for_digest
enhance_failed
```

## 5. 删除

入口：`delete_raw_file`

输入：`file_id`, `course_id`, `user_id`

动作：删除 `RawFile` 记录和关联运行时产物。

输出：文件删除结果。

## 边界

`intake` 不解析文件正文，只保存文件和调度解析。

`intake` 不生成知识文档，也不直接更新知识图谱。

真实单文件解析在 [../parsing/README.md](../parsing/README.md)。
