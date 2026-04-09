## 一、两个项目的架构对齐 — "我有什么 / 他有什么 / 我缺什么"

> **最后更新**：2026-04-09 — 反映检索层第一阶段重构后的实际状态

### 1.1 能力矩阵对照

| 能力维度 | gpt-researcher 实现 | AITeachMe 现状 | 状态 | 后续方向 |
|:---|:---|:---|:---|:---|
| **LLM 调用** | `GenericLLMProvider` → 20+ provider, 三级模型 (fast/smart/strategic) | `llm_support/fallback.py` → `acompletion_with_fallback()` 已实现 tier 路由 (strategic→smart→fast)，基于 `TaskType` 降级链 | ✅ 已完成 | 调优各 tier 默认模型配置，收集 LangSmith 数据验证降级频率 |
| **搜索引擎** | `retrievers/` → 14 种 (Tavily / Bing / DuckDuckGo / arXiv / MCP ...) | `search/retrievers/` → 工厂模式已落地，含 `BaseRetriever` + Bing / DuckDuckGo / LocalRAG / Tavily，`Bocha` 当前仍是 placeholder；`factory.py` 已支持多检索器列表 / profile 解析与按 subject 自动组装 | 🟡 部分完成 | 下一步优先补 `Bocha` 真实现与 arXiv / Semantic Scholar 等学术检索器 |
| **网页抓取** | `scraper/` → 8 种 (BS4 / PyMuPDF / Selenium / Firecrawl ...) + URL 去重 + 并行 | `search/scraper/` → `BaseScraper` + BS4 + PyMuPDF 两种实现，`web_scraping.py` 支持并行抓取 + URL 去重 | ✅ 已完成 | 可按需扩展 Selenium / Firecrawl |
| **上下文压缩** | `context/compression.py` → `ContextCompressor` + 小文档快速路径 | `skills/context_manager.py` → `ContextManager` 已实现语义+词法相似度评分、段落去重、字符限制压缩 | ✅ 已完成 | 可引入 Embedding 向量过滤提升精度 |
| **Skills（技能层）** | `skills/` → 6 个 Skill 类 | `skills/` → `BaseSkill` + `SkillContext` + `SkillResult` 已落地，已实现 ResearchConductor / PedagogyWriter / ContextManager / SourceCurator / ImageGenerator / MermaidGenerator 共 6 个业务 Skill | ✅ 已完成 | 扩展教育专属 Teaching Skills（solve_step_by_step 等） |
| **Actions（原子操作）** | `actions/` → 7 个模块 | `tools/builtin/` → 已实现 query_processing / web_scraping / web_search / search_kb / markdown_processing / latex_processing / memory_ops 共 7 个模块 | ✅ 已完成 | 补充教育域原子操作（公式验证、题目生成等） |
| **文生图** | `skills/image_generator.py` → 两阶段 + 自动嵌入 | `skills/image_generator.py` → 已实现占位符处理框架（`<!-- [IMAGE: ...] -->`），当前返回文字建议 | 🟡 框架就绪，生成能力待接入 | 接入通义万相 / DALL-E 实际生成 |
| **Mermaid / 交互 HTML** | 无（纯 Markdown 报告） | `skills/mermaid_generator.py` → 已实现 mindmap 生成 + 关键词回退；`enrich_document_node` 自动处理 `[MERMAID:]` 占位符 | ✅ Mermaid 已完成 | 交互 HTML（V2 预留） |
| **流式输出** | `stream_output()` → WebSocket 实时推送 | DocGen 各节点已通过 `events.py` 发布进度事件（plan_ready / research_progress / draft_progress 等），前端可订阅 | 🟡 事件已有，WebSocket 推送待打通 | 打通 DocGen 事件到前端 WebSocket |
| **三级 LLM 策略** | `FAST_LLM` / `SMART_LLM` / `STRATEGIC_LLM` + 降级容错链 | `llm_support/fallback.py` → `acompletion_with_fallback()` 已实现，通过 `tier` 参数选择，自动降级 | ✅ 已完成 | 收集降级频率数据，调优模型配置 |
| **MCP 协议** | `mcp/` → MCPRetriever + MCPToolSelector + 三种策略 | `shared/infra/mcp.py` → 有骨架 | 🟡 可扩展 | P3 |
| **并发控制** | `WorkerPool` + `Semaphore` + `asyncio.gather` | LangGraph `Send()` fan-out 并发 + `docgen_max_parallel_chapters` 控制 + 全局 `_LLM_SEMAPHORE` | ✅ 已有，且更精细 | — |
| **可观测性** | 简单日志 + JSON handler + 可选 LangSmith | `tracing.py` → LangSmith 全链路集成 + `LLMCallTracker` + `wrap_workflow_node()` + `DigestTimingReport` + 每个 Skill/Retriever 自带 trace metadata | ✅ 已有，且远超 gpt-researcher | 建立自定义 Dashboard（见 10 文档） |
| **成本追踪** | `utils/costs.py` → `estimate_embedding_cost()` + `add_costs()` 回调 | `LLMCallTracker` 记录 token 用量，`SkillResult.cost_tokens` 追踪 Skill 级消耗 | 🟡 可选扩展 | P3：金额换算 |

### 1.2 我们不需要照搬的部分（不变）

- ❌ `multi_agents/` 编辑部模式（总编辑-记者-审稿人）→ 我们有自己的五大引擎编排
- ❌ `backend/` FastAPI 服务 → 我们有自己的 FastAPI 后端
- ❌ `frontend/` → 我们有 React + Vite + Orval 前端
- ❌ `Config` 类 → 我们有 `shared/infra/config.py` (Pydantic Settings)
- ❌ `GenericLLMProvider` → 我们有 LiteLLM 统一抽象层（更轻量）
- ❌ `memory/embeddings.py` → 我们有 `shared/infra/embedding.py`（已适配 DashScope）
- ❌ `vector_store/` → 我们有 sqlite-vec 向量检索 + reranker

### 1.3 移植核心 — 完成状态追踪

| 序号 | 移植目标 | 融入位置 | 状态 | 备注 |
|:---|:---|:---|:---|:---|
| 1 | **三级 LLM 策略** | `llm_support/fallback.py` | ✅ 已完成 | `acompletion_with_fallback()` 支持 tier 参数 + TaskType 降级链 |
| 2 | **Skill 组合模式** | `shared/infra/skills/` | ✅ 已完成 | `BaseSkill` + `@skill` 双模式共存，6 个业务 Skill 已实现 |
| 3 | **Plan-Execute-Write 范式** | `workflows/digest/docgen/` | ✅ 已完成 | 8 节点 LangGraph 拓扑：load_context → targeted_research → collect_materials → pedagogy_craft → collect_drafts → enrich_document → inject_examine → finalize_assemble |
| 4 | **上下文压缩管道** | `skills/context_manager.py` | ✅ 已完成 | 语义+词法双通道评分，段落去重，字符限制 |
| 5 | **检索器工厂** | `search/retrievers/` + `search/factory.py` | ✅ 已完成 | `BaseRetriever` + 多检索器列表 / profile 解析 + 5 种实现（含 Tavily，Bocha 仍待补真实 API） |
| 6 | **Scraper 调度器** | `search/scraper/` + `tools/builtin/web_scraping.py` | ✅ 已完成 | BS4 + PyMuPDF + 并行抓取 + URL 去重 |
| 7 | **文生图两阶段** | `skills/image_generator.py` | 🟡 框架就绪 | 占位符处理已实现，实际图片生成 API 待接入 |

### 1.4 下一阶段重点（Phase 3+）

核心移植已完成，后续聚焦于**质量提升和功能扩展**：

| 优先级 | 方向 | 具体内容 |
|:---|:---|:---|
| P0 | **文档质量调优** | 速成课/系统课 Prompt 精调，确保章节结构符合 05 文档规范，系统课字数达标 ≥10000 |
| P0 | **LangSmith Dashboard** | 建立 tier 成本分析、降级监控、DocGen 端到端、检索器命中率等自定义视图 |
| P1 | **文生图实际接入** | 通义万相 / DALL-E API 接入，替换当前的文字建议占位 |
| P1 | **DocGen 事件 → WebSocket** | 打通 DocGen 进度事件到前端实时展示 |
| P1 | **教育 Teaching Skills** | `solve_step_by_step` / `generate_similar_problems` / `explain_formula` / `compare_concepts` |
| P2 | **本地教育语料库** | `data/edu_corpus/` 预置高数/线代/概率论知识条目 |
| P2 | **学术检索器扩展** | arXiv / Semantic Scholar / PubMed 等学术检索器 |
| P3 | **交互式 HTML** | iframe 沙箱 + Desmos / GeoGebra 嵌入 |
| P3 | **MCP 协议扩展** | MCPRetriever + MCPToolSelector |

---
