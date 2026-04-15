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

不要再从 `app.shared.infra.retrievers` 或 `app.shared.infra.reranker` 这类根层旧入口导入；检索能力统一从 `app.shared.infra.search` 及其子目录进入。

## 当前内置 retrievers

- `local_rag`
  优先基于当前 subject 的本地 section / chunk 做检索，是上传资料驱动场景的第一入口。
- `wikipedia`
  基于官方 MediaWiki Search API 的免 key 检索。当前仍保留实现，但默认 profile 已不再启用；如果确实需要，建议显式配置后再打开。
- `duckduckgo`
  通用 Web 搜索，优先尝试 `duckduckgo_search` 包，缺包时退回 DuckDuckGo HTML / Lite 页面解析。
- `searxng`
  可选的 metasearch retriever，需要配置 `SEARXNG_BASE_URL` 或 `config.yaml` 中的 `searxng_base_url`。
- `tavily` / `bing` / `bocha`
  这些属于 API 型检索器，需要用户提供 key。
- `arxiv` / `semantic_scholar`
  这两类更偏学术资料补充，不适合作为中文通用搜索引擎的完全替代。

## 检索调用链

对 workflow 开发者来说，核心链路只有 4 层：

1. `config.support.RETRIEVER_PROFILES`
   定义不同场景默认用哪些 retriever，以及它们的顺序。
2. `search.factory.get_retrievers_for_subject()`
   按 profile 把名字解析成 retriever 实例。
3. workflow 调用 retriever
   `planner/concept_grounding.py` 和 `digest/docgen/runtime/chapter_context.py` 会逐个执行 retriever。
4. `readers/`
   当 retriever 返回外部 URL 后，再由 `read_urls()` 选择合适 reader 把网页 / PDF / DOCX / PPTX 读出来。

## 两条典型链路

### planner

- `collect_planner_concept_briefing()`
  先用 `local_rag` 找上传资料里的 section。
- 如果本地命中不够，再按 profile 顺序尝试外部 retriever。
- 当前 planner 更偏“概念锚点补充”，不会像 docgen 那样做完整 deep research。
- 外部结果会先经过一轮轻量 `SourceCurator` 排序，再对少量高优先级 URL 做 `read_urls()`，避免只靠搜索 snippet 或首条结果就直接生成章节脉络。

### docgen

- `DocGenChapterContextRuntime.execute()`
  先跑 `local_rag`。
- 当 `local_hits < settings.local_rag_min_results` 时，才触发外部 retriever fallback。
- 外部结果经过 `SourceCurator` 过滤后，再由 `read_urls()` 深读正文；`SourceCurator` 当前已补了中文短语 / 词块相关性排序，不再只偏英文分词。
- 深读结果再进入 `ContextCompressor`，最后变成章节写作用的 `dense_context`。

## 运行时缓存

当前已经落地一套最小 runtime cache，用来收口检索链路里最容易重复的 IO：

- external retriever 结果会按 `(retriever_name, query, max_results)` 做进程内 TTL 缓存
- reader 结果会按 `(reader_name, url)` 做进程内 TTL 缓存
- `ContextCompressor` 结果会按 `(query, documents, focus_terms, budgets)` 做进程内 TTL 缓存

当前策略保持刻意简单：

- 只做进程内内存缓存
- 带 TTL 和最大条目数
- 相同请求会做 inflight dedupe，避免同一轮 fan-out 重复打外部 IO
- `local_rag` 默认不缓存，避免把当前 subject 的本地知识快照误当成稳定公网结果

LangSmith 侧会在 retriever / reader / traced execution span 输出：

- `cache_status`
- `cache_hit`

后续如果继续做持久化缓存、subject-aware 隔离或跨构建共享，再单独扩展这层策略；当前不在 workflow 里重复实现第二套缓存。

## 配置建议

- 完全无 key 的最小可用组合：
  `local_rag + duckduckgo`
- 想继续提升稳定性但不想买 API：
  再加一个自建或可信公共 `SearXNG` 实例。
- 已有商业 key：
  再打开 `tavily / bocha / bing`，把它们放到 profile 前面即可。
