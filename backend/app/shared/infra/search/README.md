# Search 分层说明

`app.shared.infra.search` 是统一的“检索与资料获取层”，不是纯 `rag/` 目录。

这里同时承载三类能力：

- `retrievers/`
  负责发现候选资料来源，例如 Web 搜索、学术搜索、本地 `local_rag` 入口。
- `readers/`
  负责把 URL 读取并解析成结构化可消费内容，例如 HTML / PDF / DOCX / PPTX / Markdown / TXT。
- `knowledge.py`
  负责本地知识库检索契约，例如 `RetrievedChunk`、`RetrievalPipeline`、`rerank_chunks`。

## 为什么不改名成 `rag`

- 这里不只做本地向量检索。
- Web 检索 provider、URL reader、source curation、context compression 都在这一层。
- `rag` 只适合描述其中“本地知识检索”的那一支，不足以覆盖整层语义。

## 当前推荐结构

```text
shared/infra/search/
├── __init__.py            # 对外稳定入口
├── api.py                 # web_search / search_knowledge 统一入口
├── web.py                 # 多 retriever 调度
├── factory.py             # retriever / reader 选择
├── knowledge.py           # 本地知识检索契约与 rerank
├── source_curation.py     # 来源筛选整理
├── context_compression.py # 上下文压缩
├── types.py               # SearchResult / ScrapedPage 等类型
├── retrievers/            # 候选结果发现层
└── readers/               # URL 内容读取层
```

## 命名约定

- `retriever`
  负责“找什么来源”。
- `reader`
  负责“把这个 URL 读出来并解析成可消费内容”。
- `knowledge`
  负责“如何在本地知识库里检索、聚合、rerank”。

## 当前内置 readers

- `bs4`
  通用 HTML 页面读取。
- `pdf`
  远程 PDF 文本抽取。
- `docx`
  远程 Word 文档文本抽取。
- `pptx`
  远程 PowerPoint 文本抽取。
- `text`
  远程 Markdown / TXT / RST 文本抽取。

外部调用时优先从 `app.shared.infra.search` 或 `app.shared.infra.search.readers` 导入。

`app.shared.infra.retrievers` 与 `app.shared.infra.reranker` 目前只保留兼容 shim，不再作为新的 canonical 入口。
