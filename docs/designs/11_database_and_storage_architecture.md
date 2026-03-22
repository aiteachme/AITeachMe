# 11. 数据库与存储架构设计

## 1. 文档定位

本文档是 AITeachMe 项目的**完整数据库设计规范**，用于指导后续代码重构。

### 1.1 核心目标

- **表数量最小化**：控制在 6-7 张核心表
- **双部署支持**：本地部署（SQLite + 本地文件）和服务器部署（MySQL + OSS）
- **覆盖五大引擎**：Ingest、Digest、Interact、Examine、Profile
- **长期稳定性**：即使实现方法变化，主表结构也不需要频繁修改
- **可追溯性**：所有派生数据都能追溯到原始来源

### 1.2 设计原则

1. **表表达业务语义，不表达实现细节**
2. **稳定对象和生成方法分离**
3. **集合关系一律用关系表，不用 JSON 字段**
4. **数据库是 canonical truth，本地文件是导出副本**
5. **方法变化优先落到 JSON 配置字段，而不是加新列**

---

## 2. 业界最佳实践调研

### 2.1 向量存储设计

根据 2026 年业界实践调研：

**核心发现**：
- 向量库**不应该只存 ID + embedding**，必须配合 metadata 才能高效过滤
- 主流方案是**双存储架构**：关系库存业务数据 + 向量库存 embedding + 轻量 metadata
- chunk_id 设计必须支持：
  - 快速反查 document 和 chunk 信息
  - 支持 metadata filtering（按文档、章节、时间等过滤）
  - 分布式环境下的唯一性

**参考来源**：
- [Metadata Filtering in Vector Search](https://www.saumilsrivastava.ai/blog/metadata-filtering-in-vector-search-a-comprehensive-guide-for-engineering-leaders)
- [Vector Stores for RAG (Postgres + pgvector)](https://buildrag.com/tutorials/rag-components/vector-databases/)
- [SQLite for AI: Vector Search, RAG Pipelines](https://calmops.com/database/sqlite/sqlite-ai)

### 2.2 Chunk ID 设计方案对比

| 方案 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| 递增数字 | 简单 | 可预测、无语义、多实例冲突 | ❌ 不推荐 |
| doc_id * 10000 + index | 可解码 | 限制单文档 chunk 数、仍可预测 | ❌ 不推荐 |
| UUID v7 | 全局唯一、时间有序、分布式友好 | 字符串类型 | ✅ **推荐** |
| Snowflake ID | 数字型、时间有序、分布式友好 | 需要机器 ID 管理 | ✅ 备选 |

**最终选择：UUID v7**
- 全局唯一，支持分布式
- 时间有序（前缀包含时间戳）
- SQLite 和 MySQL 都支持
- sqlite-vec、pgvector、Milvus 都支持字符串 ID

### 2.3 向量存储 Metadata 设计

根据调研，向量库应该存储的 metadata：

```json
{
  "chunk_id": "018e1234-5678-7abc-def0-123456789abc",
  "doc_id": "doc_uuid",
  "doc_title": "线性代数基础",
  "chunk_index": 5,
  "section": "第二章 > 矩阵运算",
  "page_start": 12,
  "page_end": 13,
  "token_count": 512,
  "created_at": "2026-03-23T10:00:00Z"
}
```

**为什么需要这些 metadata**：
- `doc_id` + `doc_title`：支持按文档过滤检索
- `section`：支持按章节过滤
- `page_start/end`：支持按页码范围过滤
- `token_count`：支持按长度过滤
- `created_at`：支持按时间过滤（增量更新场景）

---

## 3. 总体架构

### 3.1 逻辑分层

```
┌─────────────────────────────────────────────────────────────┐
│  用户层 (User Layer)                                         │
│  - users, subjects                                          │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  材料层 (Material Layer)                                     │
│  - documents (原始文件 + 解析结果 + chunk)                   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  知识层 (Knowledge Layer)                                    │
│  - knowledge_graph (节点 + 边 + 证据)                        │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  交互层 (Interaction Layer)                                  │
│  - interactions (对话 + 测评)                                │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  状态层 (State Layer)                                        │
│  - user_states (掌握度 + 复习任务 + 错题)                    │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  向量层 (Vector Layer)                                       │
│  - chunk_embeddings (向量索引)                               │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 核心表设计（6-7 张表）

| 表名 | 职责 | 引擎覆盖 |
|------|------|----------|
| `users` | 用户身份与工作空间 | 全部 |
| `documents` | 原始文件 + 解析结果 + chunk | Ingest, Digest |
| `knowledge_graph` | 知识图谱（节点 + 边 + 证据） | Digest |
| `interactions` | 对话历史 + 测评记录 | Interact, Examine |
| `user_states` | 用户学习状态 | Profile |
| `chunk_embeddings` | 向量索引 | Ingest, Digest, Interact |
| `jobs` (可选) | 异步任务状态 | 全部 |

---

## 4. 详细表设计

### 4.1 users 表

**职责**：用户身份与工作空间管理

```sql
CREATE TABLE users (
  id TEXT PRIMARY KEY,              -- UUID v7
  username TEXT NOT NULL UNIQUE,
  email TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

  -- 工作空间列表（JSON）
  subjects_json TEXT,               -- ["math", "physics", ...]

  -- 用户偏好（JSON）
  preferences_json TEXT             -- {"theme": "dark", "language": "zh", ...}
);

CREATE INDEX idx_users_username ON users(username);
```

**subjects_json 示例**：
```json
["linear_algebra", "calculus", "physics_mechanics"]
```

**preferences_json 示例**：
```json
{
  "theme": "dark",
  "language": "zh",
  "default_subject": "linear_algebra"
}
```

---

## 5. documents 表（核心材料层）

### 5.1 表结构

**职责**：统一管理原始文件、解析结果、文档内容、chunk

```sql
CREATE TABLE documents (
  -- 基础身份
  id TEXT PRIMARY KEY,              -- UUID v7
  subject TEXT NOT NULL,
  doc_type TEXT NOT NULL,           -- 'raw_file' | 'knowledge_doc'

  -- 原始文件信息（doc_type='raw_file' 时使用）
  filename TEXT,
  filetype TEXT,                    -- 'pdf' | 'docx' | 'md' | ...
  storage_backend TEXT,             -- 'local' | 'oss'
  storage_uri TEXT,                 -- 文件路径或 OSS URL
  content_hash TEXT,                -- SHA-256
  file_size_bytes INTEGER,

  -- 解析状态（doc_type='raw_file' 时使用）
  parse_status TEXT,                -- 'pending' | 'parsing' | 'completed' | 'failed'
  parse_method TEXT,                -- 'markitdown' | 'ocr' | 'vlm' | ...
  parse_config_json TEXT,           -- 解析配置
  parse_error TEXT,

  -- 文档内容（解析后或生成的知识文档）
  title TEXT NOT NULL,
  body_markdown TEXT,               -- canonical Markdown 正文
  body_hash TEXT,                   -- Markdown hash
  language TEXT,                    -- 'zh' | 'en' | ...

  -- 元数据
  metadata_json TEXT,               -- 页数、图片数、标签等

  -- 时间戳
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMP              -- 软删除
);

CREATE INDEX idx_documents_subject ON documents(subject);
CREATE INDEX idx_documents_type ON documents(doc_type);
CREATE INDEX idx_documents_status ON documents(parse_status);
CREATE INDEX idx_documents_hash ON documents(content_hash);
```

### 5.2 metadata_json 设计

**原始文件 metadata**：
```json
{
  "estimated_pages": 120,
  "detected_language": "zh",
  "image_count": 15,
  "quality_score": 0.92,
  "asset_dir": "data/math/assets/doc_uuid/"
}
```

**知识文档 metadata**：
```json
{
  "chapter_index": 1,
  "slug": "linear-algebra-basics",
  "summary": "本章介绍线性代数的基本概念...",
  "tags": ["线性代数", "矩阵", "向量"],
  "source_doc_ids": ["doc_uuid_1", "doc_uuid_2"],
  "docgen_job_id": "job_uuid"
}
```

### 5.3 Chunk 存储设计

**关键决定**：chunk 数据直接存储在 `documents` 表的 JSON 字段中，而不是单独建表。

**chunks_json 字段结构**：
```json
{
  "chunks": [
    {
      "chunk_id": "018e1234-5678-7abc-def0-123456789abc",
      "chunk_index": 0,
      "chunk_kind": "header",
      "title": "第一章 向量空间",
      "level": 1,
      "header_path": "第一章 向量空间",
      "content": "# 第一章 向量空间\n\n向量空间是线性代数的基础...",
      "content_hash": "sha256_hash",
      "char_count": 1024,
      "token_count": 512,
      "page_start": 1,
      "page_end": 2,
      "embedding_status": "completed"
    },
    {
      "chunk_id": "018e1234-5678-7abc-def0-123456789abd",
      "chunk_index": 1,
      "chunk_kind": "paragraph",
      "title": "第一章 向量空间",
      "level": 1,
      "header_path": "第一章 向量空间 > 1.1 向量的定义",
      "content": "向量是具有大小和方向的量...",
      "content_hash": "sha256_hash",
      "char_count": 856,
      "token_count": 428,
      "page_start": 2,
      "page_end": 3,
      "embedding_status": "completed"
    }
  ],
  "total_chunks": 2,
  "chunking_method": "markdown_header",
  "chunking_config": {
    "max_chunk_size": 1000,
    "overlap": 100
  }
}
```

**为什么不单独建 chunk 表**：
1. **减少表数量**：符合"表尽可能少"的原则
2. **原子性**：document 和 chunks 是一个整体，一起创建、一起删除
3. **查询效率**：大部分场景是"给定 document 查所有 chunks"，JSON 字段一次读取即可
4. **向量检索场景**：通过 chunk_id 反查时，先查 chunk_embeddings 的 metadata 获取 doc_id，再查 documents 表

**查询模式**：
```python
# 1. 获取文档的所有 chunks
doc = db.query(Document).filter_by(id=doc_id).first()
chunks = json.loads(doc.chunks_json)["chunks"]

# 2. 通过 chunk_id 反查（向量检索后）
# 先从 chunk_embeddings metadata 获取 doc_id
# 再查 documents 表，解析 chunks_json 找到对应 chunk
```

---

## 6. chunk_embeddings 表（向量索引层）

### 6.1 表结构与设计原则

**职责**：存储 chunk 的向量表示，支持语义检索和 metadata 过滤

**关键设计原则**：
1. **chunk_id 使用 UUID v7**：全局唯一、时间有序、分布式友好
2. **必须存储 metadata**：支持按文档、章节、时间等过滤
3. **metadata 要轻量但完整**：包含反查和过滤所需的最小信息集
4. **本地和服务器统一**：SQLite (sqlite-vec) 和 PostgreSQL (pgvector) 使用相同 schema

### 6.2 本地部署（SQLite + sqlite-vec）

```sql
-- 创建虚拟表
CREATE VIRTUAL TABLE chunk_embeddings USING vec0(
  chunk_id TEXT PRIMARY KEY,
  embedding FLOAT[1536],           -- 向量维度（如 OpenAI text-embedding-3-small）

  -- Metadata 字段（用于过滤）
  doc_id TEXT NOT NULL,
  doc_title TEXT,
  chunk_index INTEGER,
  section TEXT,                    -- 章节路径
  page_start INTEGER,
  page_end INTEGER,
  token_count INTEGER,
  created_at TEXT                  -- ISO 8601 格式
);

-- 索引（sqlite-vec 自动处理向量索引）
CREATE INDEX idx_chunk_emb_doc ON chunk_embeddings(doc_id);
CREATE INDEX idx_chunk_emb_created ON chunk_embeddings(created_at);
```

### 6.3 服务器部署（PostgreSQL + pgvector）

```sql
-- 启用 pgvector 扩展
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE chunk_embeddings (
  chunk_id TEXT PRIMARY KEY,
  embedding vector(1536),          -- pgvector 类型

  -- Metadata 字段
  doc_id TEXT NOT NULL,
  doc_title TEXT,
  chunk_index INTEGER,
  section TEXT,
  page_start INTEGER,
  page_end INTEGER,
  token_count INTEGER,
  created_at TIMESTAMP,

  -- 外键约束
  FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
);

-- 向量索引（HNSW 或 IVFFlat）
CREATE INDEX idx_chunk_emb_vector ON chunk_embeddings
  USING hnsw (embedding vector_cosine_ops);

-- Metadata 索引
CREATE INDEX idx_chunk_emb_doc ON chunk_embeddings(doc_id);
CREATE INDEX idx_chunk_emb_created ON chunk_embeddings(created_at);
CREATE INDEX idx_chunk_emb_section ON chunk_embeddings(section);
```

### 6.4 为什么必须存储这些 Metadata

根据业界最佳实践调研，向量库的 metadata 设计直接影响检索质量和性能：

| Metadata 字段 | 用途 | 示例查询 |
|---------------|------|----------|
| `doc_id` | 按文档过滤 | "只在《线性代数》这本书里检索" |
| `doc_title` | 显示来源 | 检索结果显示"来自《线性代数》第3章" |
| `chunk_index` | 排序和上下文 | 获取相邻 chunk 提供更多上下文 |
| `section` | 按章节过滤 | "只在'矩阵运算'这一章检索" |
| `page_start/end` | 按页码过滤 | "只检索前50页的内容" |
| `token_count` | 控制上下文长度 | 优先返回较短的 chunk 避免超出 token 限制 |
| `created_at` | 增量更新 | "只检索最近一周新增的内容" |

**参考来源**：
- [Metadata Filtering in Vector Search](https://www.saumilsrivastava.ai/blog/metadata-filtering-in-vector-search-a-comprehensive-guide-for-engineering-leaders)
- [A Complete Guide to Filtering in Vector Search](https://qdrant.tech/articles/vector-search-filtering/)

### 6.5 检索流程示例

**场景 1：简单语义检索**
```python
# 1. 生成查询向量
query_embedding = embed_model.encode("什么是矩阵的秩？")

# 2. 向量检索（Top-K）
results = vector_db.search(
    embedding=query_embedding,
    limit=5
)

# 3. 反查完整信息
for result in results:
    chunk_id = result.chunk_id
    doc_id = result.metadata["doc_id"]

    # 从 documents 表获取完整 chunk 内容
    doc = db.query(Document).filter_by(id=doc_id).first()
    chunks = json.loads(doc.chunks_json)["chunks"]
    chunk = next(c for c in chunks if c["chunk_id"] == chunk_id)

    print(f"来源：{result.metadata['doc_title']}")
    print(f"章节：{result.metadata['section']}")
    print(f"内容：{chunk['content']}")
```

**场景 2：带 Metadata 过滤的检索**
```python
# 只在特定文档的特定章节检索
results = vector_db.search(
    embedding=query_embedding,
    filter={
        "doc_id": "doc_uuid_123",
        "section": {"$contains": "矩阵运算"}
    },
    limit=5
)
```

**场景 3：混合检索（向量 + 全文）**
```python
# 先用 metadata 过滤缩小范围，再做向量检索
results = vector_db.search(
    embedding=query_embedding,
    filter={
        "created_at": {"$gte": "2026-03-01"},
        "token_count": {"$lte": 500}
    },
    limit=10
)
```

### 6.6 Chunk ID 生成策略

**使用 UUID v7（推荐）**：
```python
import uuid
from datetime import datetime

def generate_chunk_id() -> str:
    """生成 UUID v7 格式的 chunk_id"""
    return str(uuid.uuid7())

# 示例
chunk_id = generate_chunk_id()
# 输出: "018e1234-5678-7abc-def0-123456789abc"
```

**UUID v7 的优势**：
1. **时间有序**：前缀包含时间戳，可以按创建时间排序
2. **全局唯一**：不会冲突，支持分布式生成
3. **兼容性好**：SQLite、MySQL、PostgreSQL 都支持
4. **向量库支持**：sqlite-vec、pgvector、Milvus 都支持字符串 ID

**不推荐的方案**：
- ❌ 递增数字：多实例冲突、可预测
- ❌ `doc_id * 10000 + chunk_index`：限制单文档 chunk 数、仍可预测
- ❌ 随机 UUID v4：无时间信息，不利于调试和增量更新

### 6.7 向量维度选择

| 模型 | 维度 | 适用场景 |
|------|------|----------|
| OpenAI text-embedding-3-small | 1536 | 通用场景，性价比高 |
| OpenAI text-embedding-3-large | 3072 | 高精度场景 |
| BGE-M3 | 1024 | 中文优化，本地部署 |
| Sentence-BERT | 768 | 轻量级，本地部署 |

**建议**：
- 本地部署：BGE-M3 (1024 维) 或 Sentence-BERT (768 维)
- 服务器部署：OpenAI text-embedding-3-small (1536 维)

### 6.8 向量索引策略

**SQLite (sqlite-vec)**：
- 自动使用 HNSW 索引
- 适合 < 100 万条向量
- 无需手动配置

**PostgreSQL (pgvector)**：
```sql
-- HNSW 索引（推荐，查询快但构建慢）
CREATE INDEX idx_chunk_emb_hnsw ON chunk_embeddings
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

-- IVFFlat 索引（构建快但查询稍慢）
CREATE INDEX idx_chunk_emb_ivfflat ON chunk_embeddings
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);
```

**索引选择建议**：
- < 10 万条：HNSW (m=16, ef_construction=64)
- 10-100 万条：HNSW (m=32, ef_construction=128)
- > 100 万条：考虑专用向量库（Milvus、Qdrant）

### 6.9 数据一致性保证

**原则**：chunk_embeddings 的生命周期跟随 documents 表

**删除文档时**：
```python
# 1. 删除向量索引
chunk_ids = [c["chunk_id"] for c in json.loads(doc.chunks_json)["chunks"]]
vector_db.delete(chunk_ids)

# 2. 软删除文档
doc.deleted_at = datetime.now()
db.commit()
```

**重新解析文档时**：
```python
# 1. 删除旧向量
old_chunk_ids = [c["chunk_id"] for c in json.loads(doc.chunks_json)["chunks"]]
vector_db.delete(old_chunk_ids)

# 2. 更新文档和 chunks
doc.chunks_json = json.dumps(new_chunks)
doc.body_markdown = new_markdown
doc.updated_at = datetime.now()
db.commit()

# 3. 插入新向量
for chunk in new_chunks["chunks"]:
    embedding = embed_model.encode(chunk["content"])
    vector_db.insert(
        chunk_id=chunk["chunk_id"],
        embedding=embedding,
        metadata={
            "doc_id": doc.id,
            "doc_title": doc.title,
            "chunk_index": chunk["chunk_index"],
            "section": chunk["header_path"],
            "page_start": chunk["page_start"],
            "page_end": chunk["page_end"],
            "token_count": chunk["token_count"],
            "created_at": datetime.now().isoformat()
        }
    )
```

---

## 7. knowledge_graph 表（知识层）

### 7.1 表结构

**职责**：存储知识图谱（节点 + 边 + 证据链）

```sql
CREATE TABLE knowledge_graph (
  id TEXT PRIMARY KEY,              -- UUID v7
  subject TEXT NOT NULL,
  graph_version INTEGER DEFAULT 1,

  -- 图谱数据（JSON）
  nodes_json TEXT,                  -- 节点列表
  edges_json TEXT,                  -- 边列表
  evidence_json TEXT,               -- 证据链

  -- 课程结构（JSON）
  teaching_units_json TEXT,         -- 教学单元
  theme_tree_json TEXT,             -- 主题树
  prereq_dag_json TEXT,             -- 先修 DAG

  -- 元数据
  metadata_json TEXT,               -- 构建配置、统计信息

  -- 时间戳
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_kg_subject ON knowledge_graph(subject);
CREATE INDEX idx_kg_version ON knowledge_graph(subject, graph_version DESC);
```

### 7.2 nodes_json 设计

```json
{
  "nodes": [
    {
      "node_id": "node_uuid_1",
      "node_type": "concept",
      "canonical_name": "矩阵的秩",
      "aliases": ["秩", "rank", "矩阵秩"],
      "definition": "矩阵的秩是其行向量组的极大线性无关组所含向量的个数",
      "properties": {
        "difficulty": "medium",
        "importance": "high"
      },
      "revision_no": 1,
      "confidence": 0.95,
      "created_at": "2026-03-23T10:00:00Z",
      "updated_at": "2026-03-23T10:00:00Z"
    }
  ],
  "total_nodes": 1
}
```

### 7.3 edges_json 设计

```json
{
  "edges": [
    {
      "edge_id": "edge_uuid_1",
      "source_node_id": "node_uuid_1",
      "target_node_id": "node_uuid_2",
      "edge_type": "prerequisite",
      "description": "理解矩阵的秩需要先掌握线性相关性",
      "weight": 0.8,
      "revision_no": 1,
      "created_at": "2026-03-23T10:00:00Z"
    }
  ],
  "total_edges": 1
}
```

### 7.4 evidence_json 设计

```json
{
  "evidence_links": [
    {
      "evidence_id": "evidence_uuid_1",
      "entity_type": "node",
      "entity_id": "node_uuid_1",
      "doc_id": "doc_uuid_1",
      "chunk_id": "chunk_uuid_1",
      "quote_text": "矩阵的秩定义为其行向量组的极大线性无关组所含向量的个数",
      "evidence_role": "definition",
      "confidence": 0.95,
      "created_at": "2026-03-23T10:00:00Z"
    }
  ],
  "total_evidence": 1
}
```

### 7.5 teaching_units_json 设计

```json
{
  "units": [
    {
      "unit_id": "unit_uuid_1",
      "unit_name": "矩阵的秩与线性相关性",
      "unit_type": "concept_cluster",
      "member_nodes": ["node_uuid_1", "node_uuid_2", "node_uuid_3"],
      "learning_objectives": [
        "理解矩阵秩的定义",
        "掌握秩的计算方法",
        "应用秩判断线性相关性"
      ],
      "estimated_hours": 2.5,
      "difficulty": "medium",
      "revision_no": 1
    }
  ],
  "total_units": 1
}
```

### 7.6 theme_tree_json 设计

```json
{
  "tree_version": 1,
  "root_node": {
    "tree_node_id": "tree_node_1",
    "title": "线性代数",
    "node_type": "root",
    "children": [
      {
        "tree_node_id": "tree_node_2",
        "title": "第一章 向量空间",
        "node_type": "chapter",
        "teaching_units": ["unit_uuid_1", "unit_uuid_2"],
        "children": [
          {
            "tree_node_id": "tree_node_3",
            "title": "1.1 向量的定义",
            "node_type": "section",
            "teaching_units": ["unit_uuid_1"]
          }
        ]
      }
    ]
  }
}
```

### 7.7 prereq_dag_json 设计

```json
{
  "dag_version": 1,
  "dependencies": [
    {
      "source_unit_id": "unit_uuid_1",
      "target_unit_id": "unit_uuid_2",
      "dependency_type": "prerequisite",
      "strength": 0.9,
      "reason": "必须先理解向量空间才能学习线性变换"
    }
  ],
  "total_dependencies": 1
}
```

---

## 8. interactions 表（交互层）

### 8.1 表结构

**职责**：统一存储对话历史和测评记录

```sql
CREATE TABLE interactions (
  id TEXT PRIMARY KEY,              -- UUID v7
  subject TEXT NOT NULL,
  user_id TEXT NOT NULL,
  interaction_type TEXT NOT NULL,   -- 'chat' | 'exam'

  -- 对话相关（interaction_type='chat' 时使用）
  turn_index INTEGER,
  role TEXT,                        -- 'user' | 'assistant'
  content TEXT,
  contexts_json TEXT,               -- 检索到的上下文

  -- 测评相关（interaction_type='exam' 时使用）
  exam_paper_json TEXT,             -- 试卷内容
  answers_json TEXT,                -- 用户答案
  grading_json TEXT,                -- 判卷结果

  -- 元数据
  metadata_json TEXT,

  -- 时间戳
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_interactions_user ON interactions(user_id, created_at DESC);
CREATE INDEX idx_interactions_subject ON interactions(subject, interaction_type);
```

### 8.2 对话 contexts_json 设计

```json
{
  "query": "什么是矩阵的秩？",
  "retrieved_chunks": [
    {
      "chunk_id": "chunk_uuid_1",
      "doc_id": "doc_uuid_1",
      "doc_title": "线性代数基础",
      "section": "第二章 > 矩阵运算",
      "content": "矩阵的秩定义为...",
      "score": 0.92
    }
  ],
  "retrieval_method": "vector_search",
  "retrieval_config": {
    "top_k": 5,
    "filter": {"doc_id": "doc_uuid_1"}
  }
}
```

### 8.3 测评 exam_paper_json 设计

```json
{
  "exam_id": "exam_uuid_1",
  "exam_title": "线性代数第一章测试",
  "questions": [
    {
      "question_id": "q_uuid_1",
      "question_type": "single_choice",
      "question_text": "矩阵的秩最大不超过？",
      "options": ["行数", "列数", "行数和列数的较小值", "行数和列数的较大值"],
      "correct_answer": "C",
      "knowledge_nodes": ["node_uuid_1"],
      "difficulty": "easy"
    }
  ],
  "total_questions": 1,
  "time_limit_minutes": 30
}
```

### 8.4 测评 answers_json 设计

```json
{
  "answers": [
    {
      "question_id": "q_uuid_1",
      "user_answer": "C",
      "time_spent_seconds": 15
    }
  ],
  "submitted_at": "2026-03-23T10:30:00Z"
}
```

### 8.5 测评 grading_json 设计

```json
{
  "grading_results": [
    {
      "question_id": "q_uuid_1",
      "is_correct": true,
      "score": 10,
      "feedback": "回答正确！"
    }
  ],
  "total_score": 10,
  "max_score": 10,
  "pass_threshold": 6,
  "is_passed": true,
  "graded_at": "2026-03-23T10:31:00Z"
}
```

---

## 9. user_states 表（状态层）

### 9.1 表结构

**职责**：存储用户学习状态（掌握度、复习任务、错题）

```sql
CREATE TABLE user_states (
  id TEXT PRIMARY KEY,              -- UUID v7
  subject TEXT NOT NULL,
  user_id TEXT NOT NULL,

  -- 掌握度（JSON）
  mastery_json TEXT,                -- 各知识点掌握度

  -- 复习任务（JSON）
  review_tasks_json TEXT,           -- 待复习任务

  -- 错题记录（JSON）
  mistakes_json TEXT,               -- 错题集

  -- 学习统计（JSON）
  stats_json TEXT,                  -- 学习时长、完成度等

  -- 时间戳
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

  UNIQUE(user_id, subject)
);

CREATE INDEX idx_user_states_user ON user_states(user_id);
```

### 9.2 mastery_json 设计

```json
{
  "node_mastery": {
    "node_uuid_1": {
      "mastery_level": 0.85,
      "last_practiced": "2026-03-23T10:00:00Z",
      "practice_count": 5,
      "correct_count": 4,
      "next_review": "2026-03-25T10:00:00Z"
    }
  },
  "unit_mastery": {
    "unit_uuid_1": {
      "mastery_level": 0.78,
      "completed_nodes": 3,
      "total_nodes": 5
    }
  }
}
```

### 9.3 review_tasks_json 设计

```json
{
  "tasks": [
    {
      "task_id": "task_uuid_1",
      "task_type": "review_node",
      "target_id": "node_uuid_1",
      "target_name": "矩阵的秩",
      "priority": "high",
      "due_date": "2026-03-25T10:00:00Z",
      "status": "pending",
      "created_at": "2026-03-23T10:00:00Z"
    }
  ],
  "total_pending": 1
}
```

### 9.4 mistakes_json 设计

```json
{
  "mistakes": [
    {
      "mistake_id": "mistake_uuid_1",
      "question_id": "q_uuid_1",
      "question_text": "矩阵的秩最大不超过？",
      "user_answer": "A",
      "correct_answer": "C",
      "knowledge_nodes": ["node_uuid_1"],
      "occurred_at": "2026-03-23T10:30:00Z",
      "reviewed": false,
      "review_count": 0
    }
  ],
  "total_mistakes": 1
}
```

### 9.5 stats_json 设计

```json
{
  "total_study_hours": 12.5,
  "total_exams": 3,
  "average_score": 85,
  "completed_units": 5,
  "total_units": 10,
  "completion_rate": 0.5,
  "streak_days": 7,
  "last_active": "2026-03-23T10:00:00Z"
}
```

---

## 10. jobs 表（可选，异步任务）

### 10.1 表结构

**职责**：统一管理异步任务状态（解析、图谱构建、文档生成等）

```sql
CREATE TABLE jobs (
  id TEXT PRIMARY KEY,              -- UUID v7
  subject TEXT NOT NULL,
  job_type TEXT NOT NULL,           -- 'parse' | 'graph_digest' | 'docgen' | 'exam_grade'

  -- 任务状态
  status TEXT NOT NULL,             -- 'pending' | 'running' | 'completed' | 'failed'
  progress INTEGER DEFAULT 0,       -- 0-100
  current_step TEXT,

  -- 输入输出
  input_json TEXT,                  -- 任务输入
  output_json TEXT,                 -- 任务输出
  error_message TEXT,

  -- 配置与统计
  config_json TEXT,                 -- 任务配置
  metrics_json TEXT,                -- 运行统计

  -- 时间戳
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  started_at TIMESTAMP,
  finished_at TIMESTAMP
);

CREATE INDEX idx_jobs_subject ON jobs(subject, job_type);
CREATE INDEX idx_jobs_status ON jobs(status);
```

### 10.2 解析任务 input_json

```json
{
  "doc_id": "doc_uuid_1",
  "parse_method": "markitdown",
  "parse_config": {
    "extract_images": true,
    "ocr_fallback": true
  }
}
```

### 10.3 图谱构建任务 input_json

```json
{
  "doc_ids": ["doc_uuid_1", "doc_uuid_2"],
  "strategy": "incremental",
  "config": {
    "min_confidence": 0.7,
    "max_nodes": 1000
  }
}
```

### 10.4 任务 output_json

```json
{
  "doc_id": "doc_uuid_1",
  "chunks_created": 25,
  "embeddings_created": 25,
  "parse_quality": 0.92
}
```

---

## 11. 本地与服务器部署对比

### 11.1 存储后端对比

| 组件 | 本地部署 | 服务器部署 |
|------|----------|------------|
| 关系数据库 | SQLite | MySQL / PostgreSQL |
| 向量索引 | sqlite-vec | pgvector / Milvus |
| 文件存储 | 本地文件系统 | OSS / MinIO |
| 路径格式 | 相对路径 | URL |

### 11.2 路径抽象设计

**storage_uri 字段统一格式**：
- 本地：`local://data/math/raw/file.pdf`
- OSS：`oss://bucket-name/math/raw/file.pdf`

**路径解析函数**：
```python
def resolve_storage_uri(uri: str) -> str:
    """解析存储 URI 为实际路径"""
    if uri.startswith("local://"):
        return uri.replace("local://", "./")
    elif uri.startswith("oss://"):
        return f"https://oss.example.com/{uri.replace('oss://', '')}"
    else:
        return uri
```

### 11.3 迁移策略

**从本地迁移到服务器**：
1. 导出 SQLite 数据为 SQL 脚本
2. 上传本地文件到 OSS
3. 更新 `storage_uri` 字段（`local://` → `oss://`）
4. 导入数据到 MySQL/PostgreSQL
5. 重建向量索引到 pgvector

**迁移脚本示例**：
```python
# 1. 更新 storage_uri
for doc in documents:
    if doc.storage_uri.startswith("local://"):
        local_path = doc.storage_uri.replace("local://", "./")
        oss_path = upload_to_oss(local_path)
        doc.storage_uri = f"oss://{oss_path}"

# 2. 迁移向量索引
for doc in documents:
    chunks = json.loads(doc.chunks_json)["chunks"]
    for chunk in chunks:
        embedding = get_embedding_from_sqlite(chunk["chunk_id"])
        insert_to_pgvector(
            chunk_id=chunk["chunk_id"],
            embedding=embedding,
            metadata={...}
        )
```

---

## 12. 五大引擎覆盖验证

### 12.1 Ingest 引擎

**涉及表**：
- `documents`（原始文件 + 解析结果 + chunks）
- `chunk_embeddings`（向量索引）
- `jobs`（解析任务）

**数据流**：
```
上传文件 → documents (doc_type='raw_file')
  → 解析任务 (jobs)
  → 更新 body_markdown + chunks_json
  → 生成 embedding → chunk_embeddings
```

### 12.2 Digest 引擎

**涉及表**：
- `documents`（读取 chunks）
- `knowledge_graph`（构建图谱 + 课程结构）
- `jobs`（图谱构建任务、文档生成任务）

**数据流**：
```
documents.chunks_json → 抽取节点/边
  → knowledge_graph.nodes_json + edges_json + evidence_json
  → 派生课程结构 → teaching_units_json + theme_tree_json + prereq_dag_json
  → 生成知识文档 → documents (doc_type='knowledge_doc')
```

### 12.3 Interact 引擎

**涉及表**：
- `chunk_embeddings`（向量检索）
- `documents`（获取 chunk 内容）
- `interactions`（对话历史）

**数据流**：
```
用户提问 → 向量检索 (chunk_embeddings)
  → 反查 chunk 内容 (documents.chunks_json)
  → 生成回答 → 保存对话 (interactions)
```

### 12.4 Examine 引擎

**涉及表**：
- `knowledge_graph`（读取教学单元）
- `interactions`（生成试卷 + 保存答案）
- `user_states`（更新掌握度 + 错题）
- `jobs`（出题任务、判卷任务）

**数据流**：
```
选择教学单元 (knowledge_graph.teaching_units_json)
  → 生成试卷 (jobs + interactions.exam_paper_json)
  → 用户答题 → 保存答案 (interactions.answers_json)
  → 判卷 (jobs) → 更新结果 (interactions.grading_json)
  → 更新掌握度 (user_states.mastery_json)
  → 记录错题 (user_states.mistakes_json)
```

### 12.5 Profile 引擎

**涉及表**：
- `user_states`（掌握度 + 复习任务 + 学习统计）
- `knowledge_graph`（读取课程结构）
- `interactions`（读取历史记录）

**数据流**：
```
读取掌握度 (user_states.mastery_json)
  + 课程结构 (knowledge_graph.theme_tree_json)
  → 生成学习路径
  → 创建复习任务 (user_states.review_tasks_json)
  → 更新学习统计 (user_states.stats_json)
```

---

## 13. 关键约束与索引

### 13.1 唯一性约束

```sql
-- users 表
ALTER TABLE users ADD CONSTRAINT uk_users_username UNIQUE (username);

-- documents 表
ALTER TABLE documents ADD CONSTRAINT uk_documents_hash
  UNIQUE (subject, content_hash, deleted_at);

-- user_states 表
ALTER TABLE user_states ADD CONSTRAINT uk_user_states
  UNIQUE (user_id, subject);
```

### 13.2 外键约束（服务器部署）

```sql
-- chunk_embeddings 表
ALTER TABLE chunk_embeddings
  ADD CONSTRAINT fk_chunk_emb_doc
  FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE;

-- interactions 表
ALTER TABLE interactions
  ADD CONSTRAINT fk_interactions_user
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

-- user_states 表
ALTER TABLE user_states
  ADD CONSTRAINT fk_user_states_user
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
```

### 13.3 性能索引

```sql
-- documents 表
CREATE INDEX idx_documents_subject_type ON documents(subject, doc_type);
CREATE INDEX idx_documents_created ON documents(created_at DESC);

-- chunk_embeddings 表
CREATE INDEX idx_chunk_emb_doc_idx ON chunk_embeddings(doc_id, chunk_index);

-- interactions 表
CREATE INDEX idx_interactions_user_time ON interactions(user_id, created_at DESC);
CREATE INDEX idx_interactions_type ON interactions(subject, interaction_type, created_at DESC);

-- jobs 表
CREATE INDEX idx_jobs_subject_type ON jobs(subject, job_type, status);
CREATE INDEX idx_jobs_created ON jobs(created_at DESC);
```

---

## 14. 总结

### 14.1 核心设计决策

1. **6-7 张表**：users, documents, knowledge_graph, interactions, user_states, chunk_embeddings, jobs
2. **chunk_id 使用 UUID v7**：全局唯一、时间有序、分布式友好
3. **向量库必须存 metadata**：支持按文档、章节、时间过滤
4. **chunks 存储在 documents 表的 JSON 字段**：减少表数量，保持原子性
5. **数据库是 canonical truth**：本地文件只是导出副本
6. **JSON 字段存储复杂结构**：避免过多关系表，保持灵活性

### 14.2 与现有代码的映射

| 现有设计 | 新设计 |
|----------|--------|
| `raw_file` + `document` | 合并为 `documents` 表（通过 `doc_type` 区分） |
| `document_chunk` 独立表 | 合并到 `documents.chunks_json` |
| `knowledge_node` + `knowledge_edge` + 多张关系表 | 合并为 `knowledge_graph` 表 |
| `chat_message` + `exam_submission` | 合并为 `interactions` 表 |
| `user_profile` + `user_knowledge_state` + `review_task` + `mistake` | 合并为 `user_states` 表 |

### 14.3 重构优先级

**阶段 1：向量索引重构（最重要）**
1. 将 chunk_id 从算术编码改为 UUID v7
2. 在 chunk_embeddings 添加完整 metadata
3. 更新向量检索逻辑

**阶段 2：表合并**
1. 合并 raw_file 和 document 为 documents 表
2. 将 document_chunk 数据迁移到 chunks_json
3. 更新 Ingest 引擎代码

**阶段 3：知识图谱重构**
1. 合并知识图谱相关表为 knowledge_graph
2. 更新 Digest 引擎代码

**阶段 4：交互与状态层重构**
1. 合并对话和测评表为 interactions
2. 合并用户状态表为 user_states
3. 更新 Interact、Examine、Profile 引擎代码

---

## 参考资料

- [Metadata Filtering in Vector Search](https://www.saumilsrivastava.ai/blog/metadata-filtering-in-vector-search-a-comprehensive-guide-for-engineering-leaders)
- [Vector Stores for RAG (Postgres + pgvector)](https://buildrag.com/tutorials/rag-components/vector-databases/)
- [SQLite for AI: Vector Search, RAG Pipelines](https://calmops.com/database/sqlite/sqlite-ai)
- [A Complete Guide to Filtering in Vector Search](https://qdrant.tech/articles/vector-search-filtering/)
- [Document Chunking Strategies for RAG](https://grizzlypeaksoftware.com/library/document-chunking-strategies-for-rag-tqxosyf4)
