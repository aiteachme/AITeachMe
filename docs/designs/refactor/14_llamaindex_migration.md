# LlamaIndex 全索引存储层迁移方案

> 最后更新：2026-04-16
>
> 原则：开发期直接废弃旧 sqlite-vec / 手写 pgvector 索引，不做旧数据迁移和双读兼容；`retrieval_chunk` 继续作为业务元数据与引用来源。

## 1. 迁移目标

本次迁移不是在旧 SQL 检索外面包一层 adapter，而是让 LlamaIndex 接管本地知识库的向量索引生命周期：

- 写入：构建流程生成 embedding 后写入 LlamaIndex node
- 持久化：本地写入 `ContentStore`，云端写入 Postgres vector store
- 检索：`search_knowledge()` 统一查询 LlamaIndex subject index
- 删除：文件删除、知识清空、学科删除同步删除 LlamaIndex node/index

保留不动的部分：

- LangGraph workflow 骨架
- SSE streaming
- `retrieval_chunk` 表和 citation 契约
- SourceCurator / ContextCompressor
- teaching 层调用面

## 2. 目标架构

```text
构建写入：
  digest / knowledge_graph / unified
    -> aembed_texts()
    -> knowledge_repo.bulk_insert_embeddings()
    -> llamaindex_index.upsert_chunks()
    -> LlamaIndex vector store

检索读取：
  interact / local_rag / tools / teaching
    -> search_knowledge()
    -> llamaindex_index.retrieve_subject_chunks()
    -> retrieval_chunk 补齐正文和 citation metadata
    -> RetrievedChunk[]

删除清理：
  clear / subject delete / file delete
    -> knowledge_repo.delete_embeddings_by_chunk_ids()
    -> llamaindex_index.delete_chunks()
```

## 3. 后端选择

### 本地模式

- 使用 `llama-index-core` 内置 `SimpleVectorStore`
- 每个 subject 一份索引，持久化到 `ContentStore`
- 索引路径：`<subject>/rag_index/vector_store.json`
- 不依赖 sqlite-vec，开发环境更轻

### 云端模式

- 使用 `llama-index-vector-stores-postgres`
- 统一表：`atm_llamaindex_rag`
- 用 node metadata 的 `subject` 字段做隔离
- 继续复用 `DATABASE_URL`

## 4. 已落地代码边界

新增统一索引层：

```text
shared/infra/search/llamaindex_index/
├── __init__.py
└── manager.py
```

核心入口：

- `upsert_chunks(subject, chunks)`
- `rebuild_subject_index(subject, chunks)`
- `delete_chunks(subject, chunk_ids)`
- `clear_subject_index(subject)`
- `retrieve_subject_chunks(subject, query, top_k)`
- `query_subject_index(subject, query_embedding, top_k)`

旧入口兼容策略：

- `bulk_insert_embeddings()` 保留函数名，但内部写 LlamaIndex
- `delete_embeddings_by_chunk_ids()` 保留函数名，但内部删 LlamaIndex node
- `vector_search()` 保留短期兼容，但内部查询 LlamaIndex，不再读旧 SQL 向量表
- `ATMVectorStore` 仅作为旧 `build_knowledge_retriever()` 的兼容层，不再包装 `knowledge_repo.vector_search()`

## 5. 旧数据策略

当前仍处于开发阶段，旧索引数据直接废弃：

- 不迁移 `chunk_embeddings`
- 不迁移 `chunk_embeddings_*`
- 不迁移旧 `retrieval_chunk.embedding`
- 不保留旧检索 fallback

下一次知识构建会基于现有 `retrieval_chunk` 内容重新生成 LlamaIndex 索引。

## 6. 验证范围

最小验证即可，不需要跑全量大套件：

- `tests/test_search_namespace.py`
- `tests/test_architecture_boundaries.py`
- `tests/test_subject_embedding_service.py`
- `tests/test_llamaindex_index.py`

按实际改动补跑：

- 写入构建变更：`tests/test_knowledge_digest_service.py`
- 删除清理变更：`tests/test_subject_deletion.py`

## 7. 后续可选优化

- 将 API 字段 `vector_table` 正式改名为 `index_ref`
- 云端索引增加 hybrid search
- 对 `SimpleVectorStore` 增加构建锁或原子写文件策略
- 删除旧 sqlite-vec 依赖和旧 pgvector SQL helper
