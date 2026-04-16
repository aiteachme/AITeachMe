# DocGen 改造计划

最后更新：2026-04-16

一句话概括：接下来不推翻现有 DocGen，而是在 `confirmed plan -> research -> write -> enrich -> practice -> publish` 这条主线上，先修前后端构建合同和失败降级口径，再补强章节研究、证据账本、质量审校、Examine 练习注入和资产生命周期，让知识文档生成从“能跑出一篇文档”升级成“可控、可审、可恢复的教学研究生成链路”。

最小落地顺序：

```text
1. 修 docs 构建必须携带 confirmed_plan_id 的前后端入口问题
2. 统一核心步骤 strict、增强步骤 fallback 的失败策略
3. 给 Planner 和 finalize_titles 增加可解释降级
4. 让 DocGen research 复用 shared search 的并发检索与融合能力
5. 增加 evidence ledger，让章节内容有证据账本
6. 增加 review / rewrite，保证章节质量不过线时能修一次
7. 将 practice 接入 Examine，规则题只做兜底
8. 建立 asset manifest，管理 Mermaid、图片和交互块生命周期
```

阅读方式：先看上面的最小落地顺序；需要动手时再按后文的 P0/P1/P2 分阶段计划拆任务。

当前权威代码入口：

- API 入口：`backend/app/api/knowledge_docs.py`
- DocGen build：`backend/app/workflows/digest/docgen/builds.py`
- DocGen graph：`backend/app/workflows/digest/docgen/graph.py`
- DocGen 状态：`backend/app/workflows/digest/docgen/state.py`
- DocGen 节点：`backend/app/workflows/digest/docgen/nodes/`
- DocGen 内部能力：`backend/app/workflows/digest/docgen/lib/`

## 1. 总体判断

当前 DocGen 的主方向是正确的：

```text
confirmed plan
  -> load_context
  -> research_chapters
  -> finalize_titles
  -> write_chapters
  -> enrich_assets
  -> append_practice
  -> publish_document
```

这条链路已经具备几个重要基础：

- 文档生成必须消费用户确认后的 `ConfirmedBuildPlan`。
- 章节 research 和章节 writing 已经通过 LangGraph fan-out 并行。
- 本地资料优先，缺口不足时再外部检索。
- 已有 source curation、URL reading、context compression、coverage gap loop。
- 已有 sprint / systematic 模式区分。
- 已有 Mermaid、图片建议、interactive HTML 的 asset sidecar 雏形。
- 已有 `_build/` staging、正式发布、manifest 与版本归档。

后续不建议做大规模重写。更合适的路线是：保留现有 graph 骨架，逐步补强合同、研究质量、证据追踪、审校重写、练习生成和资产生命周期。

目标形态：

```text
Confirmed Plan
  -> Research Brief
  -> Chapter Research Workers
  -> Evidence Ledger
  -> Chapter Writer
  -> Chapter Critic / Rewrite
  -> Document Editor
  -> Asset Sidecar
  -> Examine Practice Injection
  -> Citation Finalizer
  -> Publish + Manifest
```

## 2. 外部参考原则

这里借鉴的是 Deep Research 类产品和 agentic RAG 的工程原则，而不是照搬它们的产品形态。

### OpenAI Deep Research

OpenAI Deep Research 强调复杂研究任务要能使用 public web、file search、vector stores、remote MCP 和 code interpreter，并且适合后台长任务。对 AITeachMe 的启发：

- 资料来源应分层：用户上传资料、本地向量库、公共 Web、专业来源。
- Prompt/plan 中要显式指定输出结构、来源优先级、语言与引用要求。
- 长任务应有可轮询状态、可恢复中间产物和明确失败原因。

参考：`https://developers.openai.com/api/docs/guides/deep-research`

### Gemini Deep Research

Gemini Deep Research 的关键体验是先生成 multi-step research plan，用户可修改或批准，然后系统多轮搜索、阅读、基于新发现继续搜索，最后生成带来源链接的报告。对 AITeachMe 的启发：

- Planner 不只是目录生成器，而是 research plan / teaching brief 生成器。
- 用户确认 plan 后，DocGen 应严格按 plan 执行。
- Research 阶段应能根据 gap 继续补查，而不是一次检索后直接写。

参考：`https://blog.google/products-and-platforms/products/gemini/google-gemini-deep-research/`

### Anthropic Research

Anthropic 的多智能体研究系统使用 orchestrator-worker 模式：lead agent 分解任务，多个 subagents 并行探索，最后 citation agent 处理来源。对 AITeachMe 的启发：

- 多 agent 更适合 research 阶段，不适合让多个 agent 各自写最终报告后硬拼。
- 每个 research worker 应有独立目标、工具边界、输出格式和停止条件。
- effort budget 要按任务复杂度分配，避免简单任务过度消耗。
- Citation / evidence 需要独立处理，不能只靠正文里自然语言“看起来有依据”。

参考：`https://www.anthropic.com/engineering/multi-agent-research-system`

### LangChain Open Deep Research

LangChain Open Deep Research 总结为 `Scope -> Research -> Write`。它特别指出，多 agent 适合并行研究，但并行写报告容易造成段落割裂。对 AITeachMe 的启发：

- 当前章节并行 research 是合理的。
- 最终文档需要统一 writer/editor 收口，确保学习路线连续。
- 需要把用户目标和 planner 对话压缩成 research brief，贯穿研究与写作。

参考：`https://www.langchain.com/blog/open-deep-research`

## 3. 当前重大问题

### P0-1：前端构建入口与后端 confirmed plan 合同不一致

后端 docs 构建已经强制要求 `confirmed_plan_id`。这符合新的产品路径：先 planner，后 confirm，再 DocGen。

风险点：

- `DigestBuildButton` 仍然按旧逻辑只提交 `file_uids`。
- 后端会抛出 `CONFIRMED_BUILD_PLAN_REQUIRED`。
- 图谱侧边栏也复用了这个按钮，可能导致用户从非 planner 页面触发失败。

建议：

- docs 构建入口必须基于 latest confirmed plan。
- 如果当前 subject 没有 confirmed plan，前端应引导进入 BuildPlanPage。
- `DigestBuildButton` 拆成更明确的 `DocsBuildButton` 与 `GraphBuildButton`。
- `GraphBuildButton` 保持 `build_type = "graph"`，不要求 confirmed plan。

涉及文件：

- `frontend/src/components/pages/DigestBuildPanel.tsx`
- `frontend/src/hooks/useKnowledgeBuildFlow.ts`
- `backend/app/workflows/digest/docgen/builds.py`

### P0-2：strict failure 与 fallback 口径冲突

当前文档中存在两种口径：

- `docs/designs/refactor/02_landed_decisions.md`：Strict failure 模式，无静默 fallback。
- `docgen/README.md`：建议 Mermaid、标题等子步骤提供失败降级。

实际代码也已经出现混合状态：

- Writer 主 LLM 失败会抛错。
- Mermaid LLM 失败会生成规则 mindmap fallback。
- 测试里仍有 Mermaid 失败必须抛错的断言。

建议分层定义：

| 层级 | 失败策略 | 原因 |
| --- | --- | --- |
| 核心内容层 | strict | 不能在正文完全失败时伪装成功 |
| 增强层 | soft fallback | 不应让图、标题、交互块拖垮整本文档 |
| 发布层 | strict | 持久化和 manifest 错误必须暴露 |

核心内容层包括：

- `load_context`
- `research_chapters` 主研究
- `write_chapters` 主正文
- `publish_document`

增强层包括：

- `finalize_titles`
- Mermaid 生成
- 图片生成或建议块
- interactive HTML
- practice injection

具体建议：

- Writer 主 LLM 失败继续失败。
- `finalize_titles` 单章失败使用 planner 标题并记录 `title_resolution_fallback_used = true`。
- Mermaid 失败使用规则图并记录 fallback reason。
- Image 失败使用配图建议块。
- Practice 接 Examine 失败后使用当前规则题兜底。
- 测试和 README 同步为这套口径。

### P0-3：Planner fallback 已有，但失败时没有真正返回 fallback plan

当前 `draft_plan` 已经构造了 `fallback_plan`，但主模型流式失败或没有有效任务时仍直接 raise。

建议：

- 主模型 stream 失败时返回 fallback plan。
- 标记 `planner_generation_mode = "fallback"`。
- 在 response/runtime stats 中带上 fallback reason。
- 标题二次生成失败时保留 provisional title，不影响 planner 返回。

涉及文件：

- `backend/app/workflows/digest/planner/nodes/draft_plan.py`
- `backend/app/workflows/digest/planner/lib/plans.py`

### P0-4：DocGen research 未充分复用 search 层并发融合

`shared/infra/search/web.py` 已经有并发 retriever 调度与 RRF 融合。DocGen 章节 research 目前仍在自己的 runtime 中逐个 query、逐个 retriever 执行。

建议：

- 将章节 research 的检索调度逐步收口到 `shared.infra.facade.research` 或 `shared.infra.search.dispatch_web_search`。
- 保留 DocGen 自己的教学语义判断、gap assessment 和 output contract。
- 不在 DocGen 内再扩展第二套 provider 并发与融合逻辑。

涉及文件：

- `backend/app/workflows/digest/docgen/lib/chapter_context.py`
- `backend/app/shared/infra/search/web.py`
- `backend/app/shared/infra/facade/research.py`

## 4. 目标 graph 设计

短期 graph：

```text
load_context
  -> research_chapters
  -> merge_research
  -> finalize_titles
  -> write_chapters
  -> review_chapters
  -> rewrite_chapters
  -> merge_drafts
  -> enrich_assets
  -> append_practice
  -> publish_document
```

长期 graph：

```text
load_context
  -> build_research_brief
  -> chapter_research_workers
  -> merge_evidence
  -> finalize_titles
  -> chapter_writer
  -> chapter_critic
  -> chapter_rewriter
  -> document_editor
  -> asset_sidecar
  -> examine_injection
  -> citation_finalizer
  -> publish_document
```

不建议一开始就拆得太细。第一阶段只加 `review_chapters / rewrite_chapters`，并增强现有 research 和 publish。

## 5. 数据合同设计

### 5.1 Research Brief

Planner confirmed plan 应进一步收束成 DocGen 可执行的 research brief。

建议结构：

```python
{
    "subject": str,
    "user_goal": str,
    "digest_mode": "sprint" | "systematic",
    "course_type": str,
    "tone": str,
    "source_strategy": "local_first" | "web_first",
    "preferred_source_classes": list[str],
    "include_sources": bool,
    "quality_targets": {
        "min_chapter_quality": float,
        "min_coverage_score": float,
        "require_examples": bool,
        "require_formulas": bool,
        "require_citations": bool,
    },
    "chapters": list[ChapterResearchBrief],
}
```

### 5.2 Chapter Research Brief

每章 research worker 的输入应从 loose dict 升级成显式合同。

```python
{
    "chapter_index": int,
    "title": str,
    "objective": str,
    "required_elements": list[str],
    "search_queries": list[str],
    "writing_instructions": str,
    "source_file_ids": list[int],
    "media_hints": {
        "mermaid": list[str],
        "images": list[str],
        "interactive": list[str],
    },
    "execution_contract": {
        "target_word_count": int,
        "min_word_count": int,
        "coverage_requirements": list[str],
        "min_coverage_score": float,
        "media_quota": dict,
        "practice_quota": dict,
    },
}
```

现有 `DigestChapterContract.to_assignment(...)` 已经接近这个形态，后续可优先在字段语义和校验上增强，不必另起一套 incompatible contract。

### 5.3 Evidence Ledger

建议新增章节级 evidence ledger。它是后续引用、审校、rewrite、Examine 出题的共同依据。

```python
{
    "evidence_id": str,
    "chapter_index": int,
    "claim_type": "definition" | "formula" | "example" | "method" | "warning" | "source_note",
    "claim": str,
    "source_url": str,
    "source_title": str,
    "source_kind": "local" | "academic" | "institutional" | "community" | "general_web",
    "source_file_id": int | None,
    "excerpt": str,
    "confidence": float,
}
```

Ledger 来源：

- local RAG chunk
- external page excerpt
- curated source metadata
- compressed context

Ledger 用途：

- Writer 限制关键结论必须来源于 ledger。
- Critic 检查正文是否脱离 evidence。
- Citation finalizer 生成章节参考。
- Examine 生成题目时区分概念、公式、例题、易错点。

### 5.4 Chapter Review

章节审校输出：

```python
{
    "chapter_index": int,
    "passed": bool,
    "scores": {
        "structure": int,
        "teachability": int,
        "mode_fit": int,
        "explanation_depth": int,
        "evidence_grounding": int,
        "presentation": int,
    },
    "blocking_issues": list[str],
    "rewrite_instructions": str,
    "rewrite_required": bool,
}
```

评分门槛建议先沿用设计文档：

- `sprint`：总分不低于 18/30。
- `systematic`：总分不低于 22/30，且结构清晰度、教学可学性不得低于 4。

### 5.5 Asset Manifest

后续 asset 不应只混在 Markdown 里，应有 manifest。

```python
{
    "asset_id": str,
    "chapter_index": int,
    "kind": "mermaid" | "image" | "interactive_html",
    "prompt": str,
    "status": "generated" | "fallback" | "failed",
    "content_key": str | None,
    "inline_markdown": str | None,
    "fallback_reason": str | None,
    "render_contract": dict,
}
```

这能支持：

- 前端稳定渲染。
- 后续导出 PDF / Word。
- 图片真实生成。
- asset 失败可解释。

## 6. Research 层改造

### 6.1 当前流程

当前 `DocGenChapterContextRuntime.execute(...)` 大致为：

```text
base queries
  -> LLM sub queries
  -> local RAG
  -> local insufficient then external retrievers
  -> source curation
  -> URL reading
  -> context compression
  -> coverage assessment
  -> gap query enqueue
  -> repeat until stop
  -> purify material
```

这个方向是对的，但内部可维护性和检索效率需要提升。

### 6.2 目标流程

```text
ChapterResearchBrief
  -> plan_queries
  -> retrieve_candidates
  -> fuse_candidates
  -> curate_sources
  -> read_sources
  -> compress_context
  -> extract_evidence
  -> assess_gaps
  -> maybe_followup_round
  -> ChapterResearchMaterial
```

### 6.3 检索策略

分层来源：

| Layer | 来源 | 当前状态 | 后续动作 |
| --- | --- | --- | --- |
| 0 | 用户上传资料 local RAG | 已有 | 保持最高优先级 |
| 1 | subject / 系统教育语料库 | 未建 | 后续建设 |
| 2 | 教育垂直 Web | 部分已有 | 按学科 profile 加权 |
| 3 | 学术来源 | 已有 arxiv / semantic_scholar | systematic 优先 |
| 4 | 通用 Web | 已有 | 兜底 |

模式差异：

| 模式 | Research 侧重点 |
| --- | --- |
| `sprint` | 高频题型、公式速用、易错点、真题/例题 |
| `systematic` | 定义、推导、前置关系、边界条件、应用 |

### 6.4 并发策略

建议保留当前章节级 fan-out，同时增强章节内部检索：

```text
章节间：LangGraph Send 并行
章节内：retriever provider 并发 + RRF 融合
URL reading：read_urls 并发
LLM purify：每章最多 1 次
```

避免过度并发：

- 遵守 `llm_concurrency_limit`。
- `docgen_max_parallel_chapters` 不应默认过高。
- 对外部检索设置总预算和 provider 预算。
- 对 search-only 模式单独限流。

### 6.5 Gap assessment

当前 gap assessment 偏字符串包含。建议逐步升级：

```python
{
    "coverage_score": float,
    "gaps_remaining": list[str],
    "concept_density": float,
    "example_density": float,
    "formula_presence": bool,
    "source_quality_score": float,
    "citation_coverage": float,
    "stop_reason": str,
}
```

先做规则和 metadata 统计，后续再接 LLM judge。

## 7. Writing 层改造

### 7.1 Writer 输入

Writer 需要同时消费：

- chapter research material
- dense context
- evidence ledger
- execution contract
- digest mode
- skillpack guidance
- user goal

Prompt 应明确：

- 不写研究笔记。
- 不堆来源列表。
- 关键结论必须能在 evidence 中找到依据。
- 输出中文 Markdown。
- 一级标题必须等于最终章节标题。
- sprint 和 systematic 的结构差异必须体现。

### 7.2 Writer 输出

建议 `chapter_draft` 增强字段：

```python
{
    "chapter_index": int,
    "title": str,
    "markdown": str,
    "summary": str,
    "tags": list[str],
    "word_count": int,
    "source_details": list[dict],
    "evidence_ids_used": list[str],
    "coverage_score": float,
    "quality_score": float,
    "repair_actions": list[str],
}
```

### 7.3 Review / Rewrite

新增节点：

```text
review_chapters
  -> route
     pass -> merge_drafts
     fail -> rewrite_chapters
```

Rewrite 原则：

- 每章最多 rewrite 1 次。
- 只重写失败章节。
- rewrite prompt 必须带原文、review issues、evidence ledger。
- rewrite 失败时保留原 draft，但标记 `quality_warning`，除非原文为空。

## 8. Title Resolution 策略

当前 `finalize_titles` 会根据研究材料重新命名章节。这个方向对，但不应成为整单失败点。

建议：

- 单章标题 LLM 失败时使用 planner title。
- 如果 LLM 输出标题不可用，用 `coerce_resolved_chapter_title(...)` 兜底。
- 状态里记录：
  - `title_resolution_fallback_used`
  - `title_resolution_error`
  - `resolved_title_source = "llm" | "planner" | "fallback"`

这样既保留质量，又不让标题增强拖垮构建。

## 9. Practice 接 Examine

当前 `append_practice` 是规则生成。后续建议接入 Examine 的 question build 能力。

目标流程：

```text
chapter_metadatas
  -> build_practice_blueprint
  -> examine/question_build
  -> normalize_questions
  -> append_practice_markdown
```

Practice blueprint：

```python
{
    "digest_mode": str,
    "chapters": [
        {
            "chapter_index": int,
            "title": str,
            "required_elements": list[str],
            "evidence_summary": str,
            "weak_points": list[str],
            "practice_quota": dict,
        }
    ]
}
```

题型建议：

| 模式 | 题型 |
| --- | --- |
| `sprint` | 高频题型识别、易错判断、速记回忆、变式训练 |
| `systematic` | 概念解释、推理链、应用迁移、边界反例 |

失败策略：

- Examine 成功：使用结构化题目。
- Examine 失败：使用当前规则题。
- 部分章节失败：失败章节使用规则题，成功章节保留 Examine 题。

## 10. Asset Sidecar 改造

### 10.1 Mermaid

当前 Mermaid 已有 LLM 生成和规则 fallback。建议增强：

- 支持 mindmap / flowchart 两类。
- 根据章节类型选择图类型。
- 生成后做语法校验。
- manifest 记录 fallback reason。

### 10.2 Image

当前图片主要是建议块。后续接文生图时，需要：

- 生成 prompt。
- 调 image generation。
- 写入 content store。
- manifest 记录路径和渲染规格。
- 前端按 asset manifest 渲染。

### 10.3 Interactive HTML

当前 interactive 是内联 HTML。后续建议：

- 统一 `data-atm-kind` 类型。
- 每种交互块都有 render contract。
- 前端可选择原生 React 组件渲染，而不是只信任 HTML。
- 导出时有降级纯文本。

## 11. Publish / Storage 改造

当前 `_build` staging 已经是好基础。建议增强为可恢复构建：

```text
_build/
  status.json
  manifest.json
  research/
    chapter_01.json
  drafts/
    chapter_01.md
  reviews/
    chapter_01.json
  assets/
    manifest.json
  merged_knowledge_base.md
```

发布规则：

- 每章 research 完成后写 staging。
- 每章 draft 完成后写 staging。
- review 和 asset manifest 也写 staging。
- `publish_document` 只做最终 promotion。

收益：

- 构建中断后可以看见阶段性成果。
- 前端 draft preview 更稳定。
- 后续可以做 resume。

## 12. Observability 与状态

当前有 progress、recent events、LLM metrics。建议补充：

### 12.1 Research metrics

```python
{
    "chapter_index": int,
    "local_hits": int,
    "web_hits": int,
    "trusted_source_count": int,
    "unique_domain_count": int,
    "research_round_count": int,
    "coverage_score": float,
    "stop_reason": str,
}
```

### 12.2 Quality metrics

```python
{
    "chapter_index": int,
    "quality_score": float,
    "review_passed": bool,
    "rewrite_used": bool,
    "blocking_issue_count": int,
}
```

### 12.3 Asset metrics

```python
{
    "mermaid_generated": int,
    "mermaid_fallback": int,
    "image_generated": int,
    "image_fallback": int,
    "interactive_generated": int,
}
```

### 12.4 前端等待态

`POST /knowledge/docs` 已返回 `build_preview` / `build_metrics`，后续不要新增 digest 专用 SSE，继续走轮询口径。

等待态建议展示：

- 当前阶段描述。
- 章节进度。
- 最新章节标题。
- 草稿摘录。
- 来源数量和可信来源数量。
- LLM 调用量和失败次数。
- 如果 search-only，明确提示“本轮主要基于联网研究”。

## 13. 分阶段实施计划

### Phase 0：合同修复与文档对齐

目标：消除最明显的可用性断裂。

任务：

- 修复 docs 构建按钮必须带 `confirmed_plan_id`。
- 无 confirmed plan 时引导用户进入 planner。
- 明确 graph-only 构建入口与 docs 构建入口。
- 统一 strict/fallback 策略。
- 更新相关测试。

验收：

- 从 BuildPlanPage 确认后可以正常触发 docs build。
- 从知识图谱侧不再错误触发 docs build。
- Mermaid fallback 测试与代码一致。
- Writer 主 LLM 失败仍会导致构建失败。

### Phase 1：标题和 Planner 失败降级

目标：非核心 LLM 失败不拖垮整单。

任务：

- `draft_plan` stream 失败返回 fallback plan。
- planner title generation 失败保留 provisional title。
- `finalize_titles` 单章失败使用 planner title。
- 状态中记录 fallback reason。

验收：

- Planner 主模型失败时仍返回一份可确认方案。
- DocGen 标题 LLM 失败时仍能继续写文档。
- 前端能看到 fallback 状态或最近事件。

### Phase 2：Research 调度收口

目标：提升 research 速度和来源质量。

任务：

- 把 DocGen 检索调度逐步迁到 `shared.infra.search` / `shared.infra.facade.research`。
- 保留本地资料优先。
- 引入 provider 并发与 RRF 融合。
- 保留现有 `research_rounds`、`retriever_stats` metadata。

验收：

- 本地命中足够时不查外网。
- 本地不足时外部 provider 并发。
- LangSmith 中能看到 configured / active retrievers。
- 常规章节 research 耗时下降。

### Phase 3：Evidence Ledger

目标：让文档有可审证据链。

任务：

- 在 research output 中生成 evidence ledger。
- 写入 chapter material metadata。
- publish manifest 中记录 evidence summary。
- Writer prompt 消费 evidence ledger。

验收：

- 每章至少有 local 或 web evidence。
- 来源不足时有明确 warning。
- 文档参考来源不再只是全局堆列表。

### Phase 4：Review / Rewrite

目标：提升章节质量稳定性。

任务：

- 新增 `review_chapters`。
- 新增 `rewrite_chapters`。
- 每章最多 rewrite 1 次。
- 增加质量评分 metadata。

验收：

- 低质量草稿会触发 rewrite。
- rewrite 后分数提升或记录保留原因。
- 总构建成本可控。

### Phase 5：Practice 接 Examine

目标：让知识文档接入诊断引擎。

任务：

- 构建 practice blueprint。
- 调 Examine question build。
- 失败时规则题兜底。
- practice metadata 写入 manifest。

验收：

- sprint 题目更偏题型和易错点。
- systematic 题目更偏理解、推理、迁移。
- Examine 失败不影响文档发布。

### Phase 6：Asset Manifest

目标：把媒体增强从 Markdown 占位升级为稳定资产系统。

任务：

- 新增 asset manifest。
- Mermaid / image / interactive 写入 manifest。
- 图片生成接 content store。
- 前端后续可按 manifest 渲染。

验收：

- 每个 asset 都有状态。
- 失败有 fallback reason。
- 文档导出可以降级。

### Phase 7：构建恢复与持久化缓存

目标：让长任务更可靠。

任务：

- Research / draft / review / asset 分阶段 staging。
- search / reader / compression 持久化缓存。
- 构建失败后保留可读中间态。
- 后续可做 resume。

验收：

- 后端崩溃后不丢全部中间结果。
- 前端能展示最近草稿和失败阶段。
- 重试构建能复用一部分缓存。

## 14. 优先级总表

| 优先级 | 事项 | 收益 | 风险 |
| --- | --- | --- | --- |
| P0 | 修 confirmed plan 构建入口 | 解决直接失败 | 低 |
| P0 | 统一 strict/fallback | 消除测试和文档冲突 | 低 |
| P0 | Planner/Title 非核心降级 | 长任务韧性提升 | 中 |
| P1 | Research 调度收口 | 速度和来源质量提升 | 中 |
| P1 | Evidence ledger | 降低幻觉、增强可信度 | 中 |
| P1 | Review / Rewrite | 文档质量稳定 | 中高 |
| P2 | Practice 接 Examine | 闭环学习价值提升 | 中 |
| P2 | Asset manifest | 前端/导出稳定 | 中 |
| P3 | Resume / persistent cache | 长任务可靠性 | 高 |

## 15. 不建议做的事

- 不要重新创建 `app.services` 或 `app.teaching`。
- 不要把 DocGen 逻辑迁回 API 层。
- 不要在 DocGen 内复制第二套 search provider 调度。
- 不要让每章 writer 各自决定全文结构。
- 不要在没有 evidence ledger 前强行做复杂 citation。
- 不要一开始就引入全链路多 agent，先把 research worker 做稳。
- 不要让图片生成成为核心链路阻塞点。

## 16. 最小落地顺序

如果只做一轮小而稳的改造，建议按下面顺序：

```text
1. 前端 docs 构建入口必须带 confirmed_plan_id
2. 修 strict/fallback 文档与测试
3. finalize_titles 单章 fallback
4. planner stream 失败返回 fallback plan
5. DocGen research 接入 shared search dispatch
6. 增加 chapter review metadata，但先不 rewrite
7. 再开启最多一次 rewrite
```

这组改动能最直接提升可用性和稳定性，而且不会破坏现有 graph 主线。

## 17. 验证清单

后端：

```text
conda activate atm
pytest backend/tests/test_docgen_strict_failures.py -q
pytest backend/tests/test_docgen_research_stack.py -q
pytest backend/tests/test_docgen_assets_and_practice.py -q
pytest backend/tests/test_knowledge_digest_service.py -q
pytest backend/tests/test_build_planner_service.py -q
pytest backend/tests/test_search_dispatch.py -q
```

前端：

```text
cd frontend
npm run build
```

人工回归：

- 从 planner 创建方案。
- 修改方案。
- 确认方案。
- 触发 docs build。
- 文档页等待态有持续更新。
- draft 可预览。
- completed 后 live 文档切换成功。
- graph-only build 不要求 confirmed plan。
- 无 confirmed plan 的 docs build 有明确引导。

## 18. 一句话总结

DocGen 的下一阶段不是“把 prompt 写狠一点”，而是把它建设成一个有合同、有研究计划、有证据账本、有质量门槛、有失败降级、有资产生命周期的教学文档生成链路。
