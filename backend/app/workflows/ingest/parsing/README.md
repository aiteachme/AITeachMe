# Ingest Parsing 链路

最后更新：2026-06-15

职责：单文件 fast parse，把 `RawFile` 的原始文件解析成 Markdown、assets 和解析元数据。

```text
输入: user_id + course_id + file_id
输出: parsed_markdown + assets + parse metadata + ingest_status
```

## 主流程

```text
load_raw_file
  -> compute_fingerprint
  -> classify_file
  -> plan_parse
  -> parse_file
  -> finalize_success
```

错误分支：

```text
任意节点 error -> finalize_failure
```

文本快通道：

```text
compute_fingerprint -> parse_file -> finalize_success
```

## 入口

`run_parse_file_workflow`

输入：

```text
user_id
course_id
file_id
```

输出：

```text
filename
filetype
parser_used
parse_plan
needs_enhance
error
```

## 1. `load_raw_file`

输入：`user_id`, `course_id`, `file_id`

动作：读取 `RawFile`，物化原始文件到临时目录，解析 provider 参数，准备 Markdown/assets 输出路径。

输出：

```text
filename
filetype
file_path
temp_dir
local_markdown_path
local_asset_dir
record_markdown_path
record_asset_dir
requested_parser_provider
parse_decision
is_text_fast_path
text_category
text_language_hint
```

关键字段：

| 字段 | 作用 |
| --- | --- |
| `parse_decision` | provider 可用性和用户选择的解析策略 |
| `is_text_fast_path` | 是否跳过分类，直接按 UTF-8 文本处理 |
| `asset_link_prefix` | Markdown 中图片引用的相对路径前缀 |

## 2. `compute_fingerprint`

输入：`file_path`, `is_text_fast_path`

动作：计算文件 SHA256 和大小；文本文件直接路由到 `parse_file`。

输出：

```text
content_hash
file_size_bytes
```

## 3. `classify_file`

输入：`file_path`, `filetype`, `file_id`, `user_id`

动作：对非文本文件做轻量分类，识别页数、语言、结构和复杂度。

输出：

```text
classification
classification_payload
estimated_pages
detected_language
```

落库字段：

```text
RawFile.classification_json
RawFile.estimated_pages
RawFile.detected_language
RawFile.ingest_status = fast_parsing
```

## 4. `plan_parse`

输入：

```text
classification
parse_decision
requested_parser_provider
filetype
file_size_bytes
```

动作：生成 `ParsePlan`，决定解析模式和 parser chain。

输出：

```text
parse_plan.mode
parse_plan.parser_chain
parse_plan.decision_reason
parse_plan.options
```

## 5. `parse_file`

输入：

```text
file_path
parse_plan
parse_decision
classification
asset_link_prefix
asset_name_prefix
```

动作：进入文本快通道、外部 provider 或本地 parser chain；规范 Markdown 图片引用并抽取 assets。

输出：

```text
parsed_markdown
parse_metadata
parser_used
attempted_parsers
parser_elapsed_s
markdown_chars
image_count
quality_score
needs_enhance
needs_quality_reparse
needs_asset_ocr
```

关键字段：

| 字段 | 作用 |
| --- | --- |
| `parser_used` | 最终成功的解析器 |
| `attempted_parsers` | 尝试过的解析器链路 |
| `quality_score` | 当前 Markdown 可用性评分 |
| `needs_enhance` | 是否触发后续 OCR/视觉增强 |

外部解析超时：

- MinerU 沿用快速回退预算，默认 25 秒内未拿到最终结果则按策略 fallback。
- PaddleOCR Cloud 是异步 job API，默认等待预算为 25 秒，可通过 `PADDLE_OCR_PARSE_TIMEOUT_S` 配置，范围 15-600 秒。
- PaddleOCR 默认每 1 秒轮询一次任务状态，尽快发现服务端已完成的 job 并进入结果下载。
- PaddleOCR 模型默认由后端代码决定，可通过 `PADDLE_OCR_MODEL` 覆盖，便于对比不同模型的速度和质量。
- PaddleOCR 默认使用原单任务链路；设置 `PADDLE_OCR_PARSE_MODE=parallel` 后，大 PDF 会按 `PADDLE_OCR_CHUNK_MAX_PAGES`（默认 10）拆分并以 `PADDLE_OCR_CHUNK_CONCURRENCY`（默认 4）并发提交，所有分块完成后按页序合并 Markdown。
- PaddleOCR 如果已经拿到结果 URL 并进入下载落地阶段，会重新给下载阶段 10 秒宽限；宽限内完成就算 PaddleOCR 成功，宽限后仍未完成才按超时 fallback。

## 6. `finalize_success`

输入：`parsed_markdown`, `local_asset_dir`, `parse_metadata`, `parser_used`, `quality_score`

动作：上传 Markdown 和 assets，刷新 `raw_file_asset`，写回 `RawFile`。

输出：

```text
RawFile.status = completed
RawFile.parsed_markdown
RawFile.markdown_path
RawFile.asset_dir
RawFile.parser_used
RawFile.parse_metadata_json
RawFile.quality_score
RawFile.image_count
```

状态：

```text
needs_enhance = true  -> ingest_status = fast_parsed
needs_enhance = false -> ingest_status = ready_for_digest
```

## 7. `finalize_failure`

输入：`error`, `file_id`, `user_id`, `temp_dir`

动作：写回失败状态和错误信息，并清理临时目录。

输出：

```text
RawFile.status = failed
RawFile.ingest_status = failed
RawFile.parse_error_message
RawFile.digest_current_step = ingest.parse.failed
```

## 后台增强

入口：`nodes/enhance.py`

输入：Phase 1 Markdown、assets、`classification_json`、`ParsePlan`

动作：可选调用 OCR/Vision 模型增强图片和扫描内容。

输出：

```text
ingest_status = ready_for_digest 或 enhance_failed
digest_current_step = ingest.enhance.completed 或 ingest.enhance.failed
```

## 模型策略

OCR/Vision 模型选择和 token 预算统一在 `lib/model_policy.py`。

LangSmith 节点展示名和读写字段在 `graph.py` 的 `STEP_DETAILS`。
