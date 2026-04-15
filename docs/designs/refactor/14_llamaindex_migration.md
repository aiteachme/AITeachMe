# LlamaIndex 渐进式迁移方案

> 最后更新：2026-04-15
>
> 原则：渐进式替换，不动 workflow graph 骨架，不动 LangSmith 观测面，在 `shared/infra/search/llamaindex_adapter/` 建 adapter 层。

---

## 1. 迁移目标

用 LlamaIndex 替换当前自建的 retrieval pipeline，获得：

- 更成熟的 query transform / sub-question decomposition
- 原生 reranker 和 postprocessor 链
- 更丰富的 vector store 适配（未来迁移 PostgreSQL + pgvector 更顺畅）
- hybrid retrieval（vector + keyword）开箱即用
- 社区维护的 retriever / reader 生态

不迁移的部分：

- LangGraph workflow 骨架不动
- LangSmith 观测面不动
- SSE streaming 不动
- teaching 层不动

---

## 2. 当前架构 vs 目标架构

```
迁移前：
  interact/retrieve_context → aembed_texts() → vector_search() → RetrievalPipeline → rerank
  search_knowledge()        → aembed_texts() → _vector_search() → rerank_chunks()
  digest/chapter_context    → get_retrievers_for_subject() → micro-loop → SourceCurator → ContextCompressor

迁移后 (Phase 1-2 已完成)：
  interact/retrieve_context → build_knowledge_retriever() → ATMKnowledgeRetriever.aretrieve()
  search_knowledge()        → build_knowledge_retriever() → ATMKnowledgeRetriever.aretrieve()
  digest/chapter_context    → (未改动，仍走现有 retriever + SourceCurator + ContextCompressor)
                               ↑ LocalRAGRetriever 内部调用 search_knowledge() 已自动走 LlamaIndex
```

---

## 3. 已完成的实现

### Phase 1：基础适配层 ✅

**3.1 安装依赖**

```
llama-index-core>=0.12.0
```

> **注意**：以下包在 PyPI 中 **不存在**，不要安装：
> - ~~`llama-index-embeddings-litellm`~~ — 用自定义 `ATMEmbedding` 替代
> - ~~`llama-index-vector-stores-sqlite`~~ — sqlite-vec 无官方集成，用自定义 `ATMVectorStore` 替代
> - ~~`llama-index-postprocessor-flag-embedding-reranker`~~ — 用自定义 `ATMReranker` 桥接现有 litellm rerank

**3.2 Adapter 目录结构**

```
shared/infra/search/llamaindex_adapter/
├── __init__.py          # 导出核心组件
├── embedding.py         # ATMEmbedding — 桥接 aembed_texts() → BaseEmbedding
├── vector_store.py      # ATMVectorStore — 桥接 vector_search() → BasePydanticVectorStore
├── reranker.py          # ATMReranker — 桥接 rerank_chunks() → BaseNodePostprocessor
└── retriever.py         # ATMKnowledgeRetriever + build_knowledge_retriever() 工厂
```

**3.3 ATMEmbedding**

- 继承 `llama_index.core.embeddings.BaseEmbedding`
- 内部调用现有 `aembed_texts()`，复用 LiteLLM + config.yaml 配置
- 支持 async + sync

**3.4 ATMVectorStore**

- 继承 `BasePydanticVectorStore`
- `aquery()` 内部调用 `knowledge_repo.vector_search()`
- `add()` / `delete()` 为 no-op（写入仍走 ingest pipeline）
- 自动管理 DB session

**3.5 ATMReranker**

- 继承 `BaseNodePostprocessor`
- 内部将 `NodeWithScore` ↔ `RetrievedChunk` 互转
- 调用现有 `rerank_chunks()`（litellm.arerank）

**3.6 ATMKnowledgeRetriever**

- 组合 `VectorStoreIndex` + `ATMEmbedding` + `ATMVectorStore` + `ATMReranker`
- 工厂函数 `build_knowledge_retriever(subject, top_k)` 一行创建
- 当 rerank 启用时自动 fetch 3x candidates

---

### Phase 2：业务代码接入 ✅

**已替换的调用点：**

| 文件 | 改动 |
|------|------|
| `interact/support/retrieval.py` | 移除手写 `RetrievalPipeline`，改用 `build_knowledge_retriever()` |
| `search/api.py` → `search_knowledge()` | 移除手动 embed + vector_search + rerank，改用 `build_knowledge_retriever()` |

**自动受益的调用方（无需修改）：**

| 文件 | 原因 |
|------|------|
| `retrievers/local_rag.py` | 内部调用 `search_knowledge()`，已自动走新路径 |
| `tools/builtin/search_kb.py` | 内部调用 `search_knowledge()` |
| `teaching/context.py` | 内部调用 `search_knowledge()` |

---

### Phase 3：清理 ✅

- `knowledge.py` 中的 `RetrievalPipeline` 已标记为 deprecated
- `RetrievedChunk`、`RetrievalConfig`、`rerank_chunks()` 保留（多处引用）

---

## 4. 迁移风险与缓解

| 风险 | 缓解措施 |
| --- | --- |
| LlamaIndex 版本更新频繁，API 不稳定 | 只依赖 `llama-index-core` 的稳定接口，adapter 层隔离变化 |
| 引入新依赖增加包体积 | 只安装 `llama-index-core`，不装完整 `llama-index` |
| 性能回退 | adapter 底层调用完全相同的 DB 函数，功能等价 |
| 现有 runtime cache 失效 | `LocalRAGRetriever` 等仍通过 `search_knowledge()` 进入新路径，cache 机制不受影响 |

---

## 5. 不迁移的部分

- **LangGraph workflow 骨架**：interact/digest/examine/profile 的 graph 结构不动
- **SSE streaming**：保持现有 `SSEEventEmitter` 机制
- **Teaching 层**：teaching tools、context、documents 不受影响
- **SourceCurator**：教育场景的来源排序逻辑保留
- **ContextCompressor**：压缩逻辑保留
- **knowledge_repo.py 底层 SQL**：adapter 桥接到这里，不改底层存储

---

## 6. 未来扩展（超出本次范围）

| 步骤 | 内容 | 前置条件 |
| --- | --- | --- |
| Next 1 | Digest chapter research 接入 sub-question engine | 本次迁移完成 |
| Next 2 | Hybrid retrieval (vector + keyword) | Next 1 |
| Next 3 | Vector store 迁移（替换 sqlite-vec 为 LlamaIndex 原生 store） | Next 1 |
| Next 4 | LangSmith callback 桥接（将 LlamaIndex 事件映射到 LangSmith span） | Next 1 |
