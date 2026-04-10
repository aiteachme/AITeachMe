# AITeachMe × GPT-Researcher 重构基线

> 文档定位：本目录不是”庆功手册”，而是后续 Digest 重构、工具分层和 LangSmith 接入的执行合同。
> 最后更新：2026-04-10

---

## 1. 本轮重构只做两件大事

### 1.1 工具体系与分层边界重整

核心目标不是“把 gpt-researcher 的目录搬过来”，而是把它的高价值模式吸收到当前仓库：

- Plan-Search-Compress-Write 的研究范式
- Fast / Smart / Strategic 的模型分层
- Retrievers / Scrapers / Skills 的可插拔设计
- 面向 LangSmith 的细粒度可观测性

同时要把 AITeachMe 自己的边界压实：

- `app.shared.infra`：通用 AI runtime、外部集成、canonical memory、retriever、scraper、skill 基座
- `app.teaching`：教学语义、教学模板、教学反馈解释、教学文档脚手架
- `app.workflows`：五大引擎的 LangGraph 编排

### 1.2 Digest 产出升级为“教育型 Deep Research”

目标不是生成一篇通用研究报告，而是生成一份真正可学习、可复习、可追问、可扩展的知识文档：

- 支持“速成课”与“系统课”两种课程模式
- 通过对话先确定构建选项，再进入构建
- 章节级 research 具备更强的靶向检索和缺口补齐能力
- 文档原生支持公式、Mermaid、配图、后续交互 HTML 插槽
- 与 `examine` / `profile` 的教学闭环自然衔接

---

## 2. 当前基线与主要风险

### 2.1 已有基线（2026-04-10 校准）

- `digest/docgen` 已有 **9 节点** LangGraph 主链路（load_context → targeted_research → collect_materials → resolve_titles → pedagogy_craft → collect_drafts → enrich_document → inject_examine → finalize_assemble），其中 `resolve_titles` 是后加的标题解析节点
- `digest/unified` 已有 6 节点顶层编排图（prepare_shared → run_parallel_lanes → derive_curriculum → publish_outputs → cleanup / fail），Doc Lane 与 KG Lane 通过 `asyncio.gather` 并行
- `shared/infra/` 已从单文件升级为完整 package，含 `tools/`（registry + decorator + builtin）、`skills/`（BaseSkill + 6 个业务 Skill）、`search/`（retrievers + scraper + factory）、`memory/`（canonical store）、`storage/`、`guardrails/` 等子包
- `shared/kernel/` 已独立为纯内核层（ids / time / events / exceptions）
- `teaching/` 已有 `documents/`（content_blocks + report_generation）、`memory/`（兼容 facade）、`context.py`、`skill_tools.py` 等
- 前端已具备 Markdown、Mermaid、公式的基础阅读能力，DigestBuildPanel 已有进度追踪
- LangSmith tracing 已有 `wrap_digest_node` + `LLMCallTracker` + `DigestTimingReport` 等基础设施
- Planner 对话流程已落地，支持 `build_session_id / planner_session_id / confirmed_plan_id` 串联

### 2.2 当前最需要先写清楚的风险（2026-04-10 更新）

| 风险 | 说明 | 当前状态 | 本轮文档策略 |
| --- | --- | --- | --- |
| `shared/infra` 与 `teaching` 边界仍有摇摆 | `memory` 出现双份实现（`shared/infra/memory` vs `teaching/memory`），`learner_doc.py` 路径语义分叉 | `teaching/context.py` 已正确依赖 `shared/infra/memory`，但 `teaching/memory/` 仍保留独立实现 | 明确 canonical 模块，标记过渡模块，禁止新增平行逻辑 |
| `confirmed_plan` 结构不够稳定 | 当前 `load_context_node` 从 `confirmed_plan` dict 中取 `chapter_plan`、`digest_mode`、`tone` 等，但缺少 schema 约束 | Planner 对话已落地，但输出仍是松散 dict | 定义 `BuildContract` Pydantic model，收紧上游输出 |
| Digest 章节研究仍是一次性 | `targeted_research_node` 调用 `ResearchConductor.run()` 一次，缺少”识别缺口 → 补检索”的质量驱动循环 | `ResearchConductor` 已有 plan-search-compress 基本能力 | 在 Skill 内部增加轻量微循环，不改 graph 拓扑 |
| 课程模式约束不够硬 | `course_type` 已在 state 中流转，但 `sprint` / `systematic` 的章节结构、字数目标、媒体策略仍靠 prompt 隐式控制 | `resolve_docgen_course_type()` 已存在 | 定义 05 文档中的产物契约，让 writer 和 enrich 节点显式遵守 |
| 不能为了 Digest 重构伤及其他引擎 | `ingest` / `interact` / `examine` / `profile` 需要保持稳定 | unified graph 已做到 Doc/KG 并行隔离 | 所有改动限制在 Docs Lane + shared/infra，不碰其他引擎 |
| `app/utils/docgen_store` 散落状态管理 | 多处直接调用 `update_knowledge_build_status()` 和 `append_knowledge_build_recent_event()`，状态更新逻辑分散在各节点中 | 已在用但缺少统一抽象 | 后续考虑收敛为 progress reporter 接口 |

---

## 3. 重构原则

1. 不做全仓“大一统重写”，优先修正边界、补齐契约、增强 DocGen 主链路。
2. 不照搬 `gpt-researcher` 的目录树，只吸收可证明有价值的方法。
3. `shared/infra` 解决“能力从哪里来、怎么接、怎么观测”；`teaching` 解决“教学语义如何表达”。
4. `digest` 的重构只动 Docs Lane，不改变 KG / Curriculum / 其他四大引擎的主逻辑。
5. 每个阶段都必须能在 LangSmith 上看清输入、输出、耗时、失败点。

---

## 4. 阅读顺序

| 文件 | 作用 |
| --- | --- |
| [01_architecture_alignment.md](01_architecture_alignment.md) | 看两个项目的能力映射，明确“学什么，不学什么” |
| [03_tools_refactor.md](03_tools_refactor.md) | 看 `infra / teaching / workflows` 的工具分层与迁移边界 |
| [04_docgen_pipeline.md](04_docgen_pipeline.md) | 看 Digest 如何升级成教育型 deep research 流程 |
| [05_document_modes.md](05_document_modes.md) | 看速成课 / 系统课的输出契约 |
| [06_retrieval_strategy.md](06_retrieval_strategy.md) | 看检索 profile、教育资源库、合规策略 |
| [07_teaching_tools.md](07_teaching_tools.md) | 看教学工具和通用工具怎样合理拆分 |
| [08_migration_plan.md](08_migration_plan.md) | 看 canonical 模块、过渡目录和清理顺序 |
| [09_execution_plan.md](09_execution_plan.md) | 看真正的实施阶段、验收口径和不改范围 |
| [10_langsmith_observability.md](10_langsmith_observability.md) | 看全链路 trace 规范 |
| [11_open_questions.md](11_open_questions.md) | 看尚需确认的产品/技术决策 |

---

## 5. 推荐实施顺序（2026-04-10 更新）

### Phase 0：边界冻结与文档对齐 ✅ 已完成

- 明确 `shared/infra`、`teaching`、`workflows` 三层职责
- 明确 canonical memory 在 `shared/infra/memory`
- 完成 refactor 系列文档初版

### Phase 1：LangSmith 契约加固与 Build Contract 收紧

- 统一 trace metadata（`course_type / retrieval_profile / teaching_action`）
- 定义 `BuildContract` Pydantic model 替代松散 `confirmed_plan` dict
- 打通 Planner → DocGen 的 LangSmith 关联

### Phase 2：检索 profile 与章节研究升级

- 引入显式检索 profile（`docgen_sprint` / `docgen_systematic`）
- `ResearchConductor` 内部增加轻量质量驱动微循环
- 补齐检索结果缓存，避免重复裸搜

### Phase 3：文档质量与课程模式收紧

- `sprint` / `systematic` 的章节结构契约硬编码到 writer 和 enrich 节点
- `PedagogyWriter` 输出带结构元信息的 `ChapterDraft`
- 引入显式 `AssetPlan` 替代自由占位符

### Phase 4：富媒体与教学闭环

- 完善 Mermaid / image / interactive HTML 插槽
- 接入 `teaching/documents` 的教学块（导读、recap、错因卡、公式卡）
- 把 `examine` / `profile` 的结果翻译成文档增强

---

## 6. 一句话结论

这轮 refactor 的正确姿势不是“把 gpt-researcher 搬进来”，而是：

- 用它的研究范式升级 `digest`
- 用它的可插拔思路整理 `infra`
- 用 AITeachMe 自己的教学语义沉淀 `teaching`
- 用 LangSmith 把整个构建过程变成可持续优化的透明系统
