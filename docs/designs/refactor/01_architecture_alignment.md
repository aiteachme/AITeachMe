## 一、两个项目的架构对齐 — "我有什么 / 他有什么 / 我缺什么"

### 1.1 能力矩阵对照

| 能力维度 | gpt-researcher 实现 | AITeachMe 现状 | 差距评估 | 重构优先级 |
|:---|:---|:---|:---|:---|
| **LLM 调用** | `GenericLLMProvider` → 20+ provider, 三级模型 (fast/smart/strategic) | `shared/infra/llm.py` → LiteLLM + Instructor, `model_router.py` 按 TaskType 路由 | 🟡 已有 TaskType 路由，需扩展为三级分层 | P0 |
| **搜索引擎** | `retrievers/` → 14 种 (Tavily / Bing / DuckDuckGo / arXiv / MCP ...) | `shared/infra/search/` → `web_search()` + `search_knowledge()` 向量检索 | 🔴 Web 检索器种类极少，无工厂模式 | P0 |
| **网页抓取** | `scraper/` → 8 种 (BS4 / PyMuPDF / Selenium / Firecrawl ...) + URL 去重 + 并行 | 无独立 Scraper 模块（Ingest 有 markitdown 解析但不做 URL 抓取） | 🔴 需新建 | P0 |
| **上下文压缩** | `context/compression.py` → `ContextCompressor`(Embedding 相似度过滤) + `WrittenContentCompressor` + 小文档快速路径 | `shared/infra/embedding.py` 有 embedding，`search/api.py` 有 rerank，但无独立 Compressor 管道 | 🟡 可基于现有 embedding + reranker 快速接入 | P1 |
| **Skills（技能层）** | `skills/` → 6 个 Skill 类 (Researcher / Writer / ContextManager / Browser / Curator / ImageGenerator) | `shared/infra/skills/base.py` → `@skill` 装饰器 + `SkillRegistry`，但只有注册框架无业务实现 | 🟡 框架已有，需填充业务 Skill 类 | P1 |
| **Actions（原子操作）** | `actions/` → 7 个模块 (query_processing / retriever / web_scraping / report_generation / markdown_processing / agent_creator / utils) | `shared/infra/tools/` → `ToolRegistry` + `ToolDefinition`，但 builtin 工具极少 | 🟡 需补充教育域原子操作 | P1 |
| **文生图** | `skills/image_generator.py` → 两阶段 (LLM 规划 → 并行生成) + `embed_images_in_report()` 自动嵌入 | 无 | 🔴 需新建 | P2 |
| **Mermaid / 交互 HTML** | 无（纯 Markdown 报告） | 无 | 🔴 需自研 | P2 |
| **流式输出** | `stream_output()` → WebSocket 实时推送 (logs/report/images/cost/path) | WebSocket 有（Interact 引擎），但 DocGen 不使用 | 🟡 需打通到 DocGen | P2 |
| **三级 LLM 策略** | `FAST_LLM` / `SMART_LLM` / `STRATEGIC_LLM` + 降级容错链 | `model_router.py` 有 11 个 TaskType 但无 fast/smart/strategic 分层 | 🟡 需在现有 TaskType 上叠加三级分层 | P0 |
| **MCP 协议** | `mcp/` → MCPRetriever + MCPToolSelector + MCPResearchSkill + 三种策略 (disabled/fast/deep) | `shared/infra/mcp.py` → 有骨架 | 🟡 可扩展 | P3 |
| **并发控制** | `WorkerPool` + `Semaphore` + `asyncio.gather` | LangGraph `Send()` 并发 + `DocGenExecutionStrategy.chapter_semaphore` + 全局 `_LLM_SEMAPHORE` | ✅ 已有，且更精细 | — |
| **可观测性** | 简单日志 + JSON handler + 可选 LangSmith | `shared/infra/tracing.py` → LangSmith 集成 + `LLMCallTracker` + `wrap_digest_node()` + `DigestTimingReport` | ✅ 已有，且远超 gpt-researcher | — |
| **成本追踪** | `utils/costs.py` → `estimate_embedding_cost()` + `add_costs()` 回调 | `LLMCallTracker` 记录 token 用量，但无金额换算 | 🟡 可选扩展 | P3 |

### 1.2 我们不需要照搬的部分

- ❌ `multi_agents/` 编辑部模式（总编辑-记者-审稿人）→ 我们有自己的五大引擎编排
- ❌ `backend/` FastAPI 服务 → 我们有自己的 FastAPI 后端
- ❌ `frontend/` → 我们有 React + Vite + Orval 前端
- ❌ `Config` 类 → 我们有 `shared/infra/config.py` (Pydantic Settings)
- ❌ `GenericLLMProvider` → 我们有 LiteLLM 统一抽象层（更轻量）
- ❌ `memory/embeddings.py` → 我们有 `shared/infra/embedding.py`（已适配 DashScope）
- ❌ `vector_store/` → 我们有 sqlite-vec 向量检索 + reranker

### 1.3 我们要"移植"的核心

抽取灵魂，不照搬皮囊：

| 序号 | 移植目标 | 来源 | 融入位置 | 改造要点 |
|:---|:---|:---|:---|:---|
| 1 | **三级 LLM 策略** | `config/variables/default.py` 的 FAST/SMART/STRATEGIC 分层 + `query_processing.py` 的降级容错链 | `model_router.py` 扩展 | 在现有 TaskType 上叠加 LLMTier 维度，不破坏已有路由 |
| 2 | **Skill 组合模式** | `skills/` 的 6 个 Skill 类各司其职 | `shared/infra/skills/` 新增业务 Skill 类 | 保留 `@skill` 装饰器用于轻量 Skill，新增 `BaseSkill` 类用于重量级 Skill |
| 3 | **Plan-Execute-Write 范式** | `ResearchConductor.plan_research()` → `conduct_research()` → `ReportGenerator.write_report()` | `workflows/digest/docgen/` 重建 graph | 用 LangGraph 节点实现，保留 `wrap_digest_node()` 可观测性 |
| 4 | **上下文压缩管道** | `context/compression.py` 的 `ContextCompressor` | `shared/infra/context/` 新建 | 用我们的 embedding 替换 LangChain 的 `OPENAI_EMBEDDING_MODEL` |
| 5 | **检索器工厂** | `actions/retriever.py` 的 `get_retriever()` / `get_retrievers()` | `shared/infra/search/` 扩展 | 加入本地 RAG 优先策略 |
| 6 | **Scraper 调度器** | `scraper/scraper.py` 的 URL 去重 + 类型路由 + 并行抓取 | `shared/infra/search/scraper/` 新建 | 精简到 BS4 + PyMuPDF 两种，按需扩展 |
| 7 | **文生图两阶段** | `skills/image_generator.py` 的 `_plan_image_concepts()` → 并行生成 → `embed_images_in_report()` | `shared/infra/skills/image_generator.py` 新建 | 底层替换为通义万相 / Qwen-VL |

---
