# 09. AI 技术栈与 Infra 接入指南

最后更新：2026-04-19

本文说明当前 AI 能力和基础设施如何接入代码，不再记录历史重构计划。

## 1. 总原则

AITeachMe 的 AI 工程分三层：

```text
规则层：校验、状态流转、客观判分、路径处理
模型层：生成、抽取、改写、判定、OCR
工作流层：多步骤长流程、并发、失败恢复、观测
```

原则：

- 不把所有问题都丢给大模型。
- 代码要优先消费结构化输出。
- Search 只找来源，不直接产最终教学答案。
- Workflow 决定业务策略，Infra 只接能力。

## 2. 当前核心技术栈

| 能力 | 当前技术 / 入口 |
| --- | --- |
| LLM 文本/结构化/流式 | `shared.infra.llm_support` + LiteLLM |
| Embedding | `shared.infra.embedding` |
| Workflow | LangGraph + `shared.infra.workflow` |
| 本地向量索引 | `shared.infra.search.llamaindex_index` |
| 检索与读取 | `shared.infra.search` |
| 工具执行 | `shared.infra.tools` |
| MCP | `shared.infra.mcp` |
| 存储 | `shared.infra.storage` |
| 观测 | `shared.infra.observability` |

## 3. 模型路由

模型名来自代码默认值与可选项目 override，用户可在设置页保存非敏感覆盖。

当前逻辑名：

| 逻辑模型 | 用途 |
| --- | --- |
| `reason` | 规划、复杂判断、深度推理 |
| `primary` | 对话、写作、出题、批改等主文本生成 |
| `light` | 分类、摘要、批量轻任务、Mermaid 文本生成 |
| `embedding` | 向量检索 |
| `rerank` | 检索重排序 |
| `ocr` | Vision OCR，空值时使用 primary |
| `speech_to_text` | 音转文 |
| `text_to_speech` | 文转音 |
| `image_generation` | 文生图，空值时禁用真实图片生成 |
| `video_generation` | 视频生成，空值时禁用 |

注意：

- `TaskType` 表示业务语义、温度、超时、重试和观测分类。
- 模型选择优先显式传 `model="reason" / "primary" / "light"`。
- `extract` 现在只保留为兼容别名，内部默认回退到 `light`，不再作为独立模型分类继续扩展。
- Mermaid 不再有独立模型配置，直接走普通轻量文本模型。

## 4. 结构化输出

凡是后续会被代码消费的 LLM 结果，都优先 Pydantic / structured output。

典型场景：

- Planner plan intent / plan draft。
- DocGen chapter contract、evidence ledger、review report。
- KG 抽取与解析。
- Examine 出题和判卷结果。
- Profile 报告和建议。

规则：

- schema 字段少而稳。
- 字段含义能落库、渲染或被后续 workflow 消费。
- 失败要可重试、可降级、可记录。

## 5. Search / RAG

Search 层只做检索相关的几件事：

1. 找来源：本地 RAG、通用搜索、站点检索、学术检索。
2. 读来源：HTML / PDF / DOCX / PPTX / Markdown / TXT。
3. 压缩材料：把来源整理成 workflow 可消费的上下文。

Search 层只返回候选资料，后续怎么组织内容由调用方决定。

### 5.1 稳定调用接口

普通 workflow 优先用包级入口：

```python
from app.shared.infra.search import search_knowledge, web_search

results = await web_search(
    "高等数学 导数 定义",
    top_k=5,
    subject_id=subject_id,
)

chunks = await search_knowledge(
    "导数的几何意义",
    subject_id=subject_id,
    top_k=5,
)
```

只有需要覆盖 profile / timeout，或 search 层内部调度时，才使用底层调度器：

```python
from app.shared.infra.search.web import dispatch_web_search

results = await dispatch_web_search(
    "线性代数 矩阵 特征值",
    top_k=5,
    subject_id=subject_id,
    profile="docgen_zh_math",
)
```

只有调试或单独验证某个 retriever 时，才直接解析 retriever。执行时优先走 `traced_search()`，不要绕过 trace / cache：

```python
from app.shared.infra.search.factory import get_retriever

retriever = get_retriever("oi_wiki")
results = await retriever.traced_search("线性代数", max_results=5)
```

### 5.2 内部结构

当前 search 包包含：

- 本地 `local_rag`
- 外部 retriever
- reader
- source curation
- context compression
- rerank

核心文件：

| 文件 / 目录 | 作用 |
| --- | --- |
| `api.py` | `web_search()` / `search_knowledge()` 工作流入口 |
| `web.py` | 多 retriever 调度、超时、并发、RRF 融合 |
| `factory.py` | retriever / reader 注册表解析 |
| `retrievers/` | 候选来源发现 |
| `retrievers/sites/` | 明确站点适配器，不是任意网站抓取 |
| `readers/` | URL 正文读取 |
| `source_curation.py` | 来源轻量排序和去噪 |
| `context_compression.py` | 检索后上下文压缩 |

### 5.3 已接入 retriever

```text
local_rag
duckduckgo
zh_wikibooks / zh_wikiversity / zh_wikipedia / zh_wiktionary / oi_wiki
wikipedia
tavily / bocha / brave / exa / bing
google_cse / serper / serpapi / searchapi
perplexity / openrouter_search / baidu_ai_search
arxiv / semantic_scholar / pubmed_central
baidu_baike / zhihu
jina_search / mcp_search
```

### 5.4 结果契约

所有 retriever 的输入统一为：

```python
search(query: str, *, max_results: int = 5) -> list[SearchResult]
```

所有输出统一收敛为：

```python
SearchResult(
    url: str,
    title: str,
    snippet: str,
    score: float = 0.0,
    source: str = "",
)
```

`retriever` 只返回候选来源；是否打开 URL、是否压缩正文、是否写进教材，由上层 workflow 决定。

### 5.5 Profile 与实际调用

检索 profile 的优先级：

1. `settings.search.retrievers`
   显式 retriever 列表，逗号分隔。只建议调试或特殊部署使用。
2. 调用方传入的 `profile` 或 `settings.search.retriever_profile`
   例如 `docgen_zh_edu`、`docgen_zh_math`。
3. fallback
   默认 `duckduckgo`。

如果传入 `subject` 或 `local_sections`，`local_rag` 会按 `local_rag.priority` 优先参与；否则自动跳过，避免无上下文本地检索。

当前无额外 key 时的主要 profile：

| Profile | 用途 | 可用外部 retriever |
| --- | --- | --- |
| `planner_fast` | Planner 轻量补充 | `wikipedia`、`baidu_baike`、`zhihu`、`arxiv`、`semantic_scholar`、`pubmed_central`、`duckduckgo` |
| `planner_grounding` | Planner 稳定 grounding | 中文教育站点 + `wikipedia`、学术源、`duckduckgo` |
| `docgen_sprint` | 冲刺讲义章节研究 | 中文教育站点 + `wikipedia`、学术源、`duckduckgo` |
| `docgen_systematic` | 系统讲义章节研究 | 中文教育站点 + `wikipedia`、学术源、`duckduckgo` |
| `docgen_zh_edu` | 中文课程式解释优先 | `zh_wikibooks`、`zh_wikiversity`、`zh_wikipedia`、`zh_wiktionary`、`oi_wiki`、`duckduckgo` |
| `docgen_zh_math` | 中文数学 / 高数 / 线代补充 | `zh_wikibooks`、`zh_wikiversity`、`zh_wikipedia`、`oi_wiki`、`zh_wiktionary`、`arxiv`、`semantic_scholar`、`duckduckgo` |

需要 key 或 base URL 的 provider 未配置时自动跳过；workflow 不需要手动判断。

### 5.6 DocGen 当前调用方式

DocGen 没有直接调用 `web_search()`，而是在章节研究运行时直接使用 retriever 实例，这是正确的。原因是 DocGen 要做多轮研究、局部 fallback、统计每个 retriever 的命中情况，并控制每章的总预算。

当前链路：

```text
load_context
-> confirmed plan 解析 retrieval_profile
-> generate_chapters
-> DocGenChapterContextRuntime.execute()
-> LocalRAGRetriever 先跑
-> 本地命中不足时，按 profile 解析外部 retriever
-> retriever.traced_search()
-> SourceCurator
-> read_urls()
-> ContextCompressor
-> dense_context 给章节 writer
```

关键点：

- `local_rag` 总是章节研究第一优先级。
- 只有 `local_hits < settings.local_rag.min_results` 才触发外部 retriever。
- DocGen 还有一层稳定性 allowlist。`zh_wikibooks`、`zh_wikiversity`、`zh_wikipedia`、`zh_wiktionary`、`oi_wiki` 已允许参与；`baidu_baike`、`zhihu` 不作为章节正文深读主来源。
- 外部网页不会直接变成正文，仍会经过读取、过滤、压缩和章节写作。

### 5.7 命名规则

- retriever 使用小写 snake_case，并且名字表达来源，不表达调用细节。
- profile 使用 `场景_语言_用途` 或 `场景_模式`，例如 `docgen_zh_edu`、`docgen_zh_math`、`docgen_sprint`。
- 具体网站统一放到 `shared.infra.search.retrievers.sites`，例如 `oi_wiki`、`zh_wikibooks`。
- 不保留泛化抓站入口；具体网站需要显式站点适配器。

## 6. Ingest 解析栈

当前解析策略不是“一个万能 parser”，而是：

```text
分类 -> 解析计划 -> parser chain -> Markdown canonicalize -> 后台增强
```

常用能力：

- 文本快速通道。
- MarkItDown / PyMuPDF / PyMuPDF4LLM 等本地 parser。
- MinerU 外部解析。
- Vision OCR。
- assets 规范化。

## 7. 观测

观测分两层：

- LangSmith trace：研发排障。
- progress / build status：前端展示。

当前可记录：

- 模型名。
- token / cost。
- 耗时。
- 检索 provider。
- reader 结果。
- cache hit。
- workflow 节点状态。

## 8. 不再使用的抽象

以下抽象已经删除或不再作为正式架构：

- `shared.infra.facade`
- `shared.infra.guardrails`
- `app.services`
- `app.teaching`
- 独立 prompt 扩展层

## 9. 一句话

当前 AI 路线是：

```text
稳定材料层 + 结构化合同 + 显式 workflow + 可追踪来源
```

不是把系统改成一个黑盒大 Agent。
