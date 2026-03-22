# 11. 数据库与存储架构设计

## 1. 文档定位

本文档描述 AITeachMe 当前目标形态下的数据库与运行时存储边界，用于指导后续重构。

核心目标：

- 核心表数量尽量少
- 支持本地与服务器双部署
- 覆盖 Ingest / Digest / Interact / Examine / Profile
- 保持长期稳定，不因实现细节频繁加表
- 支持多章节知识文档与最终 merged 文档

---

## 2. 核心原则

1. 表表达业务语义，不表达短期实现细节
2. 稳定对象与生成方法分离
3. 数据库保存结构化真相
4. 本地 Markdown 保存知识文档正文
5. Docs 构建流程不依赖 `jobs` 表

---

## 3. 总体分层

| 层 | 核心对象 |
| --- | --- |
| 用户层 | `users` |
| 材料层 | `documents` |
| 知识层 | `knowledge_graph` |
| 交互层 | `interactions` |
| 状态层 | `user_states` |
| 向量层 | `chunk_embeddings` |
| 异步任务层 | `jobs` |

需要特别说明：

- `jobs` 仍可服务于解析、图谱、课程、测评等后台任务
- 但知识文档 Docs 构建已经明确不走 `jobs` 表

---

## 4. 核心表

| 表名 | 职责 | 备注 |
| --- | --- | --- |
| `users` | 用户身份与工作空间 | 稳定核心表 |
| `documents` | 原始文件、解析结果、知识文档正文索引 | 同时承载 `raw_file` 与 `knowledge_doc` 语义 |
| `knowledge_graph` | 图谱与课程结构聚合结果 | Digest 知识层 |
| `interactions` | 对话与测评记录 | Interact / Examine |
| `user_states` | 用户掌握度、复习任务、错题 | Profile |
| `chunk_embeddings` | 向量索引 | 检索层 |
| `jobs` | 非 Docs 的后台任务状态 | 可选但保留 |

---

## 5. documents 表

### 5.1 职责

`documents` 统一管理：

- 原始文件
- 解析后的文档内容
- 生成出来的知识文档

### 5.2 推荐结构

```sql
CREATE TABLE documents (
  id TEXT PRIMARY KEY,
  subject TEXT NOT NULL,
  doc_type TEXT NOT NULL,           -- 'raw_file' | 'knowledge_doc'

  filename TEXT,
  filetype TEXT,
  storage_backend TEXT,
  storage_uri TEXT,
  content_hash TEXT,
  file_size_bytes INTEGER,

  parse_status TEXT,
  parse_method TEXT,
  parse_config_json TEXT,
  parse_error TEXT,

  title TEXT NOT NULL,
  body_markdown TEXT,
  body_hash TEXT,
  language TEXT,

  metadata_json TEXT,

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMP
);
```

### 5.3 Knowledge Docs 的层次表达

知识文档必须支持“多个章节 + 一个 merged 文档”。

如果知识文档落在 `documents` 表中，推荐通过 `metadata_json` 区分角色：

- 章节文档
- merged 文档

章节文档示例：

```json
{
  "doc_role": "chapter",
  "chapter_index": 1,
  "slug": "linear-algebra-basics",
  "summary": "本章介绍线性代数的基本概念。",
  "tags": ["线性代数", "矩阵", "向量"],
  "source_doc_ids": ["doc_uuid_1", "doc_uuid_2"],
  "build_requested_at": "2026-03-23T16:40:00Z"
}
```

merged 文档示例：

```json
{
  "doc_role": "merged",
  "chapter_count": 6,
  "chapter_titles": [
    "向量空间",
    "矩阵运算",
    "线性方程组"
  ],
  "source_doc_ids": ["doc_uuid_1", "doc_uuid_2"],
  "build_requested_at": "2026-03-23T16:40:00Z"
}
```

注意：

- 不再使用 `docgen_job_id`
- Docs 的发布批次只用 `build_requested_at` 与 manifest 对齐

---

## 6. Chunk 存储与向量索引

### 6.1 Chunk 存储原则

Chunk 仍可直接存放在 `documents.chunks_json` 中，以减少表数量。

优点：

- 文档与 chunks 原子更新
- 给定文档读取全部 chunks 成本低
- 向量检索后可以通过 `doc_id + chunk_id` 回查

### 6.2 chunk_embeddings

`chunk_embeddings` 负责：

- 存储 embedding
- 存储轻量 metadata
- 支持按文档、章节、页码、时间过滤

推荐 metadata 字段：

- `doc_id`
- `doc_title`
- `chunk_index`
- `section`
- `page_start`
- `page_end`
- `token_count`
- `created_at`

`chunk_id` 继续推荐 UUID v7。

---

## 7. knowledge_graph 表

`knowledge_graph` 负责聚合以下 JSON 结构：

- `nodes_json`
- `edges_json`
- `evidence_json`
- `teaching_units_json`
- `theme_tree_json`
- `prereq_dag_json`
- `metadata_json`

这张表的职责是承载知识真相与教学结构，而不是承载知识文档构建状态。

---

## 8. interactions 与 user_states

### 8.1 interactions

统一存储：

- 对话历史
- 测评试卷
- 作答结果
- 判卷结果

### 8.2 user_states

统一存储：

- 掌握度
- 复习任务
- 错题
- 学习统计

---

## 9. jobs 表的边界

### 9.1 jobs 表保留的职责

`jobs` 表可以继续服务于：

- `parse`
- `graph_digest`
- `curriculum_derive`
- `exam_generate`
- `exam_grade`

### 9.2 jobs 表不再承担的职责

知识文档 Docs 构建不再依赖 `jobs` 表。

原因：

- Docs 对外不再查询任务状态
- Docs 更关心“最近已发布版本”
- Docs 已用文件锁和 manifest 替代 job 状态协议

因此，`job_type='docgen'` 不再是目标设计的一部分。

---

## 10. 本地与服务器部署

| 组件 | 本地部署 | 服务器部署 |
| --- | --- | --- |
| 关系数据库 | SQLite | MySQL / PostgreSQL |
| 向量索引 | sqlite-vec | pgvector / Milvus |
| 文件存储 | 本地文件系统 | OSS / MinIO |
| 知识文档正文 | 本地 Markdown | 对象存储或挂载卷 |

统一路径抽象示例：

- `local://data/math/raw/file.pdf`
- `oss://bucket-name/math/raw/file.pdf`

---

## 11. Docs 链路的运行时文件

Docs 发布相关文件固定放在：

`data/<subject>/knowledge_docs/`

其中包括：

- `chapter_XX_*.md`
- `merged_knowledge_base.md`
- `manifest.json`
- `.build.lock`
- `_building/`

这些文件是 Docs 去 job 化之后的核心运行时状态。

---

## 12. 五大引擎覆盖

### 12.1 Ingest

主要涉及：

- `documents`
- `chunk_embeddings`
- `jobs`

### 12.2 Digest

主要涉及：

- `documents`
- `knowledge_graph`
- `chunk_embeddings`
- `jobs`（仅图谱 / 课程，不含 Docs）

### 12.3 Interact

主要涉及：

- `chunk_embeddings`
- `documents`
- `interactions`

### 12.4 Examine

主要涉及：

- `knowledge_graph`
- `interactions`
- `user_states`
- `jobs`

### 12.5 Profile

主要涉及：

- `user_states`
- `knowledge_graph`
- `interactions`

---

## 13. 当前结论

这版设计在 Docs 链路上的关键变化已经明确：

- 知识文档必须支持多章节与 merged
- Docs 不再依赖 `DocGenJob`
- Docs 不再依赖 `jobs` 表
- Docs 的已发布元信息由 `manifest.json` 表达
- 数据库与本地 Markdown 一起构成知识文档真相层
