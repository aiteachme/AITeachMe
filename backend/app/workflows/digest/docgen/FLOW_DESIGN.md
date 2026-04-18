# DocGen 重构流程设计

最后更新：2026-04-18

这份文档只描述 `digest/docgen` 的目标流程。当前实现仍以 `README.md`、`graph.py` 和节点代码为准。

核心判断：

```text
Planner 定方向，DocGen 构建知识文档。
```

所以 DocGen 不是简单“按章写正文”，而是在现有流程上补强三件事：

- 建立整本文档的知识骨架。
- 显式记录主张、证据和冲突。
- 复核后按问题级别回流，而不是只做一次线性生成。

## 1. 推荐总流程

下面是目标流程。主干不变，只是在关键节点里补上知识骨架、主张证据和复核回流。

### 1.1 简化流程总览

这一节只保留流程结构和节点作用，不展开输入输出。详细合同继续保留在后面的完整流程里。

```text
load_context
  读取 confirmed plan、Planner 上下文、资料理解包和构建配置。

prepare_context
  ├─ enhance_plan_outline
  │    轻量增强用户确认过的章节，让粗颗粒大纲变成可执行小纲。
  ├─ infer_docgen_intent
  │    识别写作深度、考试倾向、例子偏好和避让项。
  └─ summarize_files
       总结文件、切片、章节亲和度和高置信证据。

merge_and_dispatch
  合并 prepare_context 的三路结果，生成章节任务、检索议程和初始预算。

build_document_backbone
  建立整本文档的术语、概念依赖、核心主张和易混点骨架。

generate_draft
  ├─ generate_chapter 1
  ├─ generate_chapter 2
  └─ generate_chapter N
       按章并行执行动态检索、网页打开、本地资料读取、证据抽取和草稿生成。

enhance
  ├─ enhance_chapter 1
  ├─ enhance_chapter 2
  └─ enhance_chapter N
       按章并行处理 Mermaid、图片占位、交互块、公式清洗和本章自检。

review_content
  ├─ review_chapter 1
  ├─ review_chapter 2
  ├─ review_chapter N
  └─ document_consistency_review
       复核单章覆盖、证据支撑、章节边界和整本文档一致性。

repair_or_route
  ├─ no_action
  ├─ apply_patch
  ├─ regenerate_chapter
  └─ record_only
       根据复核结果决定直接通过、局部 patch、重写问题章节或只记录 unresolved warning。

merge_review
  合并章节，做发布前完整性检查和 manifest 收口。

final_merge_patch
  可选，只修合并后才暴露的小问题，例如重复摘要、跨章过渡、manifest 缺字段。

finalize_titles
  统一标题表达。

publish_document
  发布章节 Markdown、整本 Markdown、manifest、数据库记录和版本归档。
```

简化理解：

```text
Planner 定方向
  -> DocGen 准备上下文（三路并行）
  -> 建整本知识骨架
  -> 按章研究和写草稿（章节并行）
  -> 表现层增强（章节并行）
  -> 复核
  -> 有限 patch / 重写 / 记录
  -> 再复核
  -> 合并、标题收口、发布
```

### 1.2 完整输入输出流程

这一节是 DocGen 的完整执行合同。这里写的是 workflow state 层面的输入输出，不是 HTTP API schema；真实字段以 `state.py`、`lib/models.py` 和各节点返回值为准。

```text
load_context
  输入：
    - confirmed_plan：用户确认后的构建合同，包含 user_goal、digest_mode、chapter_plan、plan_summary、plan_steps、planner_context。
    - shared_inputs：资料理解包；如果上游没传入，则根据 subject / file_ids / user_prompt 重新准备。
    - file_ids / user_prompt / planner_session_id / confirmed_plan_id：构建入口补充信息。
  处理：
    - 校验 confirmed_plan，拒绝没有章节合同的构建。
    - 解析 digest_mode、course_type、retrieval_profile。
    - 从 confirmed plan 固化 Planner 上下文，不在 DocGen 重新决定模式。
    - 生成 document_context 和 DocGenContext，给后续写作、发布、manifest 共用。
  输出：
    - shared_inputs / raw_chunks / subject_profile
    - confirmed_plan
    - chapter_assignments
    - docgen_context
    - document_context
    - digest_mode / course_type / retrieval_profile

prepare_context
  并行子任务：
    ├─ enhance_plan_outline
    ├─ infer_docgen_intent
    └─ summarize_files
  输入：
    - docgen_context：主题、目标、模式、Planner 摘要、历史修改、资料统计。
    - confirmed_plan / chapter_assignments：用户确认过的章节合同。
    - shared_inputs：source_packets、section_packets、material_profile。
  处理：
    - enhance_plan_outline：把用户确认的大纲增强成执行级小纲，但不新增、不删除、不重排章节。
    - infer_docgen_intent：识别深度、考试倾向、例子偏好、定义粒度和避让项。
    - summarize_files：总结文件，推断章节亲和度，抽取高置信证据候选。
  输出：
    - enhanced_chapter_outlines
    - intent_profile
    - file_summaries
    - source_affinity_by_chapter
    - high_confidence_evidence_units
    - plan_mismatch_warnings

merge_and_dispatch
  当前代码节点：confirm_and_dispatch
  输入：
    - docgen_context
    - enhanced_chapter_outlines
    - intent_profile
    - file_summaries
    - source_affinity_by_chapter
    - high_confidence_evidence_units
    - chapter_assignments
    - plan_mismatch_warnings
  处理：
    - 合并 prepare_context 的三路结果。
    - 先生成 ChapterGenerationPlanSeed / ChapterGenerationTaskSeed。
    - 生成 backbone_research_agenda，给整本知识骨架使用。
    - 同时保留兼容的 ChapterGenerationPlan / ChapterGenerationTask，便于章节 fan-out。
  输出：
    - chapter_generation_plan_seed
    - chapter_task_seeds
    - backbone_research_agenda
    - chapter_generation_plan
    - chapter_tasks

build_document_backbone
  输入：
    - chapter_generation_plan_seed / chapter_task_seeds
    - backbone_research_agenda
    - file_summaries
    - high_confidence_evidence_units
  处理：
    - 构建整本文档的术语表、概念依赖、符号表、核心主张池和易混点。
    - 如果模型或资料不足，fallback 为基于章节 seed 的弱骨架。
    - 将 backbone 回填到章节任务，形成最终执行合同。
  输出：
    - document_backbone
    - chapter_generation_plan
    - chapter_tasks
    - backbone_conflict_warnings

generate_draft
  当前代码节点：generate_chapters（LangGraph Send x N）
  并行子任务：
    ├─ generate_chapter 1
    ├─ generate_chapter 2
    └─ generate_chapter N
  输入：
    - 单章 chapter_task
    - total_chapters
    - shared_inputs.section_packets
    - docgen_context
    - document_backbone
    - digest_mode / course_type / retrieval_profile
  处理：
    - retrieve_for_chapter：按动态预算执行本地 RAG、外部检索和 gap queries。
    - read_and_compress：打开网页、读取本地切片、压缩成 dense_context；不能只拿搜索标题写正文。
    - extract_claims：结合 ChapterGenerationTask 和 DocumentBackbone 生成 ClaimLedger。
    - align_evidence：把 ClaimLedger 映射到 EvidenceLedger。
    - resolve_conflicts：记录定义、符号、来源口径和例子冲突。
    - draft_chapter：基于 dense_context、claim/evidence 和冲突处理结果写章节草稿。
    - critic/rewrite：当前代码仍在单章内做轻量 critic 和最多一次 rewrite；目标上应逐步前移到 review_content。
  输出：
    - chapter_drafts
    - research_traces
    - evidence_ledgers
    - claim_ledgers
    - claim_evidence_maps
    - conflict_reports
    - research_sources
    - research_ms / draft_ms / llm_calls_total

enhance
  当前代码节点：enhance_chapters
  并行子任务：
    ├─ enhance_chapter 1
    ├─ enhance_chapter 2
    └─ enhance_chapter N
  输入：
    - chapter_drafts
    - claim_ledgers
    - document_backbone
    - digest_mode
    - asset settings
  处理：
    - 只处理表现层：Mermaid、图片请求、交互占位、公式清洗、Markdown 结构和本章自检。
    - 自检题从 ClaimLedger / ConfusionMap 派生。
    - 图片模型未启用时要降级并写入 asset manifest，不泄露内部占位符。
  输出：
    - enhanced_chapter_drafts
    - asset_manifests
    - practice_manifests
    - enhance_ms

review_content
  并行/串行组合：
    ├─ review_chapter 1
    ├─ review_chapter 2
    ├─ review_chapter N
    └─ document_consistency_review
  输入：
    - enhanced_chapter_drafts
    - chapter_tasks
    - document_backbone
    - claim_ledgers
    - claim_evidence_maps
    - conflict_reports
    - intent_profile
  处理：
    - review_chapter：检查合同覆盖、证据支撑、章节边界、质量信号和风险。
    - document_consistency_review：检查跨章术语、符号、前置关系、重复和风格一致性。
    - 只做判断，不检索、不打开网页、不调工具、不改正文。
  输出：
    - reviewed_chapter_drafts
    - chapter_review_reports
    - document_consistency_report
    - review_actions
    - review_decision（目标字段：good / needs_repair / publish_with_warnings / fail）

repair_or_route
  输入：
    - reviewed_chapter_drafts
    - enhanced_chapter_drafts
    - chapter_tasks
    - document_backbone
    - review_actions
    - repair_loop_state（目标字段）
  处理：
    - no_action：无需修补，进入 merge_review。
    - apply_patch：执行 surface_patch / section_patch，局部修改章节。
    - evidence_patch：针对缺口补检索、打开网页、补证据，再做局部改写。
    - regenerate_chapter：只重写问题章节，并重新经过 enhance 和 review_content。
    - record_only：超过预算、证据不足或会推翻 confirmed plan 时只记录 warning。
    - 最多两轮，每轮后必须回到 review_content。
  输出：
    - reviewed_chapter_drafts
    - enhanced_chapter_drafts（目标：patch 后同步）
    - review_actions
    - unresolved_warnings
    - repair_loop_state（目标字段）
    - repair_trace（目标字段）

merge_review
  输入：
    - reviewed_chapter_drafts；如果为空，fallback 使用 enhanced_chapter_drafts。
    - chapter_generation_plan
    - document_backbone
    - claim_ledgers / claim_evidence_maps / conflict_reports
    - chapter_review_reports
    - document_consistency_report
    - review_actions / unresolved_warnings
  处理：
    - 按 chapter_index 去重和排序。
    - 构造 chapter_metadatas，收口章节 manifest 字段。
    - 合并整本 Markdown，并做发布前完整性检查。
  输出：
    - chapter_metadatas
    - merged_markdown
    - enriched_markdown
    - merge_review_report
    - merge_review_ms

final_merge_patch
  当前状态：目标节点，当前代码尚未独立实现。
  输入：
    - merged_markdown
    - chapter_metadatas
    - merge_review_report
    - unresolved_warnings
  处理：
    - 只修合并后才暴露的小问题，例如目录重复、跨章过渡、重复摘要、manifest 缺字段。
    - 不重新检索，不重写章节，不改变 claim/evidence。
  输出：
    - merged_markdown
    - chapter_metadatas
    - final_merge_patch_report

finalize_titles
  输入：
    - chapter_metadatas
    - chapter_assignments
    - merged_markdown
    - merge_review_report
  处理：
    - 统一标题表达。
    - 保持 chapter_index 和 confirmed plan 映射，不推翻用户确认语义。
    - 重新生成整本 merged_markdown。
  输出：
    - chapter_metadatas
    - merged_markdown
    - enriched_markdown
    - final_chapter_titles
    - title_review_report
    - finalize_ms

publish_document
  输入：
    - chapter_metadatas
    - chapter_assignments
    - document_context
    - merged_markdown
    - docgen_artifacts
  处理：
    - 写入 _build 章节 Markdown、_build merged Markdown 和 _build docgen_manifest。
    - 发布当前章节 Markdown、merged_knowledge_base.md、版本归档、docgen_manifest.json。
    - 写入 KnowledgeDoc rows、知识文档 manifest 和构建状态。
  输出：
    - doc_ids
    - built_paths
    - merged_markdown
    - user_prompt
    - finalize_ms
```

`docgen_artifacts` 至少保留：

```text
docgen_context
intent_profile
file_summaries
source_affinity_by_chapter
high_confidence_evidence_units
chapter_generation_plan_seed
chapter_task_seeds
backbone_research_agenda
document_backbone_snapshot
backbone_conflict_warnings
chapter_generation_plan
chapter_drafts
enhanced_chapter_drafts
reviewed_chapter_drafts
research_traces
evidence_ledgers
claim_ledgers
claim_evidence_maps
conflict_reports
chapter_review_reports
document_consistency_report
review_actions
unresolved_warnings
asset_manifest
practice_manifest
merge_review_report
final_chapter_titles
title_review_report
```

### 1.3 有限迭代回流设计

这一节描述目标设计，不要求完全兼容当前实现。当前代码已经有 `review_content`、`repair_or_route`、`review_actions`、`unresolved_warnings`、章节检索 runtime 和网页打开链路，但 graph 仍是 `review_content -> repair_or_route -> merge_review` 的一次性路径。下一步重构要把它改成“复核判定 -> 最多两轮修补 -> 再复核”的闭环。

推荐主流程：

```text
load_context
  -> prepare_context
  -> merge_and_dispatch
  -> build_document_backbone
  -> generate_draft
  -> enhance
  -> review_content
       ├─ good
       │    -> merge_review
       │    -> final_merge_patch(optional)
       │    -> final_consistency_review(readonly)
       │    -> finalize_titles
       │    -> publish_document
       └─ needs_repair
            -> repair_or_route
                 ├─ no_action
                 ├─ apply_patch
                 ├─ evidence_patch
                 ├─ regenerate_chapter
                 └─ record_only
            -> review_content
```

这里的循环只发生在 `review_content <-> repair_or_route` 之间，最多两轮。`review_content` 是唯一质量判定关口；`repair_or_route` 是唯一执行修补、补检索、重写或记录 warning 的节点。这样做可以避免每个节点都自行判断“要不要再修一次”，也避免变成不可控的多 Agent 循环。

节点能力边界：

```text
generate_draft
  当前/目标能力：
    - 按章并行执行本地 RAG、文件切片读取、外部检索、网页打开、正文压缩。
    - 根据 confirmed plan、digest_mode、planner_context 和章节缺口决定检索重点和写作表达。
    - 生成 dense_context、research_trace、evidence_ledger、claim_ledger、conflict_report 和章节草稿。
  可以调用工具：
    - 可以使用 shared.infra.search、web_reading.read_urls、ContextCompressor、SourceCurator。
    - 后续可接 tool tags，但工具结果必须进入 trace 和 evidence，再给 writer 使用。
  不能做：
    - 不能修改 confirmed plan 的章节数量、顺序和用户确认语义。
    - 不能做标题最终收口。

enhance
  当前/目标能力：
    - 按章并行处理 Mermaid、图片请求、交互占位、公式清洗、Markdown 结构和本章自检。
    - 根据 asset settings、digest_mode 和章节合同决定图示、练习和表现层策略。
  可以调用工具：
    - 可以调用 Mermaid / image / markdown / latex / teaching block 这类表现层工具。
    - 如果图片或图示需要额外事实支撑，不能在 enhance 里直接补新知识；应生成 warning 或交给 repair_or_route 的 evidence_patch。
  不能做：
    - 不能引入新的核心定义、结论、例题口径或证据主张。
    - 不能改变 claim / evidence 的对应关系。

review_content
  当前/目标能力：
    - 逐章复核合同覆盖、证据支撑、章节边界、质量信号。
    - 再做整本文档一致性检查：术语、符号、前置关系、重复和风格。
    - 产出 ReviewAction、DocumentConsistencyReport 和是否继续修补的判定。
  只能使用：
    - LLM 复核、规则检查、DocumentBackbone、ClaimLedger、EvidenceLedger、ConflictReport。
  不能做：
    - 不检索、不打开网页、不调工具、不改正文。
    - 不直接 patch，因为它要保持“裁判”角色。

repair_or_route
  目标能力：
    - 读取 ReviewAction，按严重度决定 no_action、apply_patch、evidence_patch、regenerate_chapter 或 record_only。
    - 可以补检索、打开网页、调用工具，但动作必须写入 repair_trace。
    - 每次执行后回到 review_content，由复核节点重新判定。
  不能做：
    - 不能无限循环。
    - 不能静默推翻 confirmed plan。
    - 不能在没有本地资料、已打开网页正文或明确 snippet fallback 的情况下补新断言。
```

DocGen 不再保留独立 prompt 扩展层。策略来源只保留四类：

- `confirmed plan`：用户确认过的目标、模式、章节和约束。
- `planner_context`：Planner 过程中的计划摘要、计划步骤、修订记录和用户反馈。
- `digest_mode` / `retrieval_profile`：决定速成课或系统课的检索深度、章节密度和写作风格。
- `review_actions`：复核阶段发现的具体缺口和修补动作。

运行时工具统一走 `shared.infra.tools`、`shared.infra.search`、`shared.infra.tools.builtin.*` 等基础能力。是否调用工具只由 workflow 节点显式决定，不能再通过外置 prompt 片段绕过状态机。

建议新增一个显式的回流状态：

```text
RepairLoopState
  repair_round_total：整轮 repair 次数，最大 2
  chapter_patch_rounds：每章 patch 次数
  chapter_regenerate_rounds：每章重写次数
  evidence_patch_rounds：每章补证据次数
  last_review_decision：good / needs_repair / publish_with_warnings / fail
  repair_trace：每次执行了什么、用了什么工具、补了哪些来源、哪些动作被降级记录
```

`ReviewAction` 建议扩展成能直接驱动修补的结构，而不是只有一段 reason：

```text
ReviewAction
  action_id：稳定 ID
  action_type：surface_patch / section_patch / evidence_patch / regenerate_chapter / re_dispatch / rebuild_backbone
  chapter_index：目标章节；整本问题为空
  severity：info / warning / error
  reason：为什么需要处理
  target_anchor：标题、小节名、claim_id、evidence_id、asset_id 或文本锚点
  instruction：要改什么
  constraints：不能改什么
  expected_effect：修完后应满足的检查点
  status：recorded / applied / skipped / downgraded
```

修补动作分层：

- `no_action`：复核通过，不进入 repair，直接合并。
- `surface_patch`：自动执行，修标题层级、过渡句、重复句、Markdown 轻微问题。
- `section_patch`：谨慎执行，只改局部小节；不得改变章节边界、核心定义和 claim/evidence。
- `evidence_patch`：允许针对缺口补检索、打开网页、压缩正文、补证据，再做局部改写；必须记录新来源、read_url_count、snippet fallback。
- `regenerate_chapter`：只重写问题章节。重写后必须重新经过 enhance 和 review_content；不影响其他章节。
- `record_only`：问题太大、证据不足、会推翻 confirmed plan 或超过预算时，只写入 unresolved warning。
- `re_dispatch` / `rebuild_backbone`：第一版只记录，不自动执行；后续如果支持，也必须重新进入明确的计划确认或全局重建流程。

推荐的两轮上限：

```text
repair_round_total <= 2
chapter_patch_round_per_chapter <= 2
chapter_regenerate_round_per_chapter <= 1
evidence_patch_round_per_chapter <= 1
final_merge_patch_round <= 1
```

实际路由建议：

```text
review_content
  ├─ no blocking action
  │    -> merge_review
  ├─ has actionable repair and repair_round_total < 2
  │    -> repair_or_route
  │         ├─ surface/section patch
  │         │    -> update reviewed/enhanced chapter draft
  │         ├─ evidence_patch
  │         │    -> targeted retrieval/read_urls/compress
  │         │    -> update evidence ledger and local section
  │         ├─ regenerate_chapter
  │         │    -> regenerate only failed chapters
  │         │    -> enhance regenerated chapters
  │         └─ record_only
  │              -> append unresolved_warnings
  │    -> review_content
  └─ repair budget exhausted
       -> merge_review with unresolved_warnings
```

`merge_review` 之后只允许非常小的整本修补：

- `merge_review` 负责合并章节、检查章节数量、manifest 完整性、来源覆盖和整本文档结构。
- `final_merge_patch` 只修合并后才暴露的小问题，例如目录重复、跨章过渡缺失、重复摘要、manifest 缺字段。
- `final_consistency_review` 是只读复核，不再检索、不再打开网页、不再重写章节。
- `finalize_titles` 只执行一次，放在所有 patch 和最终一致性复核之后；不要做 `finalize_titles -> finalize_titles`。

第一版可落地策略：

```text
1. graph 增加 route_after_review，根据 ReviewAction 和 RepairLoopState 决定去 repair_or_route 还是 merge_review。
2. repair_or_route 先支持 surface_patch / section_patch / record_only，并记录 repair_trace。
3. evidence_patch 复用 DocGenChapterContextRuntime，只做定向补证据，不重新跑整章研究。
4. regenerate_chapter 复用 generate_chapters + enhance_chapters 的单章能力，只替换目标章节。
5. 两轮后仍未解决的问题写入 unresolved_warnings、review_actions、docgen_manifest。
```

## 2. 当前实现映射

当前 graph：

```text
load_context
  -> prepare_parallel_inputs
  -> confirm_and_dispatch
  -> build_document_backbone
  -> generate_chapters (Send x N)
  -> enhance_chapters
  -> review_content
  -> repair_or_route
  -> merge_review
  -> finalize_titles
  -> publish_document
```

目标映射：

| 目标阶段 | 当前对应 | 状态 |
| --- | --- | --- |
| `load_context` | `load_context` | 已落地 |
| `prepare_context.enhance_plan_outline` | `prepare_parallel_inputs` 内部 | 已落地，保持轻量 grounding |
| `prepare_context.infer_docgen_intent` | `prepare_parallel_inputs` 内部 | 已落地 |
| `prepare_context.summarize_files` | `prepare_parallel_inputs` 内部 | 已落地，已输出 evidence candidates |
| `merge_and_dispatch` | `confirm_and_dispatch` | 已落地，已输出 plan seed 和 backbone agenda |
| `build_document_backbone` | `build_document_backbone` | 已落地，含 fallback backbone |
| `generate_draft` | `generate_chapters` | 已落地，已输出 trace / evidence / claim / conflict |
| `enhance` | `enhance_chapters` | 已落地，需限制为表现层 |
| `review_content.review_chapter` | `review_content` 内部 | 已落地；writer 内轻量 critic 仍需逐步降权 |
| `review_content.document_consistency_review` | `review_content` 内部 | 已落地 |
| `repair_or_route` | `repair_or_route` | 已落地 MVP：安全 surface patch + record_only；待补两轮路由 |
| `merge_review` | `merge_review` | 已落地，后续只做收口 |
| `final_merge_patch` | 无 | 待新增，只处理合并后小问题 |
| `finalize_titles` | `finalize_titles` | 已落地，标题最终收口 |
| `publish_document` | `publish_document` | 已落地，已写 docgen_artifacts manifest |

## 3. 下一步落地顺序

当前主干节点已经接近目标流程，后续不要再按“补节点”思路推进，而要补清楚预算、回流和产物合同。

### Phase 1：动态研究预算

```text
1. 新增 ResearchBudgetDecision，按本地资料覆盖度、章节缺口、digest_mode 决定检索轮数、query 数和打开 URL 数。
2. merge_and_dispatch 或 build_document_backbone 负责生成每章预算，代码再按 settings 上限 clamp。
3. generate_chapters 消费 task.budget_policy，不再只靠固定 sprint/systematic 默认值。
4. research_trace 明确记录 search result、opened url、read success/failure 和 snippet fallback。
```

### Phase 2：两轮 repair loop

```text
1. state.py 增加 repair_loop_state / repair_trace。
2. graph.py 增加 route_after_review：good -> merge_review，needs_repair -> repair_or_route。
3. repair_or_route 支持 surface_patch / section_patch / record_only，先不做无限回流。
4. evidence_patch 复用 DocGenChapterContextRuntime 做定向补证据。
5. regenerate_chapter 只替换问题章节，并重新 enhance -> review_content。
```

### Phase 3：资产占位状态收口

```text
1. 保留 atm-docgen-internal-asset-request-v1，writer 只能写内部请求，不直接泄露占位符。
2. Mermaid 继续在 enhance 阶段生成或 fallback。
3. Image 明确 generated / disabled / failed / skipped 状态，写入 AssetManifest。
4. models.image_generation 未配置时移除图片请求，但 manifest 必须记录 disabled。
```

### Phase 4：final_merge_patch

```text
1. 新增 final_merge_patch 节点或 lib 函数，只修合并后小问题。
2. 不检索、不重写章节、不改 claim/evidence。
3. 修完后进入 finalize_titles，finalize_titles 仍只执行一次。
```

### Phase 5：发布 manifest 和文档同步

```text
1. docgen_manifest 保留 planner_artifacts、repair_loop_state、repair_trace、final_merge_patch_report。
2. README.md 同步当前 graph，避免继续显示旧线性流程。
3. 关键合同补测试：动态预算、review 路由、图片 disabled manifest、发布产物。
```

## 4. 近期不要做

- 不把 DocGen 改成完整多 Agent 动态队列。
- 不让 DocGen 自动推翻 confirmed plan。
- 不一上来做无限递归 deep research。
- 不让 enhance 修核心知识逻辑。
- 不新建第二套 search/tool registry。
- 不把所有原文一次性塞进 writer prompt。

## 5. 一句话收束

```text
DocGen 的核心不是把章节写出来，
而是在既有流程上补上知识骨架、主张证据、冲突消解和一致性复核，
让最终文档可读、可追溯、可复核。
```
