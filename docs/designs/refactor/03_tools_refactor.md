## 三、工具体系重构 — Skills + Actions + Retrievers + Scraper

> **最后更新**：2026-04-09 — 反映检索层第一阶段重构后的实际实现状态

### 3.1 现状分析（已更新）

**当前 AITeachMe 的工具体系**（Phase 0/1 完成后）：
- `shared/infra/skills/base.py` — `BaseSkill` 抽象基类 + `SkillContext` + `SkillResult` + `@skill` 装饰器 + `SkillRegistry`，**双模式共存**。
- `shared/infra/skills/` — 已实现 6 个业务 Skill：ResearchConductor / PedagogyWriter / ContextManager / SourceCurator / ImageGenerator / MermaidGenerator。
- `shared/infra/tools/builtin/` — 已实现 query_processing / web_scraping / web_search / search_kb / markdown_processing / latex_processing / memory_ops，并新增 `content_analysis.py` 作为教学块复用的通用分析工具。
- `shared/infra/search/retrievers/` — 工厂模式已落地，且已升级为**注册式工厂**：`BaseRetriever` 子类自动注册，后续新增 retriever 不再需要手改 `factory.py` 映射表。
- `shared/infra/search/scraper/` — 已从单纯 `BaseScraper` 升级为 **`BaseReader + BaseScraper` 双层抽象**，当前内置 BS4 + PyMuPDF 两种 reader，并通过 URL 路由自动选择。

**gpt-researcher 的工具体系**：
- `skills/` — 6 个重量级 Skill 类（ResearchConductor / ReportGenerator / ContextManager / BrowserManager / SourceCurator / ImageGenerator），每个类持有 `researcher` 引用，内部编排多个 Action。
- `actions/` — 7 个原子操作模块，纯函数式，可独立测试。
- `retrievers/` — 14 种检索器 + 工厂函数 `get_retriever(name)`。
- `scraper/` — 8 种抓取器 + 统一调度器 `Scraper` 类（URL 去重 + 类型路由 + 并行抓取）。

**当前状态**：核心融合已完成，检索层第一阶段也已落地。当前已经具备**多检索器 list/profile 配置 + Tavily / arXiv / Semantic Scholar 接入 + 注册式 retriever 工厂 + ReaderAdapter 骨架**，并开始补 `infra -> teaching` 的分层复用：先在 `infra` 提供 `content_analysis` 这类通用分析能力，再在 `teaching/documents` 里生成 glossary / coverage 等教学块。后续重点转向剩余扩展项（`bocha` 真实 API、`custom` 私有检索器、`browser/jina/firecrawl` reader、实际图片生成 API 接入）。

#### 3.1.1 GPT-Researcher 思想移植完成度评估（新增）

如果按“思想”而不是“文件数量”来评估，目前完成度大致如下：

| 思想 | GPT-Researcher 核心价值 | AITeachMe 当前状态 | 完成度 |
|:---|:---|:---|:---|
| `Plan -> Search -> Compress -> Write` | 固定链路、减少幻觉 | Planner + DocGen 已基本对齐 | **85%** |
| 分层模型策略 | Fast / Smart / Strategic 分工 | 已通过 `fallback.py` + `TaskType` 落地 | **80%** |
| 工厂化可插拔 | retriever / scraper / llm / prompt 可切换 | retriever 已较完整，reader 仍偏弱 | **70%** |
| 流式进度协议 | 用户看到研究全过程 | 已有 planner/docgen 事件，但 schema 还不够稳 | **60%** |
| 结构化中间产物 | search result / scraped data / context 分层 | `SearchResult` / `ScrapedPage` 有了，`ChapterEvidencePack` 还没正式落地 | **55%** |
| 运行护栏 | cache / rate limit / worker pool / fallback | 方向已明确，代码尚未补齐 | **40%** |
| 章节去重 | 避免多章节内容重复 | 只在 `ContextManager` 有部分能力，未成体系 | **35%** |
| 质量评估闭环 | 不只跑通，还要看报告质量 | 尚未形成自动 eval 指标 | **25%** |

**核心判断**：

- 现在不是“没学到位”，而是**最容易先做出来的 70% 已经吃掉了**
- 剩下最难但也最值钱的 30%，集中在：
  - `ChapterEvidencePack`
  - `ReaderAdapter`
  - `Cache / RateLimit / Fallback`
  - `WrittenContentDeduper`
  - `DocumentManifest`
  - `Eval / Quality Score`

所以答案不是“已经完美移植”，而是：

- **核心方法论已经基本对齐**
- **真正决定系统上限的工程骨架还没完全到位**

### 3.2 Skills 层 — BaseSkill 抽象类（✅ 已实现）

`BaseSkill` + `SkillContext` + `SkillResult` 已落地在 `shared/infra/skills/base.py`，与 `@skill` 装饰器双模式共存：

```python
# 实际实现（精简展示）— shared/infra/skills/base.py

@dataclass(slots=True)
class SkillContext:
    subject: str
    build_session_id: str = ""
    workflow_context: WorkflowContext | None = None
    planner_session_id: str = ""
    confirmed_plan_id: str = ""
    digest_mode: str = ""
    chapter_index: int | None = None
    llm_caller: Callable[..., Awaitable[Any]] | None = None
    extra_metadata: dict[str, Any] = field(default_factory=dict)

    def resolve_llm_caller(self) -> Callable[..., Awaitable[Any]]:
        return self.llm_caller or acompletion_with_fallback

    def trace_metadata(self, **extra) -> dict[str, Any]:
        """自动注入 planner_session_id / confirmed_plan_id / digest_mode / chapter_index 等追踪字段。"""
        ...

@dataclass(slots=True)
class SkillResult:
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    images: list[dict[str, Any]] = field(default_factory=list)
    cost_tokens: int = 0

class BaseSkill(ABC):
    def __init__(self, context: SkillContext) -> None:
        self.context = context
        self.logger = structlog.get_logger(__name__).bind(
            skill_name=self.name, subject=context.subject,
            build_session_id=context.build_session_id,
        )

    @abstractmethod
    async def execute(self, **kwargs: Any) -> SkillResult: ...
```

**与原设计的差异**：
- `SkillContext` 比原设计更丰富：新增 `planner_session_id` / `confirmed_plan_id` / `digest_mode` / `chapter_index` / `extra_metadata`，支持完整的 LangSmith 追踪链路
- `SkillContext.trace_metadata()` 方法自动构建追踪元数据，Skill 内部 LLM 调用无需手动拼装
- `extract_skill_result_metadata()` 辅助函数从 SkillResult 中提取日志/追踪字段

### 3.3 具体 Skill 实现 — 当前状态

```
shared/infra/skills/
├── base.py                    # ✅ BaseSkill + SkillContext + SkillResult + @skill + SkillRegistry
├── researcher.py              # ✅ ResearchConductor — 子查询规划 → 多检索器并行 → 抓取 → SourceCurator → ContextManager → purify
├── writer.py                  # ✅ PedagogyWriter — 教育风文档撰写
├── context_manager.py         # ✅ ContextManager — 语义+词法双通道评分 + 段落去重 + 字符限制
├── image_generator.py         # 🟡 ImageGenerator — 占位符处理框架就绪，实际生成 API 待接入
├── mermaid_generator.py       # ✅ MermaidGenerator — mindmap 生成 + 关键词回退
├── source_curator.py          # ✅ SourceCurator — 域名可信度 + 词法重叠 + 本地源优先
├── loader.py                  # ✅ Skill 加载器（多路径扫描 + SKILL.md 解析）
├── api.py                     # ✅ run_skill() / list_skills() 对外 API
└── interactive_builder.py     # ⬜ InteractiveHTMLBuilder（V2 预留）
```

#### 3.3.1 ResearchConductor（✅ 已实现）

**实际实现文件**：`shared/infra/skills/researcher.py`

**与原设计的差异**（实际实现更完善）：
- 原设计是简化的 "per-query 串行" 模式，实际实现是 **"子查询规划 → 多检索器并行 → 批量抓取 → SourceCurator 质量评估 → ContextManager 压缩 → LLM purify"** 的完整管道
- 新增 `SourceCurator` 环节：域名可信度评分 + 词法重叠过滤 + 本地源优先
- 新增 `purify` 环节：用 Smart LLM 对压缩后的上下文做最终提纯
- `SkillResult.metadata` 包含丰富的追踪字段：`query_count` / `candidate_count` / `curated_source_count` / `local_hits` / `web_hits` / `purify_used` / `retriever_stats`

**实际执行流程**：
```
execute()
├── dedupe_queries() → 去重 + 限制查询数
├── generate_sub_queries() → Strategic LLM 规划子查询
├── for query in planned_queries:
│   └── for retriever in retrievers:
│       └── retriever.retrieve(query) → 并行检索
├── scrape_urls() → 并行抓取搜索结果 URL
├── SourceCurator.curate() → 质量评估 + 过滤
├── ContextManager.build_dense_context() → 语义压缩
└── LLM purify → Smart LLM 最终提纯（可选）
```

**后续优化方向**：
- 引入检索结果缓存（同一 query 短时间内不重复搜索）
- 扩展学术检索器（arXiv / Semantic Scholar）
- 教育域 site filter 更精细化

#### 3.3.2 ContextManager（✅ 已实现）

**实际实现文件**：`shared/infra/skills/context_manager.py`

**与原设计的差异**：
- 原设计基于 Embedding 向量余弦相似度过滤，实际实现采用**词法快速路径 + Embedding 过滤 + 词法兜底**三段式压缩
- 实际实现包含：段落级去重（基于文本哈希）、字符限制截断、相似度阈值过滤、超短上下文 fast path
- `ContextManager.execute()` / `run()` 接受 `query`、`focus_terms`、`documents` 等参数，可由上游用章节目标和必备要点构造压缩焦点

**后续优化方向**：
- 考虑引入 gpt-researcher 的 `WrittenContentCompressor` 去重逻辑（多章节写作时避免重复）

#### 3.3.3 ImageGenerator（🟡 框架就绪，生成 API 待接入）

**实际实现文件**：`shared/infra/skills/image_generator.py`

**当前状态**：
- `<!-- [IMAGE: ...] -->` 占位符解析和替换逻辑已实现
- 当前返回文字建议（注释形式），实际图片生成 API 尚未接入
- `enrich_document_node.py` 已集成调用 ImageGenerator

**待完成**：
- 接入通义万相 (Wanxiang) / DALL-E API 实际生成图片
- 实现 gpt-researcher 的两阶段模式：`_plan_image_concepts()` → 并行生成
- 图片存储到 ContentStore + 返回可访问 URL

#### 3.3.4 MermaidGenerator（✅ 已实现）

**实际实现文件**：`shared/infra/skills/mermaid_generator.py`

**实际实现**：
- 支持 mindmap 语法生成
- 包含关键词回退机制（LLM 生成失败时从上下文提取关键词构建简单 mindmap）
- `enrich_document_node.py` 已集成调用，自动处理 `[MERMAID:]` 占位符

### 3.4 Actions 层（原子操作）— ✅ 已实现

```
shared/infra/tools/builtin/
├── __init__.py
├── query_processing.py        # ✅ generate_sub_queries() / enrich_queries_for_education() / dedupe_queries() / build_research_focus_text()
├── web_scraping.py            # ✅ scrape_urls() 并行抓取 + URL 去重 + 类型路由
├── web_search.py              # ✅ web_search tool（@tool 注册）
├── search_kb.py               # ✅ search_knowledge tool（@tool 注册）
├── markdown_processing.py     # ✅ build_toc() / extract_headers() / add_references() / count_words()
├── content_analysis.py        # ✅ extract_key_terms() / build_term_coverage() / extract_term_excerpts()
├── latex_processing.py        # ✅ normalize_math_delimiters()（数学分隔符规范化）
└── memory_ops.py              # ✅ remember / recall tools
```

**与原设计的差异**：
- `query_processing.py` 比原设计更丰富：新增 `enrich_queries_for_education()` 教育域搜索增强 + `build_research_focus_text()` 研究焦点构建
- `web_scraping.py` 已实现完整的 URL 去重 + 类型路由（.pdf → PyMuPDF, 其他 → BS4）+ Semaphore 并发控制
- `content_analysis.py` 是按新分层思路补的通用基础件：不直接表达教学话术，而是提供术语抽取、术语片段定位、必备要点覆盖检测，供 `teaching/documents` 复用
- 原设计中的 `context_compression.py` 和 `report_generation.py` 功能已分别由 `ContextManager` Skill 和 `PedagogyWriter` Skill 承担，无需独立 Action

#### 3.4.1 query_processing.py（P0）

**移植自**：`gpt_researcher/actions/query_processing.py`

```python
async def generate_sub_queries(
    query: str,
    *,
    context: list[dict[str, Any]] | None = None,
    max_queries: int = 3,
    domain: str = "education",
) -> list[str]:
    """用 Strategic LLM 生成子查询（移植自 gpt-researcher）。

    改造点：
    1. Prompt 加入教育域约束（优先生成教材/考试相关查询）
    2. 降级容错链：Strategic → Smart → Fast
    3. 自动注入 LangSmith metadata
    """
    prompt = PROMPTS["generate_sub_queries"].format(
        query=query,
        max_queries=max_queries,
        context=json.dumps(context or [], ensure_ascii=False)[:2000],
        domain_hint=DOMAIN_HINTS.get(domain, ""),
    )
    response = await acompletion_with_fallback(
        [{"role": "user", "content": prompt}],
        task_type=TaskType.REASONING,
    )
    return json_repair.loads(response)
```

#### 3.4.2 web_scraping.py（P0）

**移植自**：`gpt_researcher/actions/web_scraping.py` + `scraper/scraper.py`

```python
async def scrape_urls(
    urls: list[str],
    *,
    max_workers: int = 10,
    user_agent: str | None = None,
) -> list[ScrapedPage]:
    """批量抓取 URL 内容（移植自 gpt-researcher）。

    改造点：
    1. URL 去重（保留顺序）
    2. 按 URL 类型路由到不同 scraper（.pdf → PyMuPDF, 其他 → BS4）
    3. 并发控制（Semaphore）
    4. 返回结构化 ScrapedPage 而非 raw dict
    """
    unique_urls = list(dict.fromkeys(urls))  # 去重保序
    semaphore = asyncio.Semaphore(max_workers)

    async def _scrape_one(url: str) -> ScrapedPage | None:
        async with semaphore:
            scraper = _get_scraper_for_url(url)
            try:
                content = await scraper.scrape(url)
                return ScrapedPage(url=url, content=content, success=True)
            except Exception as exc:
                logger.warning("scrape_failed", url=url, error=str(exc))
                return ScrapedPage(url=url, content="", success=False, error=str(exc))

    results = await asyncio.gather(*[_scrape_one(u) for u in unique_urls])
    return [r for r in results if r is not None]
```

### 3.5 Retrievers + Scraper 层 — ✅ 已实现

```
shared/infra/search/
├── __init__.py
├── api.py                     # ✅ search_knowledge + web_search
├── types.py                   # ✅ SearchResult / ScrapedPage / WebSearchResult
├── web.py                     # ✅ 多检索器聚合 + 去重
├── factory.py                 # ✅ 注册式工厂：retriever + reader 路由，多检索器 list/profile 解析
├── retrievers/
│   ├── __init__.py
│   ├── base.py                # ✅ BaseRetriever（含 LangSmith tracing）
│   ├── bing.py                # ✅ Bing Search API
│   ├── bocha.py               # 🟡 博查搜索（当前仍为 placeholder，待接入真实 API）
│   ├── duckduckgo.py          # ✅ DuckDuckGo（免费兜底）
│   ├── arxiv.py               # ✅ arXiv 学术检索
│   ├── semantic_scholar.py    # ✅ Semantic Scholar 学术检索
│   ├── tavily.py              # ✅ Tavily（高质量 research 检索）
│   └── local_rag.py           # ✅ 本地 RAG（向量 + section fallback）
└── scraper/
    ├── __init__.py
    ├── base.py                # ✅ BaseReader + BaseScraper（自动注册 + URL 匹配 + LangSmith tracing）
    ├── bs4_scraper.py         # ✅ BeautifulSoup HTML reader
    └── pdf_scraper.py         # ✅ PyMuPDF PDF reader
```

**与原设计的差异**：
- `BaseRetriever` 已升级为注册式抽象：子类自动注册到 factory，避免每次新增 retriever 都要手改 `_RETRIEVER_TYPES`
- `factory.py` 的 `get_retrievers_for_subject()` 接受 `local_sections` 参数，支持将用户上传文件的 section 直接注入 LocalRAG
- `config.py` + `factory.py` 已支持 `web_search_retrievers` / `web_search_retriever_profile`，可配置多检索器组合并保持对旧 `web_search_retriever` 的兼容
- `LocalRAGRetriever` 实现了向量检索 + section fallback 双通道，比原设计更健壮
- `BaseReader` 已落地，并保留 `BaseScraper` 兼容层；后续新增 reader 只需要实现 `supports_url()` + `read()`
- `TavilyRetriever` / `ArxivRetriever` / `SemanticScholarRetriever` 已实现；`Bocha` / `CustomRetriever` 仍待实现

**检索优先级策略（建议升级）**：
``` 
1. 本地 RAG (local_rag)        ← 用户上传的教材，最高质量，零成本
2. Tavily / 博查搜索            ← 高质量摘要检索 + 中文互联网补充
3. Bing                        ← 稳定通用搜索
4. DuckDuckGo                  ← 免费兜底，无需 API Key
5. arXiv / Semantic Scholar    ← 学术主题增强（按学科启用）
``` 

**后续扩展方向**：
- `bocha` 真实 API 接入
- `CustomRetriever`
- 多检索器 profile 的调用侧落地（Planner / DocGen 分场景启用不同 profile）
- 教育垂直站点定向检索（见 06 文档）

#### 3.5.1 从 GPT-Researcher `_easy_` 继续吸收的工程要点（新增）

这次重新对照 `_easy_` 后，确认还有 4 类高价值能力值得继续吸收，但都应按 AITeachMe 的分层方式落地，而不是直接照搬原仓库结构：

**1. 检索层不只要“更多 retriever”，还要有完整的执行护栏**

- `gpt-researcher` 真正值得学的不是“有很多检索器”，而是 **query budget + worker pool + graceful fallback** 这一整套工程约束
- AITeachMe 下一步应在 `shared/infra/search/` 补齐：
  - `SearchCache`：缓存 `(query, retriever_name, profile)` 的 search result
  - `ScrapeCache`：缓存 `(url, reader_kind)` 的正文抽取结果
  - `RateLimiter / WorkerPool`：限制外部 API 并发，避免 Tavily / 博查 / 学术源被打爆
  - `FallbackPolicy`：profile 中前置 retriever 失败时自动切到次优组合，而不是整章 research 失败

**2. `Scraper` 应进一步演进成 `ReaderAdapter` 层**

- `_easy_` 里的经验说明，单纯的 HTML scraper 不够，真正需要的是“按来源类型选择最合适的读取器”
- 对 AITeachMe 更合适的抽象是：
  - `bs4_reader`：静态 HTML
  - `pdf_reader`：PDF / 讲义
  - `browser_reader`：重 JS 站点
  - `jina_reader` / `firecrawl_reader`：正文抽取增强（后续按成本开关）
- 这样做的好处是：Retriever 仍然只负责“找来源”，Reader 只负责“把来源读成正文”，职责会比现在更清晰

**3. 需要一层稳定的数据契约，而不是在 workflow 里传散装 dict**

- `_easy_` 的文档把 `search_results` / `scraped_data` / `context` 这几个核心数据结构讲得很透，这一点非常值得借鉴
- AITeachMe 后续应在 `shared/infra/search/types.py` 与 `teaching/documents/` 之间进一步收敛出稳定契约：
  - `SearchResult`
  - `ScrapedPage`
  - `ContextBlock`
  - `ChapterEvidencePack`
- 其中 `ChapterEvidencePack` 应成为 `targeted_research -> pedagogy_craft` 的标准输出，而不是只传 `dense_context` 字符串

**4. 工具分层要继续坚持：通用能力在 infra，教学语义在 teaching**

- `_easy_` 再次验证了“核心引擎只负责编排，业务含义在外围模块表达”这个方向是对的
- 对 AITeachMe 来说：
  - 检索、抓取、缓存、限流、内容分析，这些都应留在 `shared/infra`
  - 术语速览、学习目标、误区提醒、公式拆解、例题变式，这些都应放在 `app/teaching`
- 这会让我们后面给 `interact` / `examine` / `profile` 复用基础能力时，不会再次被 digest 的教学语义绑死

#### 3.5.2 如果目标是“工具覆盖面比 GPT-Researcher 更广更强”，正确扩展方向（新增）

这里最重要的一点是：**不是继续横向堆更多同质搜索引擎，而是把工具矩阵补成完整能力图谱。**

建议把工具能力分成 8 大类，而不是只盯着 retriever：

| 工具大类 | GPT-Researcher 覆盖 | AITeachMe 当前状态 | 建议目标 |
|:---|:---|:---|:---|
| 检索器 `Retrievers` | 强 | 中强 | 超过它，但只补高价值源 |
| 读取器 `Readers` | 中 | 弱 | 明显超过它 |
| 压缩/重排 `Compression/Rerank` | 中 | 中 | 做得更教学化 |
| 事实/证据组织 `Evidence Builders` | 弱 | 弱 | 这是我们要反超的重点 |
| 教学增强 `Teaching Tools` | 弱 | 初步有 | 明显超过它 |
| 富媒体生成 `Media Tools` | 中 | 初步有 | 做得更强 |
| 交互组件生成 `Interactive Tools` | 很弱 | 预留 | 明显超过它 |
| 评估/验收 `Eval Tools` | 弱 | 弱 | 明显超过它 |

也就是说，真正的超越路线不是：

- “它 16 个 retriever，我们做 20 个 retriever”

而是：

- “它主要强在 research toolset，我们要把 `research + teaching + media + interactive + eval` 这五层都补齐”

#### 3.5.3 推荐新增工具矩阵（新增）

下面这些工具比“再补 5 个通用搜索 API”更值得优先做：

**A. 检索与读取层**

放在 `shared/infra/search/`：

- `BochaRetriever`
  - 中文互联网补强
- `CustomRetriever`
  - 企业内训 / 私有知识库 / 自建检索 API
- `PubMedRetriever`
  - 医学/生命科学方向专用
- `WikipediaRetriever` / `BaiduBaikeRetriever`
  - Planner grounding 的轻定义源
- `BrowserReader`
  - JS 站点读取
- `JinaReader`
  - 快速正文抽取
- `FirecrawlReader`
  - 高质量 reader fallback
- `SearchCache`
- `ScrapeCache`
- `RateLimiter`
- `WorkerPool`
- `FallbackPolicy`

**B. 证据与组织层**

放在 `shared/infra/tools/builtin/` 或 `shared/infra/skills/`：

- `build_evidence_pack`
  - 将 search/scrape/context 组织成 `ChapterEvidencePack`
- `written_content_dedupe`
  - 多章节内容去重
- `citation_linker`
  - 将正文段落和来源片段绑定
- `coverage_scorer`
  - 评估 required elements 的覆盖率
- `formula_extractor`
  - 从原文/网页中抽公式候选
- `example_miner`
  - 挖掘可展开的例题/变式/案例
- `misconception_detector`
  - 挖掘易错点和误区

**C. 教学增强层**

放在 `app/teaching/`：

- `solve_step_by_step`
- `generate_similar_problems`
- `explain_formula`
- `compare_concepts`
- `build_glossary_section`
- `build_learning_objectives_section`
- `build_misconception_section`
- `build_formula_walkthrough_section`
- `build_example_variations_section`
- `build_memory_hooks_section`
  - 口诀 / 记忆法 / 类比

**D. 富媒体与交互层**

放在 `shared/infra/skills/` + `app/teaching/`：

- `ImageGenerator`
  - 真图生图 API 接入
- `MermaidGenerator`
  - 已有，后续补 flowchart / sequence / quadrant
- `InteractiveHTMLBuilder`
  - 输出独立 HTML 资产
- `DesmosEmbedBuilder`
  - 函数图像
- `GeoGebraEmbedBuilder`
  - 几何/线代/曲面演示
- `ExcalidrawStyleDiagramBuilder`
  - 手绘风关系图
- `QuizCardBuilder`
  - 将知识点转交互式卡片

**E. 评估与验收层**

放在 `tests/` / `evals/` / `shared/infra/`：

- `evidence_usage_eval`
  - 来源是否真的被正文消费
- `citation_density_eval`
  - 引用密度是否足够
- `coverage_gap_eval`
  - 章节覆盖缺口是否下降
- `repetition_eval`
  - 章节间是否复读
- `media_usefulness_eval`
  - 媒体块是否真的支撑理解
- `document_bundle_validator`
  - 校验 `document.md + manifest.json + assets/`

#### 3.5.4 真正应该超越 GPT-Researcher 的 3 个点（新增）

如果只挑 3 个方向来做出明显差异化，应该是这三个：

**1. 证据包 `ChapterEvidencePack`**

它决定：

- 写作是不是按证据来
- 富媒体是不是前置规划
- LangSmith 能不能追“质量”而不是只追“耗时”

**2. 产物清单 `DocumentManifest`**

它决定：

- 前端能不能做比 PPT 更强的呈现
- 文档能不能变成“正文 + 侧栏 + 资产 + 引用 + 交互块”

**3. 教学工具层 `Teaching Tools`**

这是 GPT-Researcher 最弱、而 AITeachMe 最该强的地方。

我们真正要超过它的不是：

- “更像一个通用 research agent”

而是：

- “更像一个会研究、会组织、会讲解、会出题、会显影的 AI 教学系统”

### 3.6 LangSmith 全链路追踪 — ✅ 已实现

**实际实现方式**（与原设计略有差异）：

#### 3.6.1 Skill 层追踪

实际实现中，Skill 的 LangSmith 追踪通过 `SkillContext.trace_metadata()` + 调用方（LangGraph 节点）的 `wrap_workflow_node()` 实现，而非 BaseSkill 内部的 `run()` 包装：

```python
# 实际模式：节点调用 Skill 时传入 trace metadata
skill = ResearchConductor(context=SkillContext(
    subject=state["subject"],
    build_session_id=state["build_session_id"],
    digest_mode=state.get("digest_mode", ""),
    chapter_index=chapter_index,
))
result = await skill.execute(queries=queries, ...)
# Skill 内部的 LLM 调用自动携带 trace_metadata
```

#### 3.6.2 Retriever 层追踪

`BaseRetriever` 基类已内置 LangSmith tracing，每次 `retrieve()` 调用自动记录 retriever_name / query / result_count。

#### 3.6.3 实际 LangSmith trace 树结构

```
digest.docgen (chain)
├── load_context (chain)
├── targeted_research.ch_0 (chain)          ← fan-out Send
│   ├── ResearchConductor.execute
│   │   ├── generate_sub_queries [tier=strategic]
│   │   ├── retriever.local_rag
│   │   ├── retriever.bing
│   │   ├── scrape_urls
│   │   ├── SourceCurator.curate
│   │   ├── ContextManager.build_dense_context
│   │   └── llm.purify_context [tier=smart]
│   └── chapter_material → state
├── targeted_research.ch_1 (chain)          ← 并行
│   └── ...
├── collect_materials (chain)
├── pedagogy_craft.ch_0 (chain)             ← fan-out Send
│   ├── PedagogyWriter.execute
│   │   └── llm.write_chapter [tier=smart]
│   └── chapter_draft → state
├── pedagogy_craft.ch_1 (chain)             ← 并行
│   └── ...
├── collect_drafts (chain)
├── enrich_document (chain)
│   ├── MermaidGenerator (per placeholder)
│   ├── ImageGenerator (per placeholder)
│   ├── normalize_math_delimiters
│   └── add_references
├── inject_examine (chain)
│   └── generate exam questions
└── finalize_assemble (chain)
    └── stage_knowledge_docs
```

---

### 3.7 如何添加新 Skill（开发者指南）

在 AITeachMe 中添加新的 Skill 需 4 步：

**Step 1：选择 Skill 类型**

| 类型 | 选择条件 | 示例 |
|:---|:---|:---|
| `@skill` 装饰器 | 无状态、单步操作、被 LLM tool_call 调用 | `solve_step_by_step` |
| `BaseSkill` 子类 | 有状态、多步编排、被 LangGraph 节点直接调用 | `ResearchConductor` |

**Step 2：实现 Skill**

```python
# ── 方式 A：@skill 装饰器 ──
# 文件：shared/infra/skills/builtin/wolfram_alpha.py

from app.shared.infra.skills.base import skill

@skill(
    "wolfram_alpha_query",
    "调用 Wolfram Alpha 进行数学计算或公式验证",
    tags=["math", "external_api"],
)
async def wolfram_alpha_query(expression: str, include_plot: bool = False) -> str:
    """
    向 Wolfram Alpha Short Answers API 发送查询。
    
    Args:
        expression: 数学表达式或自然语言问题
        include_plot: 是否返回图像 URL
    """
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.wolframalpha.com/v1/result",
            params={"i": expression, "appid": get_settings().wolfram_app_id},
        )
        return resp.text
```

```python
# ── 方式 B：BaseSkill 子类 ──
# 文件：shared/infra/skills/research_conductor.py

class ResearchConductor(BaseSkill):
    """多步编排：搜索 → 抓取 → 压缩 → 返回 dense_context"""
    
    name = "research_conductor"
    description = "执行针对性研究，返回压缩后的上下文"
    
    async def execute(self, chapter_plan: dict, context: SkillContext) -> dict:
        # Step 1: 搜索
        urls = await self._search(chapter_plan["search_queries"])
        # Step 2: 抓取
        raw_content = await self._scrape(urls)
        # Step 3: 压缩
        dense_context = await self._compress(raw_content, chapter_plan["title"])
        return {"dense_context": dense_context, "sources": urls}
```

**Step 3：注册（自动）**

- `@skill` 装饰器会自动注册到 `SkillRegistry` + `ToolRegistry`
- `BaseSkill` 子类通过 `SkillLoader` 在 startup 时扫描并注册

**Step 4：加载**

在 `shared/infra/skills/loader.py` 的 `BUILTIN_SKILL_MODULES` 列表中添加新模块路径：

```python
BUILTIN_SKILL_MODULES = [
    "app.shared.infra.skills.builtin.web_search",
    "app.shared.infra.skills.builtin.wolfram_alpha",  # 新增
]
```

### 3.8 ImageGenerator 双模式说明

参考 gpt-researcher 的 `image_generator.py`（30000+ 字节），ImageGenerator 支持两种工作模式：

| 模式 | 触发时机 | 适用场景 |
|:---|:---|:---|
| **预生成模式（Pre-generation）** | 在 `pedagogy_craft` 之前 | 概念性插图（如"偏导数的几何意义"） |
| **后处理模式（Post-processing）** | 在 `enrich_document` 中 | 根据已写内容智能识别需要配图的段落 |

AITeachMe 采用**后处理模式**（与 gpt-researcher 的默认方式一致）：

```
enrich_document 节点内部流程：
1. _extract_placeholders()  → 从 Markdown 中提取 [IMAGE:...] 占位符
2. _plan_image_concepts()   → Fast LLM 分析上下文，为每个占位符生成描述
3. _generate_images()       → 并行调用通义万象生成图片（asyncio.gather）
4. _embed_images()          → 替换占位符为 Markdown 图片链接
```

> [!NOTE]
> gpt-researcher 的 ResearchConductor 有 990 行，包含 MCP 三策略等复杂逻辑。我们的实现是简化版本，仅保留核心的 "搜索 → 抓取 → 压缩" 三步流程。完整实现参考 `gpt_researcher/skills/researcher.py`。

---
