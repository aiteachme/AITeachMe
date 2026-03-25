# 04. Ingest 引擎

## 1. 目标与职责

Ingest 负责把原始资料转换成后续所有引擎都能稳定消费的“材料层”。

当前它的职责是：

- 接收上传文件
- 做轻量分类和解析器路由
- 生成稳定 Markdown
- 提取图片 / 附件到共享 `assets/`
- 对提取图片做 OCR / vision 补强
- 把解析状态写回 `raw_file`
- 为下游 `retrieval_chunk / chunk_embeddings / knowledge_document` 做好准备

Ingest 不负责直接产出知识图谱或知识文档，它只负责把材料打磨到可消费状态。

---

## 2. 当前实现落点

| 层 | 当前主模块 |
| --- | --- |
| 前端页面 | `frontend/src/pages/FilesPage.tsx` |
| API | `backend/app/api/files.py` |
| service | `backend/app/services/file_service.py` |
| workflow | `backend/app/workflows/ingest/*` |
| 路径 helper | `backend/app/services/upload_support.py` |
| 核心表 | `raw_file` |

---

## 3. 当前主 Pipeline

| 步骤 | 当前主模块 | 读 DB | 写 DB | 写 FS |
| --- | --- | --- | --- | --- |
| 上传保存 | `file_service.save_uploaded_file()` | 无 | `raw_file` | `temp/`、`raw/` |
| 自动触发解析 | `save_uploaded_files_and_request_parse()` | `raw_file` | `raw_file.status`、`raw_file.ingest_status` | 无 |
| 加载文件与规划 | `workflows/ingest/nodes/file.py` | `raw_file` | `raw_file` 分类字段 | 无 |
| 实际解析 | `workflows/ingest/nodes/parse.py` | `raw_file` | `raw_file.ingest_status=validating` | `raw_markdowns/`、`assets/` |
| 成功/失败收尾 | `workflows/ingest/nodes/finalize.py` | `raw_file` | `raw_file` 最终字段 | 无 |
| 下游材料化 | `workflows/digest/kg/support.py` | `raw_file` | `retrieval_chunk`、`chunk_embeddings` | 读取 `raw_markdowns/` |

---

## 4. 当前本地正式产物

单个原始文件解析完成后，会得到：

- `data/<subject>/raw_files/<raw_file_id>.<ext>`
- `data/<subject>/raw_markdowns/<raw_file_id>.md`
- `data/<subject>/assets/<asset_name_prefix>__*.png|jpg|...`

这里最重要的变化是：

1. `raw_markdowns/` 取代旧 `markdown/`
2. `assets/` 现在是整个 subject 共享的扁平目录，不再使用 `assets/<file_id>/`

---

## 5. 共享 `assets/` 的目录策略

当前实现采用：

- 一个 subject 只有一个 `assets/`
- 每个原始文件用 `asset_name_prefix` 作为命名前缀

示例：

`linear_algebra__file_123abc__p2_img1_9fcd2a1b8e.png`

这样做的目的是：

- 保持所有 Markdown 都是一级目录
- 让 `raw_markdowns/` 和 `knowledge_markdowns/` 都能用同一套相对路径
- 删除单个文件时可以按前缀清理本文件图片，而不会误删整科目 assets

---

## 6. Markdown 与图片引用规则

Ingest 统一把 Markdown 里的图片引用规范成：

`../assets/<flattened_asset_name>`

这条规则同时适用于：

- `raw_markdowns/*.md`
- `knowledge_markdowns/*.md`

当前所有 Markdown 文件都必须保持一级目录，避免多层目录导致图片相对路径混乱。

---

## 6.1 解析与分流原则

Ingest 不应把“关键词命中”当成主流程。更合理的解析与分流顺序应该是：

1. 先按文件格式和页面结构决定解析主链路
2. 再按正文密度、版式复杂度、图片/公式占比决定是否追加 OCR / vision
3. 最后才把标题、章节名、术语词面当成弱提示

只有像“第 X 章”“定义”“定理”“证明”这类显式结构标记，才适合作为较强信号。

---

## 7. OCR / Vision 补强策略

### 7.1 为什么必须补这一步

仅靠传统解析器，经常会得到这类内容：

`picture [176 x 30] intentionally omitted`

这对公式题、试卷扫描件、图表型资料几乎不可用。

### 7.2 当前实现

当前 ingest 在 parser 后处理阶段做两类增强：

1. 页面级 OCR  
   适用于扫描 PDF 页。
2. asset 级 OCR  
   针对提取出来的图片做 vision OCR，再回填到 Markdown。

asset OCR 的效果包括：

- 把 `intentionally omitted` 之类占位符替换成真实图片引用
- 把图片 OCR 内容补进 Markdown
- 在没有占位符时，按需追加 `Extracted Image OCR` 补充段落

### 7.3 设计思路

这套思路和 MinerU 的“Markdown + sidecar images”方向是一致的：

- 正文是 Markdown
- 图片作为旁路资产单独落盘
- Markdown 只保留稳定引用

不同点在于：

- MinerU 常按一次输出目录组织 sidecar 图片
- 我们当前按 subject 共享 `assets/`，再用 `asset_name_prefix` 做确定性隔离

---

## 8. LangGraph 节点与表写入

### 8.1 `build_classify_file_node`

写表：

- `raw_file`

主要字段：

- `estimated_pages`
- `detected_language`
- `classification_result`
- `ingest_status`

### 8.2 `build_parse_file_node`

写表：

- `raw_file.ingest_status`

写文件：

- `raw_markdowns/<raw_file_id>.md`
- `assets/<asset_name_prefix>__*.png|jpg|...`

解析元数据会进入 workflow state，并在 finalize 成功时统一写回 `raw_file.parse_metadata`。

### 8.3 `build_finalize_success_node`

写表：

- `raw_file`

主要字段：

- `markdown_path`
- `asset_dir`
- `status`
- `error_message`
- `content_hash`
- `file_size_bytes`
- `estimated_pages`
- `detected_language`
- `classification_result`
- `parse_metadata`
- `image_count`
- `ingest_status`

### 8.4 `build_finalize_failure_node`

写表：

- `raw_file`

主要字段：

- `status = failed`
- `error_message`
- `ingest_status = failed`

---

## 9. 与 Digest 的桥接关系

Ingest 结束后，下游并不是直接消费 `raw_file` 本身，而是消费：

`raw_file.parsed_markdown -> retrieval_chunk -> chunk_embeddings`

这个桥接发生在：

`backend/app/workflows/digest/kg/support.py::prepare_chunk_ids_for_files`

所以当前的正式材料层应理解为：

`RawFile -> raw_markdowns / assets -> RetrievalChunk`

---

## 10. 当前结论

Ingest 现在最核心的价值不是“上传成功”，而是把资料稳稳转换成统一材料层：

- `raw_file` 保存结构化解析状态
- `raw_files/` 保存原始文件
- `raw_markdowns/` 保存正式解析正文
- `assets/` 保存共享扁平图片资产
- OCR / vision 补强负责把图片里的信息真正带回 Markdown

而且这层应坚持“语义与版式优先，关键词兜底”的策略：不要机械依赖章节名或词面匹配去决定解析流程。

只要这层稳定，后面的知识图谱、知识文档、对话和测评都会明显更可靠。
