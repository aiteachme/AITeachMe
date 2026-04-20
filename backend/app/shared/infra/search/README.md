# Search 分层说明

`app.shared.infra.search` 是统一的“检索与资料获取层”，不是纯 `rag/` 目录。

这里同时承载三类能力：

- `retrievers/`
  负责发现候选资料来源，例如 Web 搜索、学术搜索、本地 `local_rag` 入口。
- `readers/`
  负责把 URL 读取并解析成结构化可消费内容，例如 HTML / PDF / DOCX / PPTX / Markdown / TXT。
- `knowledge.py`
  负责本地知识库检索契约，例如 `RetrievedChunk`、`RetrievalPipeline`、`rerank_chunks`。
- `llamaindex_index/`
  负责本地知识库向量索引生命周期，包括写入、持久化、检索和删除。

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
├── llamaindex_index/      # LlamaIndex subject index 管理
├── source_curation.py     # 来源筛选整理
├── context_compression.py # 上下文压缩
├── types.py               # SearchResult / ScrapedPage 等类型
├── retrievers/            # 候选结果发现层
│   └── sites/             # 站点限定检索器，含中文 OER / wiki 资源
└── readers/               # URL 内容读取层
```

这套结构暂时不建议继续拆成更多顶层包。

原因是当前复杂度主要来自“搜索完整链路”本身，而不是目录混乱：

- `api.py` 是工作流优先使用的薄入口。
- `web.py` 是内部调度器，承载本地优先、并发、超时和融合。
- `factory.py` 是注册表解析层，隔离“配置名字 -> 可用实例”的细节。
- `retrievers/` 与 `readers/` 的边界清楚：前者找 URL，后者读 URL。
- `knowledge.py` 与 `llamaindex_index/` 只服务本地 subject 知识检索。
- `retrievers/sites/` 只放“限定到某个具体网站”的适配器，不和 Tavily / Bing / DuckDuckGo 这类通用 provider 混放。

如果继续重构，推荐方向不是移动文件，而是减少 workflow 直接接触底层参数：

- 普通 workflow 只调用 `app.shared.infra.search.web_search()`。
- 只有 search 层内部或专门测试才直接调用 `dispatch_web_search()`。
- 只有需要列出可用 provider / reader 时才进入 `factory.py`。

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
- `jina`
  可选 Jina Reader。默认不启用，设置 `JINA_READER_ENABLED=true` 后参与自动 reader 选择；也可通过 preferred reader 显式指定。适合普通 HTML 抓取质量差、正文噪声重或动态页面较多的外部资料。
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
  基于官方 MediaWiki Search API 的免 key 检索。默认 profile 会启用，用于补充百科定义与中英术语解释。
- `zh_wikibooks` / `zh_wikiversity` / `zh_wikipedia` / `zh_wiktionary`
  中文 Wikimedia 检索器，统一放在 `retrievers/sites/`。它们基于对应站点的 MediaWiki API，不是通用网页搜索；适合高等数学、微积分、数学分析等中文概念解释和课程式页面补充。
  其他 wiki 站点如果要接入，优先复用 `sites/mediawiki.py`；不要为每个 MediaWiki 站点复制一套 HTTP 逻辑。当前没有默认接入 Wikisource / Wikiquote / Commons，因为它们更偏原始文本、引文或媒体素材，不是概念解释主源。
- `oi_wiki`
  OI Wiki 站点限定检索器。它优先调用 OI Wiki 站内搜索端点；端点不可用时才退回 DuckDuckGo 站点检索。适合离散数学、线性代数、概率、组合等偏计算机/竞赛数学知识。
- `duckduckgo`
  通用 Web 搜索，优先尝试 `duckduckgo_search` 包，缺包时退回 DuckDuckGo HTML / Lite 页面解析。
- `searxng`
  可选的 metasearch retriever，需要配置 `SEARXNG_BASE_URL`。
- `tavily` / `bing` / `bocha`
  这些属于 API 型检索器，需要用户提供 key。
- `brave` / `exa` / `jina_search`
  这些属于 API 型检索器，适合补充高质量通用 Web 结果或语义搜索结果。
- `google_cse` / `searchapi` / `serpapi`
  Google 搜索结果 API。三者能力重叠，通常按已有账号选择一个即可。
- `perplexity` / `openrouter_search` / `baidu_ai_search`
  这些属于答案型搜索 API。当前 search 层只抽取其返回的 citations / references 为 `SearchResult`，不在 search 层直接消费最终答案。
- `serper`
  Google SERP / Scholar API 检索器，可通过 `SERPER_SEARCH_MODE=search|scholar` 切换普通搜索和学术搜索。
- `arxiv` / `semantic_scholar`
  这两类更偏学术资料补充，不适合作为中文通用搜索引擎的完全替代。
- `pubmed_central`
  PubMed / PMC 文献全文检索，适合医学、生命科学、药学等资料补充。
- `custom_endpoint`
  自定义 HTTP 检索端点，适合接企业/学校已有搜索系统。返回 JSON 中的 `results/items/data/documents` 会被规整为 `SearchResult`。
- `mcp_search`
  调用已连接 MCP 工具做检索，需要配置 `MCP_SEARCH_TOOL`。它只是工具结果适配器，不会启动额外的研究 agent。
- `baidu_baike` / `zhihu`
  统一放在 `retrievers/sites/`，复用 DuckDuckGo 的站点限定搜索。它们是普通站点来源，不标记为 OER；只用于中文百科定义与经验型讨论补充。

所有 retriever 的输入统一为：

```python
search(query: str, *, max_results: int = 5) -> list[SearchResult]
```

所有输出统一收敛为 `SearchResult(url, title, snippet, score, source)`；provider 原始字段清洗、空值过滤和数量裁剪在 retriever 内完成。

## 检索调用链

对 workflow 开发者来说，核心链路只有 4 层：

1. `settings.support.RETRIEVER_PROFILES`
   定义不同场景默认用哪些 retriever，以及它们的顺序。
2. `search.factory.get_retrievers_for_subject()`
   按 profile 把名字解析成 retriever 实例。
3. workflow 调用 retriever
   `digest/planner/nodes/retrieve_planning_evidence.py` 和 `digest/docgen/lib/chapter_context.py` 会逐个执行 retriever。
4. `readers/`
   当 retriever 返回外部 URL 后，再由 `read_urls()` 选择合适 reader 把网页 / PDF / DOCX / PPTX 读出来。

## `dispatch_web_search()` 参数说明

`dispatch_web_search()` 是底层调度器，参数看起来多，是为了让不同 workflow 共用一套调度逻辑。

日常业务代码不应该优先调用它，而应该用 `api.py` 暴露的 `web_search()`。

| 参数 | 作用 | 是否常用 |
| --- | --- | --- |
| `query` | 搜索 query。空字符串会直接返回空列表。 | 必填 |
| `top_k` | 最终返回多少条融合后的结果。每个 provider 也最多请求这个数量。 | 常用 |
| `subject` | 当前学科 slug。传了以后 `local_rag` 才能查 subject 的本地向量索引。 | Digest / Chat 常用 |
| `local_sections` | 还没进入向量索引的本地片段，用于 planner 草稿、临时材料等场景。 | 少量 workflow 用 |
| `profile` | 检索 profile 名，决定启用哪些 retriever 和顺序。为空则使用 settings 默认逻辑。 | 高级场景 |
| `total_timeout_s` | 本次搜索总预算。为空走 `settings.search.total_timeout_s`。 | 测试/特殊链路 |
| `provider_timeout_s` | 单个 provider 最多等多久。为空走 `settings.search.provider_timeout_s`。 | 测试/特殊链路 |

这些参数不是每个调用点都该传。

推荐用法：

```python
from app.shared.infra.search import web_search

results = await web_search(query, top_k=5, subject=subject)
```

只有需要覆盖 profile 或 timeout 时，才从 `search.web` 直接调度。

## 两条典型链路

### planner

- `retrieve_planning_evidence` 节点
  先用 `local_rag` 找上传资料里的 section。
- 如果本地命中不够，再用资料主题和草稿章节做少量本地补查；如允许外部搜索，再按 profile 顺序尝试外部 retriever。
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

## Web 检索调度策略

`dispatch_web_search()` 现在只在 search 层内部做并发与融合，不改变 workflow 的业务编排：

1. 先执行 `local_rag`，保证上传资料优先。
2. 如果本地结果不足 `top_k`，外部 retriever 在总预算内并发执行。
3. 多 provider 结果使用轻量 RRF（Reciprocal Rank Fusion）变体融合；重复 URL 会合并，多个 provider 同时命中的来源会获得更高分。
4. 下游仍由 `SourceCurator`、reader、`ContextCompressor` 继续完成来源质量排序、正文读取和上下文压缩。

相关配置可放在 `settings_default.yaml`：

```yaml
search:
  provider_timeout_s: 6.0
  total_timeout_s: 12.0
  parallel_retrievers: true
  max_parallel_retrievers: 4
  fusion_k: 60
```

之前效果和速度差的关键原因不是“少一个 provider”，而是检索链路过于串行、过早信任单 provider 的前几条结果、缺少融合。OpenAI / Gemini 级搜索体验本质上是“搜索 + 阅读 + 压缩 + 引用 + 生成”的组合；本层只解决候选来源发现与读取入口，生成和引用仍由上层 workflow 控制。

## 配置建议

- 完全无 key 的最小可用组合：
  `local_rag + duckduckgo`
- 中文学习资料 / 高等数学类知识文档：
  使用 `docgen_zh_oer` 或 `docgen_zh_math` profile。内置 `docgen_sprint` / `docgen_systematic` 也会优先尝试中文 OER，再进入通用搜索。
- 想继续提升稳定性但不想买 API：
  再加一个自建或可信公共 `SearXNG` 实例。
- 已有商业 key：
  再打开 `tavily / bocha / brave / exa / bing / google_cse / serper / serpapi / searchapi`，把它们放到 profile 前面即可。
- 医学/生命科学资料：
  打开 `pubmed_central`，必要时配置 `NCBI_API_KEY` 提高请求限额。
- 已有内部搜索系统：
  配置 `CUSTOM_RETRIEVER_ENDPOINT`，并让端点返回 `url/title/snippet` 或兼容字段。
- 网页正文读取质量差：
  打开 `JINA_READER_ENABLED=true`，必要时配置 `JINA_API_KEY` 提高限额。
