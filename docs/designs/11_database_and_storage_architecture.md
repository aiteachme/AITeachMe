# 11. Ingest 与 Digest 数据库与存储架构

## 1. 文档定位

这篇文档不是“当前全库表清单”，而是 **Ingest + Digest 的数据库重构规范**。目标是让后续重构可以直接照着做，而不是看完之后还需要重新猜：

- Ingest 的稳定身份对象是什么
- 解析尝试、解析结果、材料层、资产层应该怎么拆
- Digest 的任务表、输入表、图谱表、课程表、知识文档表应该怎么建
- 哪些内容进数据库，哪些内容只写本地
- 现有代码里的哪些表和字段应该保留、收缩、拆分或淘汰

本文档针对开发阶段，**默认接受不保留旧 Ingest / Digest 数据设计包袱，允许直接重构 schema**。

不在本文档主范围内的内容：

- chat / interact
- exam / assessment
- profile

它们只在需要引用 `document_chunk` 或课程快照时被动提及。

---

## 2. 先给结论

### 2.1 这次重构最重要的 8 个决定

1. **`raw_file` 只保留“原始文件身份”职责，不再混放解析过程状态。**
2. **新增 `ingest_parse_job`，把解析状态、解析器、质量分、失败原因、调试目录全部移到 job 表。**
3. **`document` 成为 Ingest 的正式 canonical text 层，下游一律基于 `document` / `document_chunk` 工作。**
4. **新增 `document_asset`，不再只靠 `asset_dir` 和文件系统猜图片资源。**
5. **`document_chunk` 要增强成真正的 TextUnit 表，补齐 chunk hash、token 数、前后关系、source locator。**
6. **Digest 的“输入文件列表 JSON”全部改成关系表，不再用 `*_ids_json` 存输入集合。**
7. **知识文档和解析 Markdown 都以数据库文本为 canonical source，本地 `.md` 文件只是导出/调试副本。**
8. **本地文件系统只对两类东西保留真相地位：原始二进制文件、调试/导出产物。**

### 2.3 长期稳定性原则

这次设计额外要求一条很重要的原则：

> **以后就算 parser、chunker、extractor、LLM、workflow 节点拆法全变了，主表也最好几乎不用改。**

所以数据库设计必须遵守下面几条规则：

1. **表表达业务语义，不表达当前实现细节。**  
   应该有 `raw_file`、`ingest_parse_job`、`document`、`document_chunk`、`graph_digest_job` 这种表；不应该有“markitdown_result”或某个 prompt 名字式表。
2. **稳定对象和生成方法分离。**  
   `raw_file`、`document`、`document_chunk`、`knowledge_node`、`teaching_unit` 是稳定对象；  
   parser、OCR、VLM、clusterer、extractor 只是生成这些对象的方法。
3. **方法变化优先落到 `run_config_json` / `run_metrics_json` / `run_trace_json`，而不是不断加新列。**
4. **job 表只表达业务阶段，不绑定 workflow 节点名。**  
   节点顺序以后可以改，但 `ingest_parse_job`、`graph_digest_job`、`docgen_job` 这些业务阶段不应该频繁改。
5. **下游永远消费 canonical output，不消费生成方法。**  
   下游永远面向 `document` / `document_chunk` / `knowledge_node_revision` / `curriculum_snapshot`。
6. **集合关系一律关系表，不用 JSON 集合字段。**  
   这是最关键的长期稳定性基础。

### 2.2 这次重构最重要的边界

| 类别 | canonical truth 放哪 | 本地文件扮演什么角色 |
| --- | --- | --- |
| 原始文件 | 文件系统 / 未来对象存储 | 正式真相 |
| 解析后的 Markdown | 数据库 `document.body_markdown` | 导出副本 / 调试副本 |
| 图片与提取资产 | 数据库 `document_asset` 元数据 + 文件系统/对象存储二进制 | 二进制真相 |
| chunk | 数据库 `document_chunk` | 不额外落文本文件 |
| chunk embedding | 向量索引 `chunk_embeddings` | 无 |
| 图谱 / 课程 / 知识文档 | 数据库 | 可选导出 / 调试 |

---

## 3. 当前代码里的主要问题

当前代码已经有一套可运行的 Ingest / Digest 链路，但从数据库设计角度看，存在几个明显问题。

### 3.1 `raw_file` 过载

当前 `raw_file` 同时承担了四种职责：

- 原始文件身份
- 解析任务状态
- 解析结果路径
- 一部分解析质量元信息

这会导致几个问题：

- 一个文件多次解析时，没有独立 parse attempt 历史
- 失败解析会污染稳定文件身份对象
- 解析器、回退链、错误原因、质量指标都堆在一张表里

### 3.2 解析结果没有独立资产表

当前图片资源主要体现在：

- `raw_file.asset_dir`
- `data/<subject>/assets/<file_id>/...`

问题是数据库里没有稳定的资产 manifest：

- 无法直接查询某个文档有哪些图片
- 无法记录图片宽高、mime、hash、来源页码、来源块
- 后续证据、知识文档、前端引用都只能依赖路径猜测

### 3.3 `document` 的 canonical truth 不够明确

当前代码里：

- `raw_file.markdown_path` 指向本地 Markdown 文件
- `document.markdown_content` 又保存一份完整文本

这意味着“到底哪份是正式真相”并没有被设计层明确下来。

这次重构的决定是：

- 对下游业务来说，**数据库 `document.body_markdown` 是 canonical source**
- 本地 Markdown 文件只是导出/调试产物

### 3.4 `document_chunk` 还是偏轻量

当前 `document_chunk` 只有：

- `document_id`
- `title`
- `level`
- `header_path`
- `chunk_index`
- `content`

这对于简单检索足够，但对后续稳定 digest 不够。缺少：

- `content_hash`
- `token_count`
- `char_count`
- `prev_chunk_id` / `next_chunk_id`
- `page_start` / `page_end`
- `source_locator_json`
- `parse_job_id`

### 3.5 Digest job 仍在用 JSON 存输入集合

当前代码里至少有这些字段：

- `graph_digest_job.input_file_ids_json`
- `docgen_job.input_file_ids_json`
- `knowledge_doc.source_file_ids`

这类字段在开发阶段很方便，但一旦系统变复杂，就会出现：

- 无法方便 join / filter / trace lineage
- 输入集合难做去重和增量判断
- 无法优雅表达“这个 doc 来源于哪些 chunk，而不是哪些文件”

### 3.6 Digest 缺少统一的 lineage 视角

当前图谱和文档流程都有 lineage，但还不够统一。理想状态应该能回答：

- 一个 `knowledge_node_revision` 来自哪些 chunk
- 一个 `knowledge_doc` 来自哪些 chunk
- 这个课程快照是基于哪次图谱构建派生的
- 这个 graph/docgen job 处理了哪些 `document`

---

## 4. 参考设计原则

这次重构不是闭门造车，主要吸收了几类成熟系统的共同模式：

- **GraphRAG**：把 `documents`、`text_units`、`entities`、`relationships` 分层建模，而不是把“文件 -> 图谱”写成一团。  
  参考：
  - https://microsoft.github.io/graphrag/index/inputs/
  - https://microsoft.github.io/graphrag/index/outputs/
  - https://microsoft.github.io/graphrag/index/default_dataflow/
- **LlamaIndex**：`Document -> Node` 的父子层级清晰，Node 继承文档 metadata；Markdown parser 明确保留 header path 与前后关系。  
  参考：
  - https://docs.llamaindex.ai/en/v0.10.23/module_guides/loading/documents_and_nodes/
  - https://docs.llamaindex.ai/en/stable/api_reference/node_parsers/markdown/
- **Haystack**：Document Store 里的文档必须有稳定 ID 和 metadata，写入/覆盖语义清楚。  
  参考：
  - https://docs.haystack.deepset.ai/docs/document-store
- **SQLite 官方 WAL**：本地优先很适合，但必须承认“同机、单 writer、需要 checkpoint 策略”的边界。  
  参考：
  - https://sqlite.org/wal.html

这些参考共同指向一个结论：

**不要把文件、解析任务、解析结果、chunk、图谱、课程视图混成几张大表；而要分成“稳定身份层 -> 尝试/任务层 -> 派生产物层 -> 消费视图层”。**

---

## 5. vNext 存储总架构

### 5.1 逻辑分层

Ingest + Digest 的目标数据层建议拆成 6 层：

1. **Source Layer**  
   原始文件身份与存储位置
2. **Parse Layer**  
   解析尝试、解析质量、解析失败信息
3. **Material Layer**  
   标准化文档、资产、chunk、embedding
4. **Graph Layer**  
   节点、边、修订、证据、图谱任务
5. **Curriculum Layer**  
   Teaching Unit、Theme Tree、Prereq DAG、Snapshot
6. **Readable Knowledge Layer**  
   面向用户的知识文档与来源映射

### 5.2 物理存储策略

| 层 | 当前本地实现 | 中心化未来形态 |
| --- | --- | --- |
| Source Layer | 本地文件系统 | OSS / MinIO |
| Parse / Material / Graph / Curriculum / Readable | SQLite | PostgreSQL |
| Embedding | sqlite-vec | pgvector |

### 5.3 什么会经常变，什么不应该跟着变

| 容易变化的东西 | 不应该因此改主表结构的东西 |
| --- | --- |
| 解析器从 `markitdown` 换成 VLM/OCR/混合链 | `raw_file`、`ingest_parse_job`、`document` |
| chunk 规则从标题切块换成语义切块 | `document_chunk` |
| 图谱抽取 prompt / 模型 / 聚类策略变化 | `knowledge_node*`、`knowledge_edge*`、`evidence_link` |
| 课程派生算法变化 | `teaching_unit*`、`theme_tree*`、`prereq_dag*` |
| 文档生成 writer / review pipeline 变化 | `knowledge_doc*` |

也就是说，数据库应该更多表达：

- 输入输出契约
- lineage
- 当前生效版本
- 快照

而不是表达“今天这段代码具体怎么实现的”。

---

## 6. Ingest vNext 数据模型

## 6.1 `raw_file`

### 角色

保留当前表名以减少代码改动，但**语义重定义**为：

> 原始文件身份对象，不再承担解析 job 状态。

### 推荐字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | PK | 文件 ID |
| `subject` | indexed str | 工作空间 |
| `filename` | str | 用户看到的名字 |
| `filetype` | str | mime / extension 归一化值 |
| `storage_backend` | str | `local` / `oss` / `minio` |
| `storage_uri` | str | 原始文件存储位置 |
| `content_hash` | str | SHA-256 |
| `file_size_bytes` | int | 大小 |
| `source_kind` | str | `upload` / `import` / `generated` |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |
| `deleted_at` | datetime nullable | 软删除 |

### 应从 `raw_file` 移出的字段

以下字段不再属于稳定文件身份，应迁到 `ingest_parse_job` 或 `document`：

- `markdown_path`
- `asset_dir`
- `status`
- `error_message`
- `estimated_pages`
- `detected_language`
- `classification_result`
- `quality_score`
- `parse_metadata`
- `image_count`
- `ingest_status`

### 推荐约束

- `index(subject, created_at desc)`
- `index(subject, content_hash)`
- 开发阶段可选 `unique(subject, content_hash, deleted_at is null)` 作为去重约束

---

## 6.2 `ingest_parse_job`（新表）

### 角色

表示“一次解析尝试”。这是当前 schema 最缺的一层。

### 推荐字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | PK | 解析 job ID |
| `subject` | indexed str | 工作空间 |
| `raw_file_id` | FK | 来源文件 |
| `status` | str | `pending/running/completed/failed/cancelled` |
| `current_step` | str nullable | `classify/parse/canonicalize/persist/...` |
| `producer_kind` | str | `parser` / `ocr` / `hybrid` |
| `producer_name` | str | 当前使用的方法名 |
| `producer_version` | str | 方法版本 |
| `run_config_json` | str | 本次运行配置 |
| `run_trace_json` | str | 实际尝试链、fallback、关键中间轨迹 |
| `detected_language` | str nullable | 检测语言 |
| `estimated_pages` | int nullable | 页数 |
| `quality_score` | float nullable | 0-1 |
| `quality_metrics_json` | str | 细分质量指标 |
| `image_count` | int | 提取图片数量 |
| `error_code` | str nullable | 错误类别 |
| `error_message` | str nullable | 错误详情 |
| `debug_dir` | str nullable | 调试快照目录 |
| `started_at` | datetime nullable | 开始时间 |
| `finished_at` | datetime nullable | 结束时间 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

### 推荐约束

- `index(raw_file_id, created_at desc)`
- `index(subject, status)`
- 部分唯一约束：同一 `raw_file_id` 同时只能有一个 `running` job

### 为什么必须单独建表

因为你后续一定会遇到：

- 同一文件重新解析
- parser fallback 结果对比
- 解析失败重试
- 质量回归验证

没有独立 parse job，后面都会很难做。

同时这里故意不用一堆 parser 专属字段，而是采用：

- `producer_kind`
- `producer_name`
- `producer_version`
- `run_config_json`
- `run_trace_json`

就是为了以后你把实现从：

- 规则解析
- OCR
- VLM
- 多路投票

来回切换时，主表结构都不用跟着改。

---

## 6.3 `document`

### 角色

`document` 是 Ingest 的 canonical material object。下游 Digest、Interact 都应该只面向它，而不是面向文件路径。

### 推荐字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | PK | 文档 ID |
| `subject` | indexed str | 工作空间 |
| `raw_file_id` | FK | 来源原始文件 |
| `parse_job_id` | FK | 来源解析尝试 |
| `title` | str | 文档标题 |
| `body_markdown` | long text | canonical Markdown |
| `body_text_hash` | str | Markdown hash |
| `language` | str nullable | 文档语言 |
| `page_count` | int nullable | 页数 |
| `chunk_count` | int | chunk 数量 |
| `asset_count` | int | 资产数量 |
| `status` | str | `active/superseded/failed` |
| `export_markdown_uri` | str nullable | 本地/对象存储导出路径 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

### 关键决定

- `document.body_markdown` 是 canonical truth
- `export_markdown_uri` 只是导出副本路径
- 不再让 `raw_file.markdown_path` 承担下游真相角色
- `document` 只表达“最终标准化文档长什么样”，不表达“它是怎么被解析出来的”

### 推荐约束

- `unique(parse_job_id)`：一次成功 parse job 产出一份 document
- `index(raw_file_id, status)`
- `index(subject, updated_at desc)`

---

## 6.4 `document_asset`（新表）

### 角色

保存文档提取资产的 metadata。文件二进制仍在本地或对象存储，但数据库里必须有 manifest。

### 推荐字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | PK | 资产 ID |
| `document_id` | FK | 所属文档 |
| `asset_index` | int | 文档内序号 |
| `asset_kind` | str | `image/table/attachment/formula` |
| `storage_backend` | str | `local/oss/minio` |
| `storage_uri` | str | 资产路径 |
| `mime_type` | str | mime |
| `content_hash` | str nullable | 文件 hash |
| `width` | int nullable | 宽 |
| `height` | int nullable | 高 |
| `source_locator_json` | str | 页码/段落/块位置 |
| `caption` | str nullable | 标题或说明 |
| `created_at` | datetime | 创建时间 |

### 推荐约束

- `unique(document_id, asset_index)`
- `index(document_id, asset_kind)`

---

## 6.5 `document_chunk`

### 角色

这是当前项目最重要的材料桥接层。它的职责不只是“切一段文本”，而是成为：

- RAG 检索单位
- 图谱抽取单位
- 证据引用单位
- 知识文档来源单位

### 推荐字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | PK | chunk ID |
| `document_id` | FK | 所属文档 |
| `parse_job_id` | FK | 来源解析 job |
| `chunk_index` | int | 顺序号 |
| `chunk_kind` | str | `paragraph/header/list/table/code/...` |
| `title` | str | 当前块标题 |
| `level` | int | 标题层级 |
| `header_path` | str | 章节路径 |
| `content` | long text | chunk 正文 |
| `content_hash` | str | chunk hash |
| `char_count` | int | 字符数 |
| `token_count` | int nullable | token 数 |
| `prev_chunk_id` | FK nullable | 前向邻接 |
| `next_chunk_id` | FK nullable | 后向邻接 |
| `start_offset` | int nullable | 在文档文本中的起点 |
| `end_offset` | int nullable | 在文档文本中的终点 |
| `page_start` | int nullable | 起始页 |
| `page_end` | int nullable | 结束页 |
| `source_locator_json` | str | 更详细来源定位 |
| `embedding_status` | str | `pending/completed/failed` |
| `created_at` | datetime | 创建时间 |

### 推荐约束

- `unique(document_id, chunk_index)`
- `index(document_id, header_path)`
- `index(parse_job_id)`

### 参考依据

这一层本质上就是 GraphRAG 的 `TextUnit` 和 LlamaIndex 的 `Node`。换句话说，它不应该再只是“切块缓存表”，而应该是 **一等材料对象**。

### 未来兼容性要求

无论未来切块方式变成：

- 标题切块
- 语义切块
- token window
- 图文混合块

`document_chunk` 主结构都不应该再改。变化只应该落在：

- `chunk_kind`
- `source_locator_json`
- `run_config_json`（如果需要，则挂回 parse job）

---

## 6.6 `chunk_embeddings`

### 角色

保留 sqlite-vec 虚拟表设计，但语义收紧为：

> 只保存 `document_chunk.id -> embedding` 的向量索引，不承载任何业务元数据。

### 推荐字段

- `chunk_id INTEGER PRIMARY KEY`
- `embedding FLOAT[dim]`

### 关键约束

- 生命周期跟随 `document_chunk`
- 删除或重建 chunk 时必须同步重建 embedding

---

## 7. Digest vNext 数据模型

## 7.1 `graph_digest_job`

### 角色

表示一次图谱构建运行。

### 推荐字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | PK | job ID |
| `subject` | indexed str | 工作空间 |
| `run_key` | str unique | 幂等/重试键 |
| `status` | str | `pending/running/completed/failed` |
| `current_step` | str nullable | 当前阶段 |
| `progress` | int | 0-100 |
| `strategy_name` | str | 当前构建策略名 |
| `strategy_version` | str | 策略版本 |
| `run_config_json` | str | 本次构建配置 |
| `run_metrics_json` | str | 运行统计与质量指标 |
| `error_message` | str nullable | 错误信息 |
| `debug_dir` | str nullable | 调试目录 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

### 不再保留的设计

- `input_file_ids_json`

### 替代方案

新增关系表 `graph_digest_job_input_document`。

### 为什么不建议把方法拆成很多专属列

如果这里写成：

- `extractor_version`
- `clusterer_version`
- `resolver_version`
- `prompt_version`
- `embedding_model_version`

那以后每换一次方法组合，schema 都会跟着改。

更稳的做法是：

- 只保留极少数稳定核心列：`strategy_name`、`strategy_version`
- 把大量会变化的方法细节放到 `run_config_json` / `run_metrics_json`

---

## 7.2 `graph_digest_job_input_document`（新表）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `job_id` | FK | graph job |
| `document_id` | FK | 输入文档 |
| `order_index` | int | 输入顺序 |

### 推荐约束

- `unique(job_id, document_id)`

> 图谱 job 的输入应该是 `document`，不是 `raw_file`。Digest 永远不应该直接站在原始文件层做推理。

---

## 7.3 `knowledge_node`

当前表设计方向是对的，建议保留，但收紧语义。

### 推荐字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | PK | 节点 ID |
| `subject` | indexed str | 工作空间 |
| `node_type` | str | 类型 |
| `canonical_name` | str | 显示名 |
| `normalized_name` | str | 对齐名 |
| `identity_key` | str nullable | 更稳定身份键 |
| `status` | str | `active/merged/deprecated/pending` |
| `confidence` | float | 节点置信度 |
| `current_revision_id` | FK nullable | 当前版本 |
| `merged_into_node_id` | FK nullable | 合并去向 |
| `first_seen_job_id` | FK nullable | 首次出现 job |
| `last_seen_job_id` | FK nullable | 最近更新 job |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

### 推荐约束

- `unique(subject, node_type, normalized_name)`
- `index(subject, status)`

---

## 7.4 `knowledge_node_alias`

保留 alias 独立表的思路，这是对的。

### 推荐字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | PK | alias ID |
| `node_id` | FK | 所属节点 |
| `alias` | str | 别名 |
| `normalized_alias` | str | 归一化别名 |
| `language` | str | 语言 |
| `source` | str | `llm/rule/manual` |
| `confidence` | float | 置信度 |
| `is_primary` | bool | 主别名 |
| `status` | str | `active/inactive` |
| `created_by_job_id` | FK nullable | 来源 job |
| `created_at` | datetime | 创建时间 |

---

## 7.5 `knowledge_node_revision`

### 角色

节点身份稳定，内容版本化。这里应明确：

- revision 是面向内容的版本层
- evidence 永远优先挂到 revision，而不是只挂到 node 身份

### 推荐字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | PK | revision ID |
| `node_id` | FK | 所属节点 |
| `revision_no` | int | 版本号 |
| `title` | str | 标题 |
| `summary` | text | 摘要 |
| `body` | text | 正文 |
| `revision_reason` | str | 原因 |
| `digest_job_id` | FK nullable | 来源 job |
| `is_current` | bool | 当前版本 |
| `created_at` | datetime | 创建时间 |

### 推荐约束

- `unique(node_id, revision_no)`
- `index(node_id, is_current)`

---

## 7.6 `knowledge_edge` / `knowledge_edge_revision`

边和边修订继续沿用当前双层设计，原则与节点一致：

- 身份层负责唯一边
- revision 层负责描述和权重变化

不再展开逐字段赘述，字段设计与节点层对称即可。

---

## 7.7 `evidence_link`

### 角色

这是 Digest 最不能随意做轻的表。它是系统可解释性的根。

### 推荐字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | PK | evidence ID |
| `subject` | indexed str | 工作空间 |
| `entity_type` | str | `node/edge/doc` |
| `entity_id` | int | 身份对象 ID |
| `entity_revision_id` | int nullable | 版本对象 ID |
| `document_id` | FK | 来源文档 |
| `chunk_id` | FK | 来源 chunk |
| `quote_text` | text | 引用文本 |
| `source_span_start` | int nullable | 起点 |
| `source_span_end` | int nullable | 终点 |
| `evidence_role` | str | `support/summary/example/...` |
| `extraction_method` | str | `llm/rule/manual` |
| `field_scope` | str | 证据支持哪个字段 |
| `confidence` | float | 置信度 |
| `is_active` | bool | 是否生效 |
| `created_by_job_id` | FK nullable | 来源 job |
| `created_at` | datetime | 创建时间 |

### 推荐约束

- `index(entity_type, entity_id, is_active)`
- `index(chunk_id)`

### 关键决定

无论知识图谱还是知识文档，最终都应该能回到 `chunk_id`。这条 lineage 不要断。

---

## 7.8 `curriculum_derive_job`

保留独立 job 表，但语义明确为：

> 基于某次 graph digest 结果派生课程结构的一次运行。

建议字段保留当前主体，新增：

- `debug_dir`
- `run_key`
- `strategy_name`
- `strategy_version`
- `run_config_json`

并明确：

- 输入来源不是 file ids
- 输入来源是 `graph_digest_job.id`
- 课程派生算法怎么变，都不应该逼着我们改课程主表

---

## 7.9 `teaching_unit` / `teaching_unit_revision` / `teaching_unit_membership`

这三张表的总体方向也是对的，建议保留，但有两个设计原则要定死：

1. `teaching_unit` 是稳定教学身份，不是临时聚类结果缓存。
2. `teaching_unit_membership` 是单位和节点关系表，不能再塞 JSON。

### 推荐最关键约束

- `teaching_unit.unique(subject, member_signature)`
- `teaching_unit_revision.unique(unit_id, revision_no)`
- `teaching_unit_membership.unique(unit_id, knowledge_node_id, role)`

---

## 7.10 `theme_tree_version` / `theme_tree_node` / `unit_tree_membership`

这一组表的方向也基本正确，建议保留，只补两条规范：

- `theme_tree_node` 只表达树结构和显示语义
- `unit_tree_membership` 只表达单元挂载，不混入 prerequisite 语义

---

## 7.11 `prereq_dag_version` / `unit_dependency`

这组表继续保留，关键是继续坚持：

- prerequisite 是 DAG，不是树
- `unit_dependency` 要绑定 `dag_version_id`
- 依赖边不直接写回 `teaching_unit`

---

## 7.12 `curriculum_snapshot`

### 角色

快照不是冗余表，而是消费侧的一致性边界。

它定义：

> 当前对外可读的课程结构 = 哪个 theme tree version + 哪个 prereq dag version + 哪些 teaching unit 版本组合

建议保留，并继续作为：

- Examine 的范围输入
- Profile 的结构视图输入
- 前端 SummaryPage 的当前版本入口

---

## 7.13 `docgen_job`

### 角色

知识文档构建 job。建议保留，但改掉 `input_file_ids_json`。

建议新增稳定字段：

- `strategy_name`
- `strategy_version`
- `run_config_json`
- `run_metrics_json`

新增关系表：

- `docgen_job_input_document`

字段与 `graph_digest_job_input_document` 类似。

---

## 7.14 `knowledge_doc`

### 角色

面向用户的章节知识文档，应该成为 Digest 的正式产出表，而不是“顺手写一下 Markdown 文件再记个路径”。

### 推荐字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | PK | 文档 ID |
| `subject` | indexed str | 工作空间 |
| `docgen_job_id` | FK | 来源 job |
| `chapter_index` | int | 章节顺序 |
| `slug` | str | 稳定路由标识 |
| `title` | str | 标题 |
| `summary` | text | 导读摘要 |
| `body_markdown` | long text | canonical 正文 |
| `body_hash` | str | 正文 hash |
| `export_uri` | str nullable | 本地导出路径 |
| `status` | str | `draft/published/archived` |
| `version` | int | 版本号 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

### 要淘汰的设计

- `source_file_ids` JSON

### 替代方案

新增 `knowledge_doc_source_chunk`。

---

## 7.15 `knowledge_doc_source_chunk`（新表）

### 角色

表示一篇知识文档来自哪些 chunk。

### 推荐字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `knowledge_doc_id` | FK | 知识文档 |
| `chunk_id` | FK | 来源 chunk |
| `coverage_role` | str | `primary/support/example` |
| `order_index` | int | 出现顺序 |

### 推荐约束

- `unique(knowledge_doc_id, chunk_id, coverage_role)`

> 知识文档最终应该能精确追溯到 chunk，而不是只追到 file。

---

## 8. 推荐索引与硬约束

以下是这次重构中最重要、必须显式写进 schema 的约束。

### 8.1 Ingest 侧

- `raw_file`: `index(subject, content_hash)`
- `ingest_parse_job`: 同一 `raw_file` 同时只能有一个 `running`
- `document`: `unique(parse_job_id)`
- `document_asset`: `unique(document_id, asset_index)`
- `document_chunk`: `unique(document_id, chunk_index)`

### 8.2 Digest 侧

- `graph_digest_job_input_document`: `unique(job_id, document_id)`
- `knowledge_node`: `unique(subject, node_type, normalized_name)`
- `knowledge_node_alias`: `unique(node_id, normalized_alias)`
- `knowledge_edge`: `unique(subject, source_node_id, target_node_id, edge_type)`
- `knowledge_node_revision`: `unique(node_id, revision_no)`
- `knowledge_edge_revision`: `unique(edge_id, revision_no)`
- `teaching_unit`: `unique(subject, member_signature)`
- `teaching_unit_membership`: `unique(unit_id, knowledge_node_id, role)`
- `unit_tree_membership`: `unique(tree_version_id, tree_node_id, teaching_unit_id, membership_role)`
- `unit_dependency`: `unique(dag_version_id, source_unit_id, target_unit_id, dependency_type)`
- `knowledge_doc_source_chunk`: `unique(knowledge_doc_id, chunk_id, coverage_role)`

### 8.3 绝对不要再做的事

- 不要再用 JSON 字段保存关系集合
- 不要再让文件路径充当下游真相
- 不要再把解析状态塞回 `raw_file`
- 不要让 graph/docgen 直接吃 `raw_file` 而不是 `document`
- 不要把当前 workflow 节点名、prompt 名、第三方库名编码进主表结构

---

## 9. Workflow 写表责任矩阵

## 9.1 Ingest

| workflow / node | 主要写表 | 主要写本地 |
| --- | --- | --- |
| 上传保存 | `raw_file` | `raw/` |
| classify / parse | `ingest_parse_job` | `debug/ingest...`、临时导出 Markdown/asset |
| persist canonical document | `document`、`document_asset`、`document_chunk`、`chunk_embeddings` | `markdown/`、`assets/` 作为导出/调试副本 |

## 9.2 Digest Graph

| workflow / node | 主要写表 | 主要写本地 |
| --- | --- | --- |
| trigger graph job | `graph_digest_job`、`graph_digest_job_input_document` | `debug/digest.graph/...` |
| extract / resolve | `knowledge_node*`、`knowledge_edge*`、`evidence_link` | 调试摘要 |
| finalize | `curriculum_derive_job` | 调试摘要 |

## 9.3 Digest Curriculum

| workflow / node | 主要写表 | 主要写本地 |
| --- | --- | --- |
| derive units | `teaching_unit*` | `debug/digest.curriculum/...` |
| derive tree | `theme_tree_version`、`theme_tree_node`、`unit_tree_membership` | 调试摘要 |
| derive dag | `prereq_dag_version`、`unit_dependency` | 调试摘要 |
| finalize | `curriculum_snapshot` | 调试摘要 |

## 9.4 Digest Docs

| workflow / node | 主要写表 | 主要写本地 |
| --- | --- | --- |
| trigger docgen | `docgen_job`、`docgen_job_input_document` | `debug/digest.docs/...` |
| outline / draft / review | `docgen_job` 进度字段 | `docgen_intermediate/` |
| finalize | `knowledge_doc`、`knowledge_doc_source_chunk` | `knowledge_docs/` |

---

## 10. 当前代码到目标 schema 的映射

| 当前设计 | 目标设计 |
| --- | --- |
| `raw_file` 同时管文件身份 + 解析状态 + 产物路径 | `raw_file` 只管文件身份，新增 `ingest_parse_job` 管解析过程 |
| `raw_file.markdown_path` 是下游入口 | `document.body_markdown` 是下游入口 |
| 资产只在文件系统目录里 | 新增 `document_asset` manifest 表 |
| `document_chunk` 只有轻量字段 | 升级成完整 TextUnit 表 |
| `graph_digest_job.input_file_ids_json` | `graph_digest_job_input_document` |
| `docgen_job.input_file_ids_json` | `docgen_job_input_document` |
| `knowledge_doc.source_file_ids` JSON | `knowledge_doc_source_chunk` |
| 本地 Markdown 与 DB 正文真相不清 | DB 正文 canonical，本地 `.md` 导出副本 |

---

## 11. 推荐重构顺序

为了降低一次性推倒重来的风险，建议按下面顺序重构。

### 阶段 1：先把 Ingest 语义拆干净

1. 收缩 `raw_file`
2. 新增 `ingest_parse_job`
3. 新增 `document_asset`
4. 增强 `document` / `document_chunk`
5. 让 Ingest 直接写 canonical `document` 与 `document_chunk`
6. 把实现细节统一收进 `producer_* + run_*_json`

### 阶段 2：再把 Digest 输入关系表正规化

1. 去掉 `graph_digest_job.input_file_ids_json`
2. 去掉 `docgen_job.input_file_ids_json`
3. 增加 job-input join 表
4. 让 Graph / DocGen 全部以 `document_id` 作为输入粒度
5. 为 graph/docgen/curriculum job 加上 `strategy_* + run_*_json`

### 阶段 3：最后补 lineage 与知识文档来源表

1. 增加 `knowledge_doc_source_chunk`
2. 统一 graph/docgen 的 chunk 级 provenance
3. 收紧前端和服务层对 canonical text 的读取方式

---

## 12. 本地优先与中心化部署

### 12.1 当前默认

- 关系数据：SQLite
- 向量索引：sqlite-vec
- 原始文件与导出：本地文件系统

### 12.2 未来默认推荐

- 关系数据：PostgreSQL
- 向量索引：pgvector
- 原始文件与导出：OSS / MinIO

但无论本地还是中心化，上面定义的 **逻辑分层和表职责不应再变化**。

---

## 13. 最终原则

如果只记住一句话：

> **Ingest 负责把原始文件变成 canonical document / chunk；Digest 负责基于 document / chunk 构建 graph、curriculum 和 knowledge docs。**

围绕这句话，数据库设计就应该稳定成下面这条链：

`raw_file -> ingest_parse_job -> document -> document_asset / document_chunk / chunk_embeddings -> graph_digest_job/docgen_job inputs -> knowledge graph -> curriculum snapshot -> knowledge_doc`

只要这条链在 schema 上被清晰表达出来，后面的代码重构就会顺很多，也不会再出现“流程能跑，但数据库语义还是糊的”这种状态。
