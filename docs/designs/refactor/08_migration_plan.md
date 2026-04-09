## 八、要删除 / 废弃的旧文件清单

> **最后更新**：2026-04-09 — 反映检索层第一阶段重构后的实际文件状态

### 8.1 Docs Lane 废弃文件 — ✅ 已清理完毕

以下旧文件已在 Phase 2 完成后被替代（确认是否已从代码库中物理删除）：

| 文件 | 原来的功能 | 被什么替代 | 处理方式 |
|:---|:---|:---|:---|
| `nodes/cleanse_node.py` | 文本清洗（LLM 自愈） | `targeted_research` 中的 ContextCompressor 自带降噪 | 删除 |
| `nodes/outline_map_node.py` | 从 chunks 提取局部大纲 | `edu_planner` 统一规划（不依赖原文结构） | 删除 |
| `nodes/outline_reduce_node.py` | 合并局部大纲为全局大纲 | `edu_planner` 统一规划 | 删除 |
| `nodes/review_node.py` | 章节审阅 | 取消独立 review（质量由 Planner + Research 前置保障） | 删除 |
| `nodes/metadata_node.py` | 元数据提取 | 合并进 `finalize_assemble` | 删除 |
| `strategy.py` | 旧版执行策略（CleanseDecision / OutlineExecutionPlan / ReviewExecutionPlan） | 新版 strategy 只保留 `chapter_semaphore` + `io_semaphore` | 重写 |
| `prompts/docgen_prompts.py` | 旧版 Prompt | 全部重写为教育极性 Prompt（速成/系统双模式） | 重写 |

### 8.2 保留并复用的文件 — ✅ 已完成改造

| 文件 | 原来的功能 | 当前状态 |
|:---|:---|:---|
| ~~`nodes/load_files_node.py`~~ → `nodes/load_context_node.py` | 加载用户文件 chunks | ✅ 已改名并重写，加载 shared_inputs + 验证 confirmed_plan + 规范化 chapter_assignments |
| ~~`nodes/draft_node.py`~~ → `nodes/pedagogy_craft_node.py` | 章节写作 | ✅ 已重写，调用 PedagogyWriter Skill |
| `nodes/finalize_node.py` | 组装入库 | ✅ 已扩展，支持 standalone/unified 双模式发布 |
| `state.py` | DocGenState 定义 | ✅ 已重写，含 chapter_assignments / materials / drafts / metadatas + operator.add 累加 |
| `graph.py` | LangGraph 拓扑 | ✅ 已重写为 8 节点新拓扑（含 fan-out Send） |
| `services/writer_service.py` | LLM 写作服务 | ✅ 保留，PedagogyWriter Skill 内部调用 |

### 8.3 新增文件清单 — ✅ 已全部创建

| 文件 | 功能 | 状态 |
|:---|:---|:---|
| `nodes/load_context_node.py` | 上下文加载 + plan 验证 + 章节分配规范化 | ✅ |
| `nodes/targeted_research_node.py` | 靶向素材搜刮（调用 ResearchConductor） | ✅ |
| `nodes/collect_materials_node.py` | 聚合多章研究结果 | ✅ |
| `nodes/pedagogy_craft_node.py` | 教学化写作（调用 PedagogyWriter） | ✅ |
| `nodes/collect_drafts_node.py` | 合并草稿 + 构建 chapter_metadatas + TOC | ✅ |
| `nodes/enrich_document_node.py` | Mermaid/Image 占位符处理 + LaTeX 规范化 + 引用附录 | ✅ |
| `nodes/inject_examine_node.py` | 联动出题 + 练习章节生成 | ✅ |
| `prompts/docgen_prompts.py` | DocGen 写作/研究/Mermaid/子查询 Prompt | ✅ |
| `prompts/archetype_prompts.py` | 章节原型 Prompt（概念构建/方法求解/题型/复习） | ✅ |
| `prompts/planner_prompts.py` | Planner 规划 Prompt | ✅ |

**额外新增的基础设施文件**（Phase 0/1 产出）：

| 文件 | 功能 | 状态 |
|:---|:---|:---|
| `shared/infra/llm_support/fallback.py` | tier 路由 + TaskType 降级容错链 | ✅ |
| `shared/infra/search/retrievers/base.py` | BaseRetriever 抽象基类（含 LangSmith tracing） | ✅ |
| `shared/infra/search/retrievers/bing.py` | Bing Search API 检索器 | ✅ |
| `shared/infra/search/retrievers/duckduckgo.py` | DuckDuckGo 检索器 | ✅ |
| `shared/infra/search/retrievers/bocha.py` | 博查搜索检索器 | 🟡 文件已建，真实 API 待接入 |
| `shared/infra/search/retrievers/tavily.py` | Tavily research 检索器 | ✅ |
| `shared/infra/search/retrievers/local_rag.py` | 本地 RAG 检索器（向量 + section fallback） | ✅ |
| `shared/infra/search/scraper/base.py` | BaseScraper 抽象基类 | ✅ |
| `shared/infra/search/scraper/bs4_scraper.py` | BeautifulSoup HTML 抓取 | ✅ |
| `shared/infra/search/scraper/pdf_scraper.py` | PyMuPDF PDF 提取 | ✅ |
| `shared/infra/skills/researcher.py` | ResearchConductor Skill | ✅ |
| `shared/infra/skills/writer.py` | PedagogyWriter Skill | ✅ |
| `shared/infra/skills/context_manager.py` | ContextManager Skill（上下文压缩） | ✅ |
| `shared/infra/skills/source_curator.py` | SourceCurator Skill（来源质量评估） | ✅ |
| `shared/infra/skills/image_generator.py` | ImageGenerator Skill（框架就绪） | 🟡 |
| `shared/infra/skills/mermaid_generator.py` | MermaidGenerator Skill | ✅ |
| `shared/infra/tools/builtin/query_processing.py` | 子查询生成 + 教育域搜索增强 | ✅ |
| `shared/infra/tools/builtin/web_scraping.py` | 并行 URL 抓取 | ✅ |
| `shared/infra/tools/builtin/markdown_processing.py` | TOC / headers / references / word_count | ✅ |
| `shared/infra/tools/builtin/latex_processing.py` | 数学分隔符规范化 | ✅ |

### 8.4 迁移时间线与策略 — 实际执行记录

| 阶段 | 动作 | 状态 |
|:---|:---|:---|
| Phase 0 完成 | 新增 `fallback.py` + 检索器工厂 + Scraper | ✅ 已完成 |
| Phase 1 完成 | 新增 6 个业务 Skill + 7 个 builtin Action | ✅ 已完成 |
| Phase 2 完成 | 新版 DocGen graph 直接替代旧版（无需 feature flag） | ✅ 已完成 |
| Phase 3 进行中 | MermaidGenerator 已完成，ImageGenerator 框架就绪 | 🟡 部分完成 |
| Phase 4 | 教育资源库 + Teaching Skills | ⬜ 未开始 |

**关键说明**：
- 新版 DocGen 流程已直接替代旧版，**未使用 feature flag 切换**（旧版 graph 已移除）
- `DocGenState` **无需数据迁移**：State 是 LangGraph 运行时对象，不持久化到 DB
- `observability.py` 的 `build_docs_lane_summary()` 已适配新节点名

### 8.5 废弃的配置参数 — 待确认清理状态

以下 `config.py` 中的参数与**旧 DocGen 流程**绑定，新流程中不再需要（需确认是否已从 config.py 中移除）：

| 参数 | 旧用途 | 新流程替代 | 处理方式 |
|:---|:---|:---|:---|
| `docgen_skip_llm_cleanse_for_clean_markdown` | 跳过 cleanse 节点 | 新流程无 cleanse 节点 | 删除 |
| `docgen_skip_llm_review_for_single_chapter` | 跳过 review 节点 | 新流程无 review 节点 | 删除 |
| `docgen_outline_fast_path_max_chunks` | outline 快速路径判断 | 新流程 edu_planner 不依赖 chunks 数 | 删除 |
| `docgen_review_retry_mode` | review 重试模式 | 新流程无 review | 删除 |
| `docgen_review_fast_path_max_chapters` | review 快速路径判断 | 新流程无 review | 删除 |
| `docgen_metadata_fallback_llm` | metadata 提取降级 | 合并到 `finalize_assemble` 内部逻辑 | 删除 |

**保留的参数**：
- `docgen_max_parallel_chapters` → 沿用，对应新流程的 `chapter_semaphore`
- `docgen_io_parallelism` → 沿用，控制文件 I/O 并行度

### 8.6 架构层面已完成的清理

| 改动 | 说明 |
|:---|:---|
| `subject_embeddings.py` → `subject_settings.py` | 重命名为更准确的名称，旧文件已删除 |
| `infra/context.py` → `teaching/context.py` | 教学上下文逻辑归入 `teaching/` 包，infra 旧文件已删除 |
| `infra/teaching.py` → `teaching/teaching.py` | 教学函数逻辑归入 `teaching/` 包，infra 旧文件已删除 |

---
