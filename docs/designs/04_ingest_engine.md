# 04. Ingest 引擎

## 1. 目标与职责

Ingest 负责把原始资料接入系统并转换成下游稳定可消费的材料层。它解决的是“材料能否被可靠处理”的问题，而不是“知识如何组织”的问题。

当前目标包括：

- 接收多格式文件
- 进行轻量分类与解析路由
- 输出稳定 Markdown
- 提取图片等资产
- 把解析状态写回 `raw_file`
- 为后续 `Document / DocumentChunk / chunk_embeddings` 桥接准备好正式产物

---

## 2. 当前实现落点

- 前端页面：`frontend/src/pages/UploadPage.tsx`
- 后端资源组：`files`
- 业务入口：`backend/app/services/file_service.py`
- 工作流编排：`backend/app/workflows/ingest/*`
- 关键模型：`RawFile`

当前 Ingest 的编排真相已经在 `workflows/ingest/*`，不再以旧 `agents/ingest/*` 为主。

---

## 3. 当前主 Pipeline

| 步骤 | 当前主模块 | 输入 | 输出 |
| --- | --- | --- | --- |
| 1. 文件保存 | `file_service.save_uploaded_files` | `subject`、上传文件 | 本地原始文件、`raw_file` |
| 2. 解析触发 | `file_service.request_files_parse` | `file_ids` | 待处理文件集合 |
| 3. 后台分发 | `file_service.run_parse_files_background` | `subject`、文件 ID 列表 | 单文件 workflow 调度 |
| 4. 原文件加载 | `workflows/ingest/nodes/file.py` | `raw_file` ID | 路径、文件元信息、状态 |
| 5. 指纹与分类 | `workflows/ingest/nodes/file.py` | 文件内容、扩展名 | hash、大小、分类结果、解析计划 |
| 6. 实际解析 | `workflows/ingest/nodes/parse.py` | 文件路径、asset 目录、解析计划 | Markdown、提取资产、解析元数据 |
| 7. 成功/失败收尾 | `workflows/ingest/nodes/finalize.py` | 解析结果或错误 | 更新 `raw_file`、发布事件 |
| 8. 下游材料桥接 | `workflows/digest/kg/support.py` | `raw_file.markdown_path` | `document`、`document_chunk`、`chunk_embeddings` |

这里最重要的现实变化是：当前代码里的“材料化桥接”已经不是纯设计空白，而是在 Digest graph 准备阶段通过 `ensure_document_chunks_for_file()` 实际完成。

---

## 4. 核心设计原则

### 4.1 先稳材料，再谈语义

Ingest 首要目标是让资料稳定变成规范化材料，而不是过早承担知识抽取职责。

### 4.2 多解析器路由优于万能解析器

不同格式应按材料类型选择解析器链，再统一输出到 Markdown。

### 4.3 正式产物必须可落盘

Ingest 当前是双写设计：

- 数据库保存结构化状态
- 本地文件系统保存 Markdown 与资产

这对调试和下游复用都很重要。

### 4.4 材料层必须独立存在

`RawFile` 不应直接被所有下游消费；真正共享的桥接层应该是：

`RawFile -> Markdown / Assets -> Document -> DocumentChunk`

### 4.5 来源与资产要可追溯

图片、附件、路径、来源文件 ID 都属于正式业务信息，而不是可忽略附属数据。

---

## 5. 数据库写入对象

当前 Ingest 直接负责更新：

- `raw_file`

关键写入字段包括：

- `file_path`
- `markdown_path`
- `asset_dir`
- `status`
- `ingest_status`
- `content_hash`
- `file_size_bytes`
- `estimated_pages`
- `detected_language`
- `classification_result`
- `parse_metadata`
- `image_count`
- `error_message`

Ingest 本身不直接写：

- `document`
- `document_chunk`
- `chunk_embeddings`

但它通过正式产物路径为下游材料化提供输入。

---

## 6. 本地落盘对象

当前 Ingest 的正式本地产物包括：

- `data/<subject>/raw/<file_id>.<ext>`
- `data/<subject>/markdown/<file_id>.md`
- `data/<subject>/assets/<file_id>/...`

这些文件不是“临时缓存”，而是当前本地优先架构下的正式业务产物。

---

## 7. 关键状态推进

当前典型状态推进为：

`pending -> processing -> completed/failed`

同时伴随 `ingest_status` 的业务语义推进：

- 待解析
- validating
- ready_for_digest
- failed

开发时应优先保证这两层状态一致：

- 技术执行状态
- 业务可消费状态

---

## 8. 节点到表责任

| 节点 / 模块 | 读 DB | 写 DB | 写 FS |
| --- | --- | --- | --- |
| `nodes/file.py` | `raw_file` | `raw_file` | 读取原始文件 |
| `nodes/parse.py` | 无 | 更新解析元信息准备态 | `markdown/`、`assets/` |
| `nodes/finalize.py` | `raw_file` | `raw_file` | 无新增正式产物 |
| `digest/kg/support.py::ensure_document_chunks_for_file` | `raw_file`、`document`、`document_chunk` | `document`、`document_chunk`、`chunk_embeddings` | 读取 `markdown/` |

---

## 9. 开发关注点

### 9.1 Ingest 和 Digest 的桥接已经在代码里，但要继续文档化

很多历史文档把 `Document / Chunk` 说成未来计划，当前代码已经做了这件事，后续文档和实现都要以此为准。

### 9.2 开发阶段保留本地正式产物是刻意设计

Markdown 和 asset 本地落盘不是多余行为，而是本地优先和可调试性的基础。

### 9.3 新的调试快照统一入 `debug/`

如果后续为解析质量、分类结果或 parser fallback 增加更多调试摘要，应统一写入：

`data/<subject>/debug/ingest.file.parse/<run_or_job_id>/`

---

## 10. 总结

Ingest 的真正价值不是“把文件上传进来”，而是把原始资料稳稳转换成后续所有引擎都能消费的材料层。当前它已经形成清晰边界：

- `raw_file` 保存结构化接入状态
- `raw/markdown/assets` 保存正式文件产物
- 下游通过 Digest graph 准备阶段桥接到 `Document / Chunk / Embedding`

只要继续稳住这三层，后面的图谱、对话、测评和画像都会更可靠。
