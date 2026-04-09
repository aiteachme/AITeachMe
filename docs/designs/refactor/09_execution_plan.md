## 九、分阶段重构执行计划

> **最后更新**：2026-04-09 — 反映前端 Mermaid 渲染升级、Planner 概念预检索、检索层第一阶段重构和教学脚手架增强后的实际状态

### 9.1 总体原则（不变）

- **渐进式重构**：每个阶段都能独立运行和测试，不会出现"改了一半跑不起来"的情况
- **向后兼容**：旧 API 接口不变，前端无感知
- **LangSmith 先行**：每个新模块第一天就接入 LangSmith，不留"后补"的债
- **测试驱动**：每个节点都有独立的单元测试（mock LLM 调用）

---

### 9.2 Phase 0：基础设施层 — ✅ 已完成

| 任务 | 涉及文件 | 状态 |
|:---|:---|:---|
| 1. `acompletion_with_fallback()` 降级容错链 | `shared/infra/llm_support/fallback.py` | ✅ 已实现 tier 路由 + TaskType 降级链 |
| 2. `model_overrides` 差异化配置 | `shared/infra/config.py` | ✅ 已有机制 |
| 3. `.env` 差异化模型配置 | `.env` | ✅ 可选配置 |
| 4. `observability.py` 自动记录 `task_type` | `shared/infra/llm_support/observability.py` | ✅ LangSmith payload 已含 task_type |
| 5. `BaseRetriever` + `factory.py` | `shared/infra/search/retrievers/base.py` + `search/factory.py` | ✅ 工厂模式 + `get_retrievers_for_subject()` + 多检索器 list/profile 配置解析 |
| 6. Bing 检索器 | `shared/infra/search/retrievers/bing.py` | ✅ 已实现 |
| 7. DuckDuckGo 检索器 | `shared/infra/search/retrievers/duckduckgo.py` | ✅ 已实现 |
| 8. LocalRAG 检索器 | `shared/infra/search/retrievers/local_rag.py` | ✅ 已实现（向量 + section fallback） |
| 9. Tavily 检索器 | `shared/infra/search/retrievers/tavily.py` | ✅ 已实现 |
| 10. arXiv / Semantic Scholar 检索器 | `shared/infra/search/retrievers/arxiv.py` + `semantic_scholar.py` | ✅ 已实现 |
| 11. Scraper (BS4 + PDF) | `shared/infra/search/scraper/` | ✅ `BaseScraper` + BS4 + PyMuPDF |

**额外说明**：`Bocha` 检索器文件已建好，但当前仍是 placeholder，尚未接入真实 API。

### 9.3 Phase 1：Skills + Actions 层 — ✅ 已完成

| 任务 | 涉及文件 | 状态 |
|:---|:---|:---|
| 1. `BaseSkill` + `SkillContext` + `SkillResult` | `shared/infra/skills/base.py` | ✅ 含 `SkillRegistry` + `@skill` 装饰器 + `extract_skill_result_metadata()` |
| 2. `ContextManager` | `shared/infra/skills/context_manager.py` | ✅ 语义+词法双通道评分 + 段落去重 + 字符限制 |
| 3. `ResearchConductor` | `shared/infra/skills/researcher.py` | ✅ 子查询规划 → 多检索器并行 → 抓取 → SourceCurator → ContextManager → purify |
| 4. `query_processing.py` | `shared/infra/tools/builtin/query_processing.py` | ✅ `generate_sub_queries()` + `enrich_queries_for_education()` + `dedupe_queries()` |
| 5. `web_scraping.py` | `shared/infra/tools/builtin/web_scraping.py` | ✅ `scrape_urls()` 并行抓取 |
| 6. `markdown_processing.py` | `shared/infra/tools/builtin/markdown_processing.py` | ✅ TOC / headers / references / word_count |
| 7. `content_analysis.py` | `shared/infra/tools/builtin/content_analysis.py` | ✅ 术语抽取 / 片段定位 / 覆盖检测 |
| 8. `latex_processing.py` | `shared/infra/tools/builtin/latex_processing.py` | ✅ 数学分隔符规范化 |

**额外完成**：
- `SourceCurator`（`skills/source_curator.py`）— 域名可信度 + 词法重叠 + 本地源优先
- `PedagogyWriter`（`skills/writer.py`）— 教学化写作 Skill
- `web_search.py` / `search_kb.py` / `memory_ops.py` — 额外 builtin 工具

### 9.4 Phase 2：DocGen 流程重建 — ✅ 已完成

| 任务 | 涉及文件 | 状态 |
|:---|:---|:---|
| 1. `DocGenState` 重写 | `workflows/digest/docgen/state.py` | ✅ 含 chapter_assignments / materials / drafts / metadatas + operator.add 累加 |
| 2. `load_context_node.py` | `workflows/digest/docgen/nodes/` | ✅ 加载 shared_inputs + 验证 confirmed_plan + 规范化 chapter_assignments |
| 3. `targeted_research_node.py` | `workflows/digest/docgen/nodes/` | ✅ 调用 ResearchConductor + 构建 chapter_material |
| 4. `pedagogy_craft_node.py` | `workflows/digest/docgen/nodes/` | ✅ 调用 PedagogyWriter + 构建 chapter_draft |
| 5. `enrich_document_node.py` | `workflows/digest/docgen/nodes/` | ✅ Mermaid 占位符 + Image 占位符 + LaTeX 规范化 + 引用附录 |
| 6. `inject_examine_node.py` | `workflows/digest/docgen/nodes/` | ✅ 提取题目 + 生成练习章节 + 重建 TOC |
| 7. `collect_materials_node.py` | `workflows/digest/docgen/nodes/` | ✅ 聚合研究结果 + 发布进度事件 |
| 8. `collect_drafts_node.py` | `workflows/digest/docgen/nodes/` | ✅ 合并草稿 + 构建 chapter_metadatas + TOC |
| 9. `finalize_node.py` | `workflows/digest/docgen/nodes/` | ✅ stage_knowledge_docs + standalone 发布 |
| 10. `docgen/graph.py` 新拓扑 | `workflows/digest/docgen/graph.py` | ✅ 8 节点 LangGraph：load_context → targeted_research(fan-out) → collect_materials → pedagogy_craft(fan-out) → collect_drafts → enrich_document → inject_examine → finalize_assemble |
| 11. Prompts 重写 | `workflows/digest/prompts/` | ✅ `docgen_prompts.py` + `archetype_prompts.py` + `planner_prompts.py` |
| 12. `observability.py` 适配 | `workflows/digest/observability.py` | ✅ docs lane summary 已适配新节点名 |
| 13. `runtime.py` 入口适配 | `workflows/digest/runtime.py` | ✅ `run_docgen_workflow()` 已对接新 graph |

**关键里程碑已达成**：新版 DocGen 流程已替代旧版，无需 feature flag 切换。

### 9.5 Phase 3：富媒体增强 — 🟡 部分完成

| 任务 | 涉及文件 | 状态 | 备注 |
|:---|:---|:---|:---|
| 1. `ImageGenerator` | `shared/infra/skills/image_generator.py` | 🟡 框架就绪 | 占位符处理已实现，实际图片生成 API 待接入（通义万相 / DALL-E） |
| 2. `MermaidGenerator` | `shared/infra/skills/mermaid_generator.py` | ✅ 已完成 | mindmap 生成 + 关键词回退 |
| 3. 前端 Mermaid 渲染组件 | `frontend/src/components/ui/` | ✅ 已完成 | 已集成 `mermaid` 真渲染，失败时自动回退源码视图 |
| 4. 前端 KaTeX 公式渲染优化 | `frontend/src/components/ui/MarkdownViewer.tsx` | 🟡 部分完成 | 已统一 Markdown 渲染链路并强化 document 版式，复杂公式仍需人工验收 |
| 5. 前端文档阅读页面改版 | `frontend/src/pages/KnowledgeDocsPage.tsx` | ✅ 已完成 | 已支持 Mermaid SVG + 公式 + 资产图片 + 统一知识讲义样式 |

### 9.6 Phase 4：教育资源库 + 高级功能 — ⬜ 未开始

| 任务 | 涉及文件 | 状态 | 备注 |
|:---|:---|:---|:---|
| 1. 本地教育语料库 | `data/edu_corpus/` | ⬜ 待实现 | 先覆盖高数（微积分/线代/概率论） |
| 2. 教育 Teaching Skills | `shared/infra/skills/` 或 `teaching/` | ⬜ 待实现 | `solve_step_by_step` / `generate_similar_problems` / `explain_formula` / `compare_concepts` |
| 3. 交互式 HTML 支持 | `shared/infra/skills/interactive_builder.py` | ⬜ V2 预留 | iframe 沙箱 + Desmos / GeoGebra |
| 4. Anki 导出 | `shared/infra/tools/builtin/` | ⬜ V2 预留 | 接口定义 + stub |

### 9.7 Phase 5（新增）：文档质量调优 + 端到端验证 — 🟡 已启动

> 这是 Phase 0-2 完成后最关键的阶段——基础设施已就绪，现在需要确保**生成的文档质量真正超越 PPT**。

**已落地的第一步**：

- Planner 已从“直接让 LLM 生成研究任务”升级为 `load_context → ground_concepts → draft_plan`
- `ground_concepts` 会先做轻量概念预检索：
  - 优先使用 `local_rag`
  - 可选补充外部百科/定义类检索
  - 产出 `concept_briefing` + `concept_topic_hints`
- `draft_plan` Prompt 已强制要求参考概念锚点再生成研究任务，避免裸生成
- 前端 Planner 运行态已显示 `概念预检索` 节点，便于用户和 LangSmith 对齐排查
- 检索层第一阶段已落地：
  - `config.py` 支持 `web_search_retrievers` / `web_search_retriever_profile`
  - `factory.py` 支持多检索器组合、去重和 DuckDuckGo 兜底
  - `TavilyRetriever` / `ArxivRetriever` / `SemanticScholarRetriever` 已接入，可作为 `docgen_balanced` / `docgen_academic` 组合的一部分
- `infra -> teaching` 的第一批分层复用已落地：
  - `content_analysis.py` 提供通用术语抽取与覆盖检测
  - `teaching/documents` 开始基于它生成 `术语速览` 和 `学习目标对照` 教学块

| 任务 | 涉及文件 | 验证方式 |
|:---|:---|:---|
| 1. 速成课 Prompt 精调 | `prompts/archetype_prompts.py` + `docgen_prompts.py` | 生成"偏导数"速成课，人工评审 4 节结构是否符合 05 文档规范 |
| 2. 系统课 Prompt 精调 | 同上 | 生成"线性代数"系统课，验证字数 ≥ 10000 + 知识脉络完整 |
| 3. `edu_planner` 章节规划质量 | `planner/` + `planner_prompts.py` | 验证 grounding 后的研究任务能稳定覆盖核心概念；速成课 3-6 节、系统课 5-12 节自适应 |
| 4. `tone` 参数效果验证 | `docgen_prompts.py` | 对比 casual / professional / encouraging / concise 四种风格输出 |
| 5. 检索命中率分析 | LangSmith Dashboard | 建立 retriever_name 分组视图，分析 Planner grounding 与 DocGen research 的 local_rag vs web 命中比 |
| 6. 端到端性能基线 | LangSmith + 手动计时 | 速成课 < 2min，系统课 < 5min |
| 7. LangSmith 自定义 Dashboard | LangSmith UI | 建立 10 文档中定义的 8 个 Dashboard |

### 9.8 性能目标（不变，待实测验证）

| 节点 | 目标延迟 | 并发度 | Token 预算 |
|:---|:---|:---|:---|
| `edu_planner`（Planner 阶段） | < 15s | 1（串行，含 `ground_concepts`） | REASONING: 4000 |
| `targeted_research` × N | < 20s（含搜索+抓取+压缩） | N=章节数，受 `docgen_max_parallel_chapters` 控制 | DOCGEN_LIGHT: 3000/章 |
| `pedagogy_craft` × N | < 30s/章 | 同上 | DOCGEN: 8000/章 |
| `enrich_document` | < 15s | 图片并行生成（max 3） | DOCGEN_LIGHT: 1000 |
| 端到端（速成课 4 章） | **< 2 分钟** | — | — |
| 端到端（系统课 8 章） | **< 5 分钟** | — | — |

> [!TIP]
> 性能对标参考：gpt-researcher 标准研究流程 1-3 分钟（3 个子查询）。我们的速成课 4 章并发等效于 4 个子查询，性能预期应与其相当。

### 9.9 缓存策略（不变）

| 缓存对象 | Key | TTL | 后端 |
|:---|:---|:---|:---|
| `edu_planner` 输出 | `(subject, digest_mode, tone, file_ids_hash, user_goal_hash)` | 24h | 内存 dict（MVP），后续切 Redis |
| `ground_concepts` 结果 | `(subject, file_ids_hash, topic_hints_hash, user_goal_hash)` | 6h | 内存 dict |
| 检索结果 | `(query, retriever_name)` | 1h | 内存 dict |
| 网页抓取结果 | URL | 24h | 内存 dict |
| Embedding 向量 | `(text_hash, model)` | 永久 | sqlite-vec（已有） |

**缓存失效策略**：
- 用户上传新文件后，该 subject 的 `edu_planner` 与 `ground_concepts` 缓存立即失效
- 超过 TTL 的缓存惰性清理（下次访问时检查）

### 9.10 回滚策略（已简化）

Phase 0-2 已完成并稳定运行，旧版 graph 已移除。后续阶段回滚策略：

| 阶段 | 回滚机制 |
|:---|:---|
| Phase 3 (富媒体) | 纯新增 → 删除即回滚；ImageGenerator 当前已有 fallback（返回文字建议） |
| Phase 4 (教育资源库) | 纯新增 → 删除即回滚 |
| Phase 5 (质量调优) | Prompt 修改通过 git 版本控制回滚 |

### 9.11 测试策略（不变）

| 测试类型 | 范围 | 工具/方法 |
|:---|:---|:---|
| **单元测试** | 每个节点 mock LLM 调用，验证输入输出格式 | pytest + unittest.mock |
| **集成测试** | 用 `langgraph dev` 跑完整流程，验证 trace 树 | langgraph dev + LangSmith |
| **质量测试** | 生成 "偏导数" 速成课 + 系统课各一份，人工评审 | 人工评审 checklist |
| **性能测试** | 计时端到端延迟，对比 9.8 性能目标 | pytest-benchmark / 手动 |
| **回归测试** | 确认其他四大引擎（ingest/interact/examine/profile）不受影响 | pytest |

**质量评审 checklist**：
- [ ] 章节结构符合 05_document_modes.md 定义
- [ ] LaTeX 公式正确渲染（前端 KaTeX）
- [ ] Mermaid 思维导图语法合法（前端 Mermaid.js）
- [ ] 速成课包含秒杀口诀 + 范例题（≥ 2 道/节）
- [ ] 系统课字数 ≥ 10000
- [ ] 所有引用有来源 URL
- [ ] LangSmith trace 树结构清晰，每个节点输入输出可查

---
