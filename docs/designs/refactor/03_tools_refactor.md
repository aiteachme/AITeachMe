## 三、工具体系重构 — Skills + Actions + Retrievers + Scraper

> **最后更新**：2026-04-08 — 反映 Phase 0/1 实际落地后的状态，所有核心 Skill/Action/Retriever/Scraper 已实现

### 3.1 现状分析（已更新）

**当前 AITeachMe 的工具体系**（Phase 0/1 完成后）：
- `shared/infra/skills/base.py` — `BaseSkill` 抽象基类 + `SkillContext` + `SkillResult` + `@skill` 装饰器 + `SkillRegistry`，**双模式共存**。
- `shared/infra/skills/` — 已实现 6 个业务 Skill：ResearchConductor / PedagogyWriter / ContextManager / SourceCurator / ImageGenerator / MermaidGenerator。
- `shared/infra/tools/builtin/` — 已实现 7 个原子操作：query_processing / web_scraping / web_search / search_kb / markdown_processing / latex_processing / memory_ops。
- `shared/infra/search/retrievers/` — 工厂模式已落地，含 BaseRetriever + Bing / DuckDuckGo / Bocha / LocalRAG 四种实现。
- `shared/infra/search/scraper/` — BaseScraper + BS4 + PyMuPDF 两种实现。

**gpt-researcher 的工具体系**：
- `skills/` — 6 个重量级 Skill 类（ResearchConductor / ReportGenerator / ContextManager / BrowserManager / SourceCurator / ImageGenerator），每个类持有 `researcher` 引用，内部编排多个 Action。
- `actions/` — 7 个原子操作模块，纯函数式，可独立测试。
- `retrievers/` — 14 种检索器 + 工厂函数 `get_retriever(name)`。
- `scraper/` — 8 种抓取器 + 统一调度器 `Scraper` 类（URL 去重 + 类型路由 + 并行抓取）。

**当前状态**：核心融合已完成。gpt-researcher 的业务逻辑已灌入我们的框架骨架。后续重点是**质量调优和功能扩展**（教育 Teaching Skills、学术检索器、实际图片生成 API 接入）。

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
- 扩展学术检索器（Tavily / arXiv）
- 教育域 site filter 更精细化

#### 3.3.2 ContextManager（✅ 已实现）

**实际实现文件**：`shared/infra/skills/context_manager.py`

**与原设计的差异**：
- 原设计基于 Embedding 向量余弦相似度过滤，实际实现采用**语义+词法双通道评分**（无需额外 embedding 调用，更快）
- 实际实现包含：段落级去重（基于文本哈希）、字符限制截断、相似度阈值过滤
- `build_dense_context()` 方法接受 `chapter_title` / `objective` / `required_elements` / `digest_mode` 参数，上下文压缩更精准

**后续优化方向**：
- 可引入 Embedding 向量过滤作为可选的高精度模式（当前词法模式已够用）
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
├── latex_processing.py        # ✅ normalize_math_delimiters()（数学分隔符规范化）
└── memory_ops.py              # ✅ remember / recall tools
```

**与原设计的差异**：
- `query_processing.py` 比原设计更丰富：新增 `enrich_queries_for_education()` 教育域搜索增强 + `build_research_focus_text()` 研究焦点构建
- `web_scraping.py` 已实现完整的 URL 去重 + 类型路由（.pdf → PyMuPDF, 其他 → BS4）+ Semaphore 并发控制
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
├── factory.py                 # ✅ get_retrievers_for_subject() 工厂
├── retrievers/
│   ├── __init__.py
│   ├── base.py                # ✅ BaseRetriever（含 LangSmith tracing）
│   ├── bing.py                # ✅ Bing Search API
│   ├── bocha.py               # ✅ 博查搜索
│   ├── duckduckgo.py          # ✅ DuckDuckGo（免费兜底）
│   └── local_rag.py           # ✅ 本地 RAG（向量 + section fallback）
└── scraper/
    ├── __init__.py
    ├── base.py                # ✅ BaseScraper（含 LangSmith tracing）
    ├── bs4_scraper.py         # ✅ BeautifulSoup HTML 抓取
    └── pdf_scraper.py         # ✅ PyMuPDF PDF 提取
```

**与原设计的差异**：
- `BaseRetriever` 实际接口使用 `retrieve(query, top_k)` 而非 `search(query, max_results)`，与 LangChain retriever 命名习惯一致
- `factory.py` 的 `get_retrievers_for_subject()` 接受 `local_sections` 参数，支持将用户上传文件的 section 直接注入 LocalRAG
- `LocalRAGRetriever` 实现了向量检索 + section fallback 双通道，比原设计更健壮
- Tavily 检索器尚未实现（当前 4 种检索器已满足需求）

**检索优先级策略（不变）**：
```
1. 本地 RAG (local_rag)        ← 用户上传的教材，最高质量，零成本
2. Bing / 博查搜索             ← 中文互联网（知乎、CSDN、考研论坛）
3. DuckDuckGo                  ← 免费兜底，无需 API Key
```

**后续扩展方向**：
- Tavily 检索器（英文学术搜索）
- arXiv 检索器（论文搜索）
- 教育垂直站点定向检索（见 06 文档）

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
