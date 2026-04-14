# LlamaIndex 渐进式迁移方案

> 最后更新：2026-04-14
>
> 原则：渐进式替换，不动 workflow graph 骨架，不动 LangSmith 观测面，先在 `shared/infra/search` 做 adapter，验证质量后再扩展。

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
- LangSmith 观测面不动（LlamaIndex callback 桥接到 LangSmith）
- SSE streaming 不动
- teaching 层不动

---

## 2. 当前架构 vs 目标架构

```
当前：
  interact/retrieve_context → aembed_texts() → vector_search() → RetrievalPipeline → rerank
  digest/chapter_context    → get_retrievers_for_subject() → micro-loop → SourceCurator → ContextCompressor

目标：
  interact/retrieve_context → LlamaIndex VectorStoreIndex.as_retriever() → NodePostprocessor chain
  digest/chapter_context    → LlamaIndex QueryEngine (sub-question) → ResponseSynthesizer
                              ↑ 外部 retriever 仍走现有 BaseRetriever adapter
```

---

## 3. 分阶段迁移计划

### Phase 1：基础适配层（不改业务代码）

目标：在 `shared/infra/search` 下建立 LlamaIndex adapter，让现有代码可以选择性使用。

**3.1 安装依赖**

```
llama-index-core
llama-index-embeddings-litellm        # 复用现有 LiteLLM embedding 配置
llama-index-vector-stores-sqlite      # 本地开发用（对齐现有 sqlite-vec）
llama-index-postprocessor-flag-embedding-reranker  # 替代手动 rerank
```

**3.2 新建 adapter 文件**

```
shared/infra/search/
├── llamaindex_adapter/
│   ├── __init__.py
│   ├── embedding.py          # 桥接现有 aembed_texts() 到 LlamaIndex BaseEmbedding
│   ├── vector_store.py       # 桥接现有 sqlite-vec 到 LlamaIndex VectorStore
│   ├── retriever.py          # 包装现有 BaseRetriever 为 LlamaIndex BaseRetriever
│   ├── postprocessors.py     # SourceCurator + ContextCompressor 包装为 NodePostprocessor
│   └── callback.py           # LlamaIndex callback → LangSmith span 桥接
```

**3.3 Embedding adapter**

```python
# shared/infra/search/llamaindex_adapter/embedding.py
from llama_index.core.embeddings import BaseEmbedding
from app.shared.infra.embedding import aembed_texts, get_embedding_model_name

class ATMEmbedding(BaseEmbedding):
    """桥接现有 LiteLLM embedding 到 LlamaIndex。"""

    model_name: str = ""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.model_name = get_embedding_model_name()

    def _get_text_embedding(self, text: str) -> list[float]:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            aembed_texts([text])
        )[0]

    async def _aget_text_embedding(self, text: str) -> list[float]:
        result = await aembed_texts([text])
        return result[0]

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            aembed_texts(texts)
        )

    async def _aget_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return await aembed_texts(texts)

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._get_text_embedding(query)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return await self._aget_text_embedding(query)
```

**3.4 VectorStore adapter**

```python
# shared/infra/search/llamaindex_adapter/vector_store.py
from llama_index.core.vector_stores.types import BasePydanticVectorStore, VectorStoreQuery, VectorStoreQueryResult
from app.shared.infra.search import search_knowledge

class ATMVectorStore(BasePydanticVectorStore):
    """桥接现有 sqlite-vec 向量搜索到 LlamaIndex。"""

    subject: str = ""
    stores_text: bool = True
    is_embedding_query: bool = True

    async def aquery(self, query: VectorStoreQuery, **kwargs) -> VectorStoreQueryResult:
        # 调用现有 search_knowledge()
        chunks = await search_knowledge(
            query=query.query_str or "",
            subject=self.subject,
            top_k=query.similarity_top_k or 5,
        )
        # 转换为 LlamaIndex 格式
        ...
```

**3.5 外部 Retriever adapter**

```python
# shared/infra/search/llamaindex_adapter/retriever.py
from llama_index.core.retrievers import BaseRetriever as LIBaseRetriever
from llama_index.core.schema import NodeWithScore, TextNode
from app.shared.infra.search.retrievers.base import BaseRetriever as ATMRetriever

class ATMRetrieverAdapter(LIBaseRetriever):
    """包装现有 ATM retriever 为 LlamaIndex retriever。"""

    def __init__(self, atm_retriever: ATMRetriever):
        super().__init__()
        self._atm = atm_retriever

    async def _aretrieve(self, query_str: str, **kwargs) -> list[NodeWithScore]:
        results = await self._atm.traced_search(query_str)
        return [
            NodeWithScore(
                node=TextNode(text=r.snippet, metadata={"url": r.url, "title": r.title, "source": r.source}),
                score=r.score,
            )
            for r in results
        ]
```

**3.6 LangSmith callback 桥接**

```python
# shared/infra/search/llamaindex_adapter/callback.py
from llama_index.core.callbacks import CallbackManager, CBEventType, LlamaDebugHandler

class LangSmithCallbackHandler(LlamaDebugHandler):
    """将 LlamaIndex 事件桥接到 LangSmith span。"""
    # 把 RETRIEVE / QUERY / RERANKING 等事件映射为 LangSmith child span
    ...
```

---

### Phase 2：Interact 引擎接入（第一个业务消费者）

目标：让 interact 的 `retrieve_context` 节点可以选择走 LlamaIndex pipeline。

**2.1 新建 LlamaIndex query engine 工厂**

```python
# shared/infra/search/llamaindex_adapter/query_engine.py

async def build_interact_query_engine(subject: str, top_k: int = 5):
    """为 interact 构建 LlamaIndex query engine。"""
    from llama_index.core import VectorStoreIndex

    embed = ATMEmbedding()
    vector_store = ATMVectorStore(subject=subject)
    index = VectorStoreIndex.from_vector_store(vector_store, embed_model=embed)

    retriever = index.as_retriever(similarity_top_k=top_k)

    # 可选：加 reranker postprocessor
    postprocessors = []
    if settings.rag_rerank_model:
        from llama_index.postprocessor.flag_embedding_reranker import FlagEmbeddingReranker
        postprocessors.append(FlagEmbeddingReranker(top_n=top_k))

    return retriever, postprocessors
```

**2.2 修改 interact retrieve_context 节点**

在 `workflows/interact/nodes/retrieve.py` 中加一个 feature flag：

```python
if settings.use_llamaindex_retrieval:
    retriever, postprocessors = await build_interact_query_engine(subject, top_k)
    nodes = await retriever.aretrieve(question)
    for pp in postprocessors:
        nodes = pp.postprocess_nodes(nodes)
    # 转换回 RetrievedContext
else:
    # 走现有 RetrievalPipeline
```

**2.3 A/B 对比验证**

- 同一批问题，分别走旧 pipeline 和 LlamaIndex pipeline
- 对比：retrieval 质量（relevance）、延迟、token 消耗
- 通过 LangSmith trace 对比两条路径

---

### Phase 3：Digest research 接入

目标：让 digest 的 chapter research micro-loop 可以使用 LlamaIndex 的 sub-question query engine。

**3.1 Sub-question decomposition**

```python
from llama_index.core.query_engine import SubQuestionQueryEngine
from llama_index.core.tools import QueryEngineTool

# 为每个 retriever 创建 query engine tool
tools = [
    QueryEngineTool.from_defaults(
        query_engine=local_rag_engine,
        name="local_knowledge",
        description="搜索用户上传的学习资料",
    ),
    QueryEngineTool.from_defaults(
        query_engine=web_engine,
        description="搜索网络教育资源",
    ),
]

# sub-question engine 自动拆分复杂查询
engine = SubQuestionQueryEngine.from_defaults(query_engine_tools=tools)
```

**3.2 替换 micro-loop 中的 query planning**

当前 `chapter_context.py` 的 `generate_sub_queries()` 可以用 LlamaIndex 的 sub-question decomposition 替代，但保留现有的 coverage assessment 和 gap detection 逻辑。

**3.3 hybrid retrieval**

```python
from llama_index.core.retrievers import QueryFusionRetriever

# 融合 vector + keyword 检索
hybrid_retriever = QueryFusionRetriever(
    retrievers=[vector_retriever, keyword_retriever],
    num_queries=3,  # 自动生成多个查询变体
    use_async=True,
)
```

---

### Phase 4：Vector Store 迁移准备

目标：为未来 PostgreSQL + pgvector 迁移做准备。

**4.1 替换 sqlite-vec**

```python
# 本地开发
from llama_index.vector_stores.sqlite import SQLiteVectorStore

# 生产环境
from llama_index.vector_stores.postgres import PGVectorStore
```

**4.2 统一 ingestion pipeline**

```python
from llama_index.core.ingestion import IngestionPipeline
from llama_index.core.node_parser import SentenceSplitter

pipeline = IngestionPipeline(
    transformations=[
        SentenceSplitter(chunk_size=512, chunk_overlap=50),
        ATMEmbedding(),
    ],
    vector_store=vector_store,
)
```

这一步可以替代当前 ingest 后的 chunk embedding 流程，但 ingest 的解析和分类逻辑保持不变。

---

## 4. 迁移风险与缓解

| 风险 | 缓解措施 |
| --- | --- |
| LlamaIndex 版本更新频繁，API 不稳定 | 只依赖 `llama-index-core` 的稳定接口，adapter 层隔离变化 |
| 引入新依赖增加包体积 | 只安装必要的 integration 包，不装完整 `llama-index` |
| LangSmith 观测面断裂 | callback 桥接层保证 trace 连续性 |
| 性能回退 | feature flag 控制，A/B 对比后再切换 |
| 现有 runtime cache 失效 | adapter 层复用现有 `SearchRuntimeCache` |

---

## 5. 不迁移的部分

- **LangGraph workflow 骨架**：interact/digest/examine/profile 的 graph 结构不动
- **SSE streaming**：保持现有 `SSEEventEmitter` 机制
- **Teaching 层**：teaching tools、context、documents 不受影响
- **SourceCurator**：教育场景的来源排序逻辑保留，包装为 NodePostprocessor
- **ContextCompressor**：压缩逻辑保留，包装为 NodePostprocessor

---

## 6. 实施顺序与时间线

| 步骤 | 内容 | 前置条件 |
| --- | --- | --- |
| Step 1 | 安装依赖 + 建 adapter 目录骨架 | 无 |
| Step 2 | 实现 ATMEmbedding adapter | Step 1 |
| Step 3 | 实现 ATMVectorStore adapter | Step 2 |
| Step 4 | 实现 ATMRetrieverAdapter | Step 1 |
| Step 5 | 实现 LangSmith callback 桥接 | Step 1 |
| Step 6 | Interact retrieve_context 加 feature flag | Step 2-5 |
| Step 7 | A/B 对比验证 interact retrieval 质量 | Step 6 |
| Step 8 | 确认质量后，默认切换 interact 到 LlamaIndex | Step 7 |
| Step 9 | Digest chapter research 接入 sub-question engine | Step 8 |
| Step 10 | Hybrid retrieval 替换现有 micro-loop query planning | Step 9 |
| Step 11 | Vector store 迁移准备（pgvector adapter） | Step 8 |
