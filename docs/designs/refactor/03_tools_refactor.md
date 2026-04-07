## 三、工具体系重构 — Skills + Actions + Retrievers + Scraper

### 3.1 现状分析

**当前 AITeachMe 的工具体系**：
- `shared/infra/skills/base.py` — `@skill` 装饰器 + `SkillRegistry`，自动同步到 `ToolRegistry`。框架完整但**无业务 Skill 实现**。
- `shared/infra/tools/registry.py` — `ToolRegistry` 管理注册/查询/执行，支持 OpenAI function calling 格式。框架完整但 **builtin 工具极少**。
- `shared/infra/search/api.py` — `web_search()` + `search_knowledge()` 两个入口，向量检索 + rerank 管道已通。但 **web 检索器只有一种**，无工厂模式。

**gpt-researcher 的工具体系**：
- `skills/` — 6 个重量级 Skill 类（ResearchConductor / ReportGenerator / ContextManager / BrowserManager / SourceCurator / ImageGenerator），每个类持有 `researcher` 引用，内部编排多个 Action。
- `actions/` — 7 个原子操作模块，纯函数式，可独立测试。
- `retrievers/` — 14 种检索器 + 工厂函数 `get_retriever(name)`。
- `scraper/` — 8 种抓取器 + 统一调度器 `Scraper` 类（URL 去重 + 类型路由 + 并行抓取）。

**核心差距**：我们有框架但缺业务实现；gpt-researcher 有丰富实现但缺框架规范。融合的关键是**把 gpt-researcher 的业务逻辑灌入我们的框架骨架**。

### 3.2 Skills 层重构 — 引入 BaseSkill 抽象类

当前 `@skill` 装饰器适合轻量级函数式 Skill（如 `find_resources`）。但 gpt-researcher 的 Skill 是**有状态的类**（持有 researcher 引用、内部缓存、多步编排）。我们需要两层并存：

```python
# shared/infra/skills/base.py 新增

class BaseSkill(ABC):
    """重量级 Skill 基类（移植自 gpt-researcher 的 Skill 模式）。

    与 @skill 装饰器的区别：
    - @skill: 无状态函数，适合单步操作（如搜索、翻译）
    - BaseSkill: 有状态类，适合多步编排（如研究、写作、图片生成）

    每个 BaseSkill 子类必须实现 execute() 方法。
    """

    def __init__(self, context: SkillContext) -> None:
        self.context = context
        self.logger = structlog.get_logger().bind(skill=self.__class__.__name__)

    @abstractmethod
    async def execute(self, **kwargs: Any) -> SkillResult:
        """执行 Skill 的核心逻辑。"""
        ...

    @property
    def name(self) -> str:
        return self.__class__.__name__


@dataclass(slots=True)
class SkillContext:
    """Skill 执行上下文，替代 gpt-researcher 中 Skill 持有 researcher 引用的模式。"""

    subject: str
    build_session_id: str
    workflow_context: WorkflowContext | None = None
    # LLM 调用入口（避免 Skill 直接依赖 llm.py 的全局函数）
    llm_caller: Callable | None = None  # 默认用 acompletion_with_fallback


@dataclass(slots=True)
class SkillResult:
    """Skill 执行结果。"""

    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    images: list[dict[str, Any]] = field(default_factory=list)
    cost_tokens: int = 0
```

### 3.3 具体 Skill 实现规划

```
shared/infra/skills/
├── base.py                    # BaseSkill + SkillContext + SkillResult + @skill 装饰器（现有）
├── researcher.py              # 🔬 ResearchConductor — 搜索 + 抓取 + 上下文汇聚
├── writer.py                  # ✍️ PedagogyWriter — 教育风文档撰写
├── context_manager.py         # 📚 ContextManager — 上下文检索 + 压缩去重
├── image_generator.py         # 🎨 ImageGenerator — 文生图（两阶段）
├── mermaid_generator.py       # 🗺️ MermaidGenerator — 知识点思维导图
├── interactive_builder.py     # 🖥️ InteractiveHTMLBuilder — 可交互公式/动画（V2）
└── source_curator.py          # 🔍 SourceCurator — 来源质量排序
```

#### 3.3.1 ResearchConductor（核心，P0）

**移植来源**：`gpt_researcher/skills/researcher.py`

**改造要点**：
- gpt-researcher 的 `ResearchConductor` 持有 `self.researcher`（GPTResearcher 实例），我们改为持有 `SkillContext`
- 原来的 `plan_research()` → `conduct_research()` 两步，我们拆成 LangGraph 节点调用
- 原来直接调 `create_chat_completion()`，我们改为调 `acompletion_with_fallback(task_type=TaskType.REASONING)`
- 原来的 MCP 策略（disabled/fast/deep）保留，但通过 `SkillContext` 传入配置

```python
# shared/infra/skills/researcher.py

class ResearchConductor(BaseSkill):
    """搜索 + 抓取 + 上下文汇聚。

    移植自 gpt-researcher 的 ResearchConductor，核心改造：
    1. 检索优先级：本地 RAG → Bing/博查 → DuckDuckGo（教育域专属）
    2. LLM 调用走我们的 acompletion_with_fallback（自带 LangSmith 追踪）
    3. 上下文压缩走我们的 ContextManager（用我们的 embedding）
    """

    async def execute(
        self,
        *,
        queries: list[str],
        local_rag_subject: str | None = None,
        max_results_per_query: int = 5,
    ) -> SkillResult:
        """对每个 query 执行：本地RAG → 外网搜索 → 抓取 → 压缩。"""
        all_context = []
        all_sources = []

        for query in queries:
            # Step 1: 本地 RAG（如果有 subject）
            local_results = []
            if local_rag_subject:
                local_results = await search_knowledge(
                    query, local_rag_subject, top_k=max_results_per_query,
                )

            # Step 2: 如果本地不足，降级外网搜索
            web_results = []
            if len(local_results) < 3:
                web_results = await self._web_search_and_scrape(
                    query, max_results=max_results_per_query,
                )

            # Step 3: 合并 + 压缩
            combined = self._merge_results(local_results, web_results)
            compressed = await self._compress_context(query, combined)
            all_context.append(compressed)
            all_sources.extend(self._extract_sources(local_results, web_results))

        return SkillResult(
            content="\n\n---\n\n".join(all_context),
            sources=list(set(all_sources)),
        )
```

#### 3.3.2 ContextManager（P1）

**移植来源**：`gpt_researcher/skills/context_manager.py` + `context/compression.py`

**改造要点**：
- 原来用 LangChain 的 `ContextualCompressionRetriever` + `EmbeddingsFilter`，我们改为用自己的 `aembed_texts()` + 余弦相似度过滤
- 保留 gpt-researcher 的**小文档快速路径**优化（内容小于阈值时跳过 embedding）
- 保留 `WrittenContentCompressor` 的去重逻辑（用于多章节写作时避免重复）

```python
# shared/infra/skills/context_manager.py

class ContextManager(BaseSkill):
    """上下文检索 + 压缩去重。"""

    async def compress(
        self,
        query: str,
        documents: list[str],
        *,
        similarity_threshold: float = 0.42,
        max_results: int = 10,
    ) -> str:
        """压缩文档列表，返回与 query 最相关的内容。

        快速路径：如果总内容 < 2000 字符，跳过 embedding 直接返回。
        """
        total_chars = sum(len(d) for d in documents)
        if total_chars < 2000:
            return "\n\n".join(documents[:max_results])

        # 用我们的 embedding 计算相似度
        all_texts = [query] + documents
        embeddings = await aembed_texts(all_texts)
        query_emb = embeddings[0]
        doc_embs = embeddings[1:]

        # 余弦相似度过滤
        scored = []
        for doc, emb in zip(documents, doc_embs):
            sim = cosine_similarity(query_emb, emb)
            if sim >= similarity_threshold:
                scored.append((sim, doc))

        scored.sort(key=lambda x: -x[0])
        return "\n\n".join(doc for _, doc in scored[:max_results])
```

#### 3.3.3 ImageGenerator（P2）

**移植来源**：`gpt_researcher/skills/image_generator.py`

**两阶段模式完整保留**：
1. `_plan_image_concepts()` — 用 Fast LLM 分析文档，识别 2-3 个可视化机会
2. `_generate_images()` — 并行调用图片生成 API
3. `embed_images_in_report()` — 扫描占位符，替换为实际图片

**底层替换**：gpt-researcher 用 Gemini，我们用通义万相 (Wanxiang) 或 Qwen-VL。

#### 3.3.4 MermaidGenerator（自研，P2）

```python
class MermaidGenerator(BaseSkill):
    """知识点思维导图生成。"""

    async def execute(self, *, topic: str, context: str) -> SkillResult:
        """用 Fast LLM 生成 Mermaid 语法的思维导图。"""
        prompt = f"""根据以下内容，生成一个 Mermaid mindmap 语法的思维导图。
要求：
1. 根节点是主题名
2. 最多 3 层深度
3. 每层最多 5 个节点
4. 用中文

主题：{topic}
内容：{context[:3000]}
"""
        mermaid_code = await acompletion_with_fallback(
            [{"role": "user", "content": prompt}],
            task_type=TaskType.DOCGEN_LIGHT,
        )
        return SkillResult(content=f"```mermaid\n{mermaid_code}\n```")
```

### 3.4 Actions 层重构（原子操作）

Actions 是更细粒度的、无状态的、可复用的底层函数。融入 `shared/infra/tools/builtin/`：

```
shared/infra/tools/builtin/
├── __init__.py
├── query_processing.py        # 📋 generate_sub_queries() / plan_research_outline()
├── web_scraping.py            # 🌐 scrape_urls() / batch_scrape()
├── markdown_processing.py     # 📝 extract_headers() / add_references() / embed_media()
├── latex_processing.py        # 📐 validate_latex() / normalize_math_delimiters()
├── context_compression.py     # 🗜️ compress_by_similarity() / fast_path_check()
└── report_generation.py       # 📄 generate_section() / write_conclusion()
```

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

### 3.5 Retrievers 层重构（搜索引擎工厂）

在 `shared/infra/search/` 中引入工厂模式：

```
shared/infra/search/
├── __init__.py
├── api.py                     # 现有（search_knowledge + web_search）
├── types.py                   # 现有
├── web.py                     # 现有
├── factory.py                 # 🏭 新增：get_retriever(name) 工厂
├── retrievers/                # 🆕 新增目录
│   ├── __init__.py
│   ├── base.py                # BaseRetriever 抽象基类
│   ├── bing.py                # Bing Search（中文搜索首选）
│   ├── bocha.py               # 博查 Search（国内 AI 搜索）
│   ├── duckduckgo.py          # DuckDuckGo（免费兜底）
│   ├── local_rag.py           # 🎯 本地 RAG 向量库检索（封装 search_knowledge）
│   └── tavily.py              # Tavily（英文搜索备用）
└── scraper/                   # 🆕 新增目录
    ├── __init__.py
    ├── base.py                # BaseScraper 抽象基类
    ├── bs4_scraper.py         # BeautifulSoup 抓取器
    └── pdf_scraper.py         # PyMuPDF PDF 解析
```

#### 3.5.1 BaseRetriever 接口

```python
# shared/infra/search/retrievers/base.py

class BaseRetriever(ABC):
    """检索器抽象基类（移植自 gpt-researcher 的 Retriever 接口）。"""

    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        max_results: int = 5,
    ) -> list[SearchResult]:
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...


@dataclass(slots=True)
class SearchResult:
    """统一的搜索结果格式。"""
    url: str
    title: str
    snippet: str
    score: float = 0.0
    source: str = ""  # retriever name
```

#### 3.5.2 工厂函数

```python
# shared/infra/search/factory.py

def get_retriever(name: str) -> BaseRetriever:
    """检索器工厂（移植自 gpt-researcher 的 get_retriever）。"""
    match name.lower().strip():
        case "bing":
            from .retrievers.bing import BingRetriever
            return BingRetriever()
        case "bocha":
            from .retrievers.bocha import BochaRetriever
            return BochaRetriever()
        case "duckduckgo" | "ddg":
            from .retrievers.duckduckgo import DuckDuckGoRetriever
            return DuckDuckGoRetriever()
        case "local_rag" | "rag":
            from .retrievers.local_rag import LocalRAGRetriever
            return LocalRAGRetriever()
        case "tavily":
            from .retrievers.tavily import TavilyRetriever
            return TavilyRetriever()
        case _:
            raise ValueError(f"Unknown retriever: {name}")


def get_retrievers_for_subject(
    subject: str | None = None,
) -> list[BaseRetriever]:
    """教育域检索优先级策略。"""
    retrievers = []
    if subject:
        retrievers.append(get_retriever("local_rag"))
    settings = get_settings()
    web_retriever = settings.web_search_retriever or "bing"
    retrievers.append(get_retriever(web_retriever))
    retrievers.append(get_retriever("duckduckgo"))  # 免费兜底
    return retrievers
```

#### 3.5.3 检索优先级策略（教育域专属）

```
1. 本地 RAG (local_rag)        ← 用户上传的教材，最高质量，零成本
2. Bing / 博查搜索             ← 中文互联网（知乎、CSDN、考研论坛）
3. DuckDuckGo                  ← 免费兜底，无需 API Key
```

**配置方式**（`.env`）：
```env
# 检索器配置
WEB_SEARCH_RETRIEVER=bing          # 主力 web 检索器
BING_API_KEY=xxx                   # Bing Search API Key
BOCHA_API_KEY=xxx                  # 博查 API Key（可选）
LOCAL_RAG_PRIORITY=true            # 是否优先查本地 RAG
LOCAL_RAG_MIN_RESULTS=3            # 本地结果少于此数时降级查外网
```

### 3.6 LangSmith 全链路追踪适配

**关键原则**：每个 Skill / Action / Retriever 的调用都必须在 LangSmith 中可追踪。

#### 3.6.1 Skill 层追踪

```python
# BaseSkill.execute() 自动包裹 LangSmith trace

class BaseSkill(ABC):
    async def run(self, **kwargs: Any) -> SkillResult:
        """外部调用入口，自动包裹 LangSmith trace。"""
        with langsmith_trace(
            name=f"skill.{self.name}",
            run_type="chain",
            inputs=kwargs,
            metadata=build_langsmith_metadata(
                workflow=self.context.workflow_context.workflow_name if self.context.workflow_context else "",
                node=f"skill.{self.name}",
            ),
        ) as run:
            result = await self.execute(**kwargs)
            if run:
                run.end(outputs={"content_len": len(result.content), "source_count": len(result.sources)})
            return result
```

#### 3.6.2 Retriever 层追踪

```python
# BaseRetriever 自动追踪

class BaseRetriever(ABC):
    async def traced_search(self, query: str, **kwargs) -> list[SearchResult]:
        """带 LangSmith 追踪的搜索。"""
        with langsmith_trace(
            name=f"retriever.{self.name}",
            run_type="retriever",
            inputs={"query": query, **kwargs},
        ) as run:
            results = await self.search(query, **kwargs)
            if run:
                run.end(outputs={"result_count": len(results)})
            return results
```

#### 3.6.3 在 LangSmith 中的可视化效果

重构后，一次完整的 DocGen 流程在 LangSmith 中的 trace 树：

```
digest.docgen (chain)
├── edu_planner (chain)
│   └── llm.acompletion [task_type=reasoning] (llm)
├── targeted_research.chapter_1 (chain)
│   ├── retriever.local_rag (retriever)
│   ├── retriever.bing (retriever)
│   ├── skill.ResearchConductor (chain)
│   │   ├── scraper.bs4 (tool)
│   │   └── skill.ContextManager.compress (chain)
│   │       └── llm.acompletion [task_type=docgen_light] (llm)
│   └── llm.acompletion [task_type=extract] (llm)
├── targeted_research.chapter_2 (chain)  ← 并行
│   └── ...
├── pedagogy_craft.chapter_1 (chain)
│   └── llm.acompletion [task_type=docgen] (llm)
├── pedagogy_craft.chapter_2 (chain)  ← 并行
│   └── ...
├── enrich_document (chain)
│   ├── skill.ImageGenerator (chain)
│   │   ├── llm.acompletion [task_type=docgen_light] (llm)  ← plan concepts
│   │   └── tool.wanxiang_generate (tool)       ← generate image
│   ├── skill.MermaidGenerator (chain)
│   │   └── llm.acompletion [task_type=docgen_light] (llm)
│   └── tool.validate_latex (tool)
├── inject_examine (chain)
│   └── llm.acompletion [task_type=docgen] (llm)
└── finalize_assemble (chain)
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
