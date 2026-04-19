# DocGen 流程设计

最后更新：2026-04-19

这份文档描述 `digest/docgen` 的目标流程、当前实现映射和后续演进约束。当前实现以 `graph.py`、`state.py`、`nodes/`、`lib/models.py` 为准；本文用于解释节点边界、输入输出合同和后续重构方向。

## 0. 文档维护硬约束

`FLOW_DESIGN.md` 必须长期同时保留两类流程说明：

- **短流程总览**：快速看懂所有节点、并行关系、fan-out/fan-in、流水线顺序和每个节点作用。
- **长流程执行合同**：逐节点写清输入、输出、作用、内部步骤和约束，作为后续实现和重构的详细合同。

后续任何人改 DocGen 流程时，必须同时更新短流程和长流程。不能只改代码映射表，也不能只改长流程。

如果目标阶段名和当前代码节点名不一致，必须显式写出映射，例如：

```text
prepare_context / 当前 prepare_parallel_inputs
merge_and_dispatch / 当前 confirm_and_dispatch
generate_draft / 当前 generate_chapters
enhance / 当前 enhance_chapters
```

核心判断：

```text
Planner 定方向，DocGen 构建知识文档。
```

DocGen 不是“重新想一个大纲再写全文”，而是消费用户确认过的 `confirmed_plan`，在不推翻用户确认语义的前提下完成：

- 章节执行合同细化。
- 整本文档知识骨架构建。
- 单章研究、证据、主张、冲突记录。
- 表现层增强。
- 内容复核、有限回流和发布级 manifest。

## 1. 流程总览与执行合同

### 1.1 短流程总览

这一节面向快速阅读，必须写清所有节点、并行关系、fan-out/fan-in、流水线关系和节点作用。字段级输入输出放在 `1.2 长流程执行合同`。

```text
load_context
  读取 confirmed plan、资料理解包、Planner 上下文和构建入口参数。
  校验用户已经确认章节合同，生成 DocGen 全局上下文、章节 assignment 和发布上下文。
  |
  v
prepare_context / 当前 prepare_parallel_inputs
  并行准备写作上下文：
    ├─ enhance_plan_outline
    │    把用户确认的大纲增强成执行级小纲，不新增、不删除、不重排章节。
    ├─ infer_docgen_intent
    │    识别讲解深度、考试倾向、例子偏好、定义粒度和避让项。
    └─ summarize_files
         摘要文件、判断章节亲和度、抽取高置信证据候选。
  三路结果 fan-in 后进入派发阶段。
  |
  v
confirm_and_dispatch
  合并 prepare_context 的三路结果。
  生成 ChapterGenerationPlanSeed、ChapterGenerationTaskSeed 和 backbone_research_agenda。
  同时生成当前章节 fan-out 使用的 ChapterGenerationPlan / ChapterGenerationTask。
  |
  v
build_document_backbone
  基于章节 seed、资料摘要和证据候选，构建整本文档知识骨架。
  统一术语、概念依赖、符号、核心主张和易混点，并回填每章最终执行合同。
  |
  v
generate_chapters
  按章节 fan-out：
    ├─ generate_chapter 1
    ├─ generate_chapter 2
    └─ generate_chapter N
  每章独立执行检索、网页/本地资料读取、上下文压缩、claim/evidence/conflict 和正文草稿写作。
  所有章节草稿 fan-in 为 chapter_drafts、research_traces、claim/evidence/conflict ledgers。
  |
  v
enhance_chapters
  按章并行增强：
    ├─ enhance_chapter 1
    ├─ enhance_chapter 2
    └─ enhance_chapter N
  处理 Mermaid、image、interactive、公式清洗、Markdown 结构和本章自检题。
  增强稿 fan-in 为 enhanced_chapter_drafts、asset_manifests、practice_manifests。
  |
  v
review_content / 当前 review_chapter Send x N + document_consistency_review
  按章并行复核：
    ├─ review_chapter 1
    ├─ review_chapter 2
    └─ review_chapter N
  然后执行 document_consistency_review。
  章节复核使用 LLM 结构化 review + 规则 guardrail，整本复核检查术语、符号、章节数、重复和风格一致性。
  输出 reviewed drafts、chapter review reports、document consistency report、review actions 和 review decision。
  |
  v
repair_or_route
  当前实现：对 surface_patch / section_patch 执行局部 Markdown patch；对 evidence_patch / regenerate_chapter / re_dispatch / rebuild_backbone 等重动作结构化记录。
  当前流水线：review_content -> repair_or_route -> merge_review。
  目标流水线：review_content <-> repair_or_route，最多两轮有限闭环。
  |
  v
merge_review
  reviewed drafts fan-in 后按 chapter_index 去重、排序、收口 chapter metadata。
  合并整本 Markdown，生成 merge review report，做发布前完整性检查。
  |
  v
final_merge_patch
  目标节点，当前尚未独立实现。
  只修合并后才暴露的小问题，例如目录重复、跨章过渡、重复摘要、manifest 缺字段。
  不重新检索，不重写章节，不改变 claim/evidence。
  |
  v
finalize_titles
  LLM 复核最终章节标题，保持 chapter_index 和 confirmed plan 语义映射。
  同步改写每章 Markdown 一级标题，并重新生成整本 Markdown。
  |
  v
publish_document
  发布章节 Markdown、整本 Markdown、docgen_manifest.json、版本归档和 KnowledgeDoc rows。
  同时写入构建状态、manifest 和可供 Interact / Examine / Profile 复用的 DocGen artifacts。
```

并行与 fan-in/fan-out 关系摘要：

```text
prepare_context
  enhance_plan_outline ┐
  infer_docgen_intent  ├─ fan-in -> merge_and_dispatch
  summarize_files      ┘

generate_draft
  generate_chapter 1 ┐
  generate_chapter 2 ├─ fan-in -> enhance
  generate_chapter N ┘

enhance
  enhance_chapter 1 ┐
  enhance_chapter 2 ├─ fan-in -> review_content
  enhance_chapter N ┘

review_content
  review_chapter 1 ┐
  review_chapter 2 ├─ fan-in -> document_consistency_review -> repair_or_route
  review_chapter N ┘

repair_or_route
  当前：review_content -> repair_or_route -> merge_review
  目标：review_content <-> repair_or_route，最多两轮，然后进入 merge_review
```

### 1.2 长流程执行合同

这一节是 DocGen 的详细执行合同。字段以当前 state/model 为准，已经删掉长期为空或不生效的 Planner 伪字段。

```text
load_context
  输入：confirmed_plan / shared_inputs / planner_context
    - confirmed_plan：用户确认后的构建合同，包含章节、模式、目标、约束。
    - shared_inputs：资料理解包，包含文件、切片、画像、统计、资产索引。
    - planner_context：confirmed_plan 中固化的 Planner 会话摘要和修改意见。
  输出：confirmed_plan payload / shared_inputs / DocGenContext / chapter_assignments / document_context
    - confirmed_plan payload：用户确认语义的冻结快照，不允许静默漂移。
    - shared_inputs：DocGen 的资料包，负责说明“从哪里找材料”。
    - DocGenContext：DocGen 全局运行上下文。
    - chapter_assignments：confirmed plan 章节转成的执行章节列表。
    - document_context：发布和写作共用的文档级上下文。
  作用：确认用户已确认的章节合同，补齐资料上下文、模式和构建状态。

prepare_parallel_inputs
  ├─ enhance_plan_outline
  │    输入：chapter_assignments / material_stats_profile / material_sections / planner_context
  │      - chapter_assignments：用户确认的章节列表。
  │      - material_stats_profile：资料类型、题目密度、公式密度、学科画像等统计；当前主要来自 shared_inputs.material_profile。
  │      - material_sections：切片级正文，可抽取高信息密度片段；当前主要来自 shared_inputs.section_packets。
  │      - planner_context：Planner 会话摘要、修改意见和用户确认上下文。
  │    输出：EnhancedChapterOutline[] / plan_mismatch_warnings[]
  │      - EnhancedChapterOutline：每章执行级小纲和重点目标。
  │      - plan_mismatch_warnings：模型输出和 confirmed plan 不一致时的 warning。
  │    作用：执行级细化章节，不新增、不删除、不重排 confirmed plan。
  │    注意：这里只做轻量 grounding，不做完整 Web research。
  ├─ infer_docgen_intent
  │    输入：user_prompt / plan_summary / digest_mode / chapter_assignments / docgen_history_brief
  │      - user_prompt：用户最终学习提示。
  │      - plan_summary：Planner 生成的方案摘要。
  │      - digest_mode：sprint 或 systematic。
  │      - chapter_assignments：用户确认章节列表。
  │      - docgen_history_brief：和文档生成有关的历史修改摘要。
  │    输出：DocGenIntentProfile
  │      - depth_level：讲解深度。
  │      - example_preference：定义优先、例题优先、比喻优先等偏好。
  │      - exam_orientation：考试导向强弱。
  │      - derivation_tolerance：目标字段，是否允许详细推导；当前代码用 explanation_depth / definition_depth 等字段近似表达。
  │      - redundancy_tolerance：目标字段，是否允许重复强调；当前代码用 review_orientation / chapter_style_hints 等字段近似表达。
  │      - avoidance_rules：目标字段，尽量不写或不能写的内容；当前代码对应 avoid_list。
  │    作用：识别写作深度、考试倾向、例子偏好、定义粒度、避让项。
  └─ summarize_files
       输入：source_packets / section_packets / chapter_assignments
         - source_packets：文件级正文包。
         - section_packets：切片级正文包。
         - chapter_assignments：章节目标，用于判断文件和章节亲和度。
       输出：FileMaterialSummary[] / source_affinity_by_chapter / high_confidence_evidence_units
         - FileMaterialSummary：文件摘要、核心概念、公式、例题、高价值 section、章节亲和度。
         - source_affinity_by_chapter：每章优先使用哪些文件和切片。
         - high_confidence_evidence_units：高置信证据单元。
       作用：为章节生成提供文件摘要、章节亲和度、高价值 section 和候选证据。

confirm_and_dispatch
  输入：EnhancedChapterOutline[] / DocGenIntentProfile / FileMaterialSummary[] / source_affinity_by_chapter / high_confidence_evidence_units / chapter_assignments
  输出：ChapterGenerationPlanSeed / ChapterGenerationTaskSeed[] / backbone_research_agenda
    - ChapterGenerationPlanSeed：整轮写作规则、格式、预算、章节任务初稿。
    - ChapterGenerationTaskSeed：单章执行合同初稿。
    - backbone_research_agenda：构建全局知识骨架需要优先检索和打开的主题、切片、证据方向。
  作用：合并 prepare_context 的多路结果，先形成章节研究范围和全局检索议程。
  每个 ChapterGenerationTaskSeed 至少包含：
    - chapter_index / confirmed_title / enhanced_title / chapter_goal / mode
    - required_elements / forbidden_scope
    - retrieval_queries / priority_section_refs / preferred_sources / fallback_policy
    - target_length / style_rules / citation_policy / uncertainty_policy / allowed_assets
  当前实现补充：
    - 同时生成章节 fan-out 使用的 ChapterGenerationPlan / ChapterGenerationTask。
    - 当前代码节点名为 confirm_and_dispatch。

build_document_backbone
  输入：ChapterGenerationPlanSeed / ChapterGenerationTaskSeed[] / shared_inputs / high_confidence_evidence_units / backbone_research_agenda
  输出：DocumentBackbone / ChapterGenerationPlan / ChapterGenerationTask[] / backbone_conflict_warnings
    - DocumentBackbone：整本文档的全局知识骨架。
    - ChapterGenerationPlan：吸收 backbone 后的最终整轮执行计划。
    - ChapterGenerationTask：吸收 backbone 后的最终单章执行合同。
    - backbone_conflict_warnings：全局术语、定义、符号或来源冲突 warning。
  作用：在初版章节研究范围上做全局证据采样和统一建模，再回填每章合同。
  DocumentBackbone 包含：
    - CanonicalGlossary：全局术语表，统一术语、别名、定义。
    - ConceptDependencyGraph：概念依赖图，约束前置关系。
    - NotationRegistry：符号和记号规范。
    - CanonicalClaimPool：整本文档必须讲清的核心主张池。
    - ConfusionMap：易混点、误区和边界。
  回填到 ChapterGenerationTask 的字段：
    - dependency_refs / forward_refs
    - claim_targets / concept_targets / confusion_targets
    - coverage_threshold / evidence_support_threshold / repetition_tolerance / patch_tolerance

generate_chapters
  ├─ generate_chapter 1
  ├─ generate_chapter 2
  └─ generate_chapter N
  输入：单章 ChapterGenerationTask / shared_inputs / DocumentBackbone / DocGenContext / retrieval_profile
  输出：ChapterDraft[] / ChapterResearchTrace[] / ClaimLedger[] / ClaimEvidenceMap[] / EvidenceLedger[] / ConflictReport[]
    - ChapterDraft：章节初稿、摘要草稿、占位符、质量信号。
    - ChapterResearchTrace：检索轮次、执行 query、打开上下文、覆盖率。
    - ClaimLedger：本章主张账本，列出本章必须讲清的话。
    - ClaimEvidenceMap：主张和证据的映射。
    - EvidenceLedger：可追溯证据单元。
    - ConflictReport：定义、符号、来源或例子冲突记录。
  作用：每章执行研究、主张抽取、证据对齐、冲突消解和正文草稿生成。
  generate_chapter 内部步骤：
    1. retrieve_for_chapter：取 retrieval_queries / priority_section_refs，先本地，资料不足时外部补洞。
    2. compress_context：读取命中内容并压缩为 dense_context，同时抽取 evidence_units。
    3. extract_claims：基于 ChapterGenerationTask、dense_context 和 CanonicalClaimPool 生成 ClaimLedger。
    4. align_evidence：把 ClaimLedger 映射到 evidence_units，生成 ClaimEvidenceMap 和 EvidenceLedger。
    5. resolve_conflicts：处理定义冲突、记号冲突、来源口径差异和例子冲突。
    6. draft_chapter：基于 resolved claims 和 claim-evidence map 写章节草稿，留下增强占位符。
    7. critic/rewrite：当前代码仍在单章内做轻量 critic 和最多一次 rewrite；目标上应逐步前移到 review_content。
  模式差异：sprint/systematic 的核心差异主要在 draft_chapter 体现。
    - sprint：短、密、题型导向，强调考点、速判、易错点、复盘清单。
    - systematic：长、稳、结构导向，强调定义、推理、例子、迁移和前置关系。

enhance_chapters
  ├─ enhance_chapter 1
  ├─ enhance_chapter 2
  └─ enhance_chapter N
  输入：ChapterDraft / ClaimLedger / ConfusionMap / placeholder_requests / asset settings / digest_mode
  输出：EnhancedChapterDraft[] / AssetManifest[] / PracticeManifest[]
    - EnhancedChapterDraft：增强后的章节正文。
    - AssetManifest：Mermaid、图片、交互块等资产清单。
    - PracticeManifest：本章自检题和练习种子。
  作用：处理 Mermaid、图片占位、交互块、公式清洗、本章自检。
  enhance_chapter 内部步骤：
    1. 解析章节中的 Mermaid / image / interactive 占位符。
    2. 生成或降级处理对应资产。
    3. 统一公式、Mermaid、Markdown 结构。
    4. 根据 ClaimLedger 和 ConfusionMap 追加本章自检题。
    5. 产出 asset / practice manifest。
  约束：
    - 不大幅改写知识内容。
    - 不修核心定义。
    - 不自行引入新结论。
    - 不改变 claim / evidence 关系。

review_content / 当前 review_chapter Send x N + document_consistency_review
  ├─ review_chapter 1
  ├─ review_chapter 2
  ├─ review_chapter N
  └─ document_consistency_review
  输入：EnhancedChapterDraft[] / ChapterGenerationTask[] / DocumentBackbone / ClaimLedger[] / ClaimEvidenceMap[] / EvidenceLedger[] / ConflictReport[] / DocGenIntentProfile
  输出：ReviewedChapterDraft[] / ChapterReviewReport[] / DocumentConsistencyReport / ReviewAction[] / review_decision
    - ReviewedChapterDraft：最终可合并章节稿。
    - ChapterReviewReport：单章覆盖率、质量分、缺失点、修补记录、warning。
    - DocumentConsistencyReport：跨章术语、符号、定义、前置关系和风格一致性报告。
    - ReviewAction：复核后的回流动作。
    - review_decision：good / needs_repair / publish_with_warnings / fail。
  作用：复核增强后的最终章节，并检查整本文档一致性。
  review_chapter 检查：
    1. 合同覆盖：required_elements 是否覆盖，是否越界。
    2. 主张支撑：claim 是否有足够 evidence 支撑。
    3. 结构风格：长度、节奏、模式、用词是否符合。
    4. 风险信号：定义模糊、低支撑断言、unresolved conflict。
  document_consistency_review 检查：
    1. 跨章术语和符号是否一致。
    2. 定义是否冲突。
    3. 前置关系是否倒挂。
    4. 是否重复讲或某章吃掉下一章内容。
    5. 整本风格是否断裂。
  当前实现补充：
    - review_chapter 使用 LLM 结构化复核 + 规则 guardrail。
    - review_chapter 当前通过 LangGraph Send 按章 fan-out，在 LangSmith 中可见为并行章节复核分支。
    - document_consistency_review 在章节 fan-in 后执行，不调工具、不检索、不改正文。

repair_or_route
  输入：ReviewAction[] / ReviewedChapterDraft[] / EnhancedChapterDraft[] / ChapterGenerationTask[] / DocumentBackbone
  输出：ReviewedChapterDraft[] / rerun_tasks / unresolved_warnings / repair_trace
  作用：按问题严重度决定是否 patch、重写章节、重派发任务或重建 backbone。
  回流级别：
    - surface_patch：标题微调、语句不通顺、小过渡、小引用补齐。
    - section_patch：小节逻辑弱、例题不好、易混点没讲清、定义需要局部改写。
    - evidence_patch：证据不足、来源支撑弱，需要补检索、补阅读、补 evidence binding。
    - regenerate_chapter：claim coverage 不够、关键证据缺失、核心定义冲突、章节边界偏移。
    - re_dispatch：单章任务合同本身不清楚，需要重新生成 ChapterGenerationTask。
    - rebuild_backbone：跨章术语漂移、概念顺序错、整本结构断裂。
  当前实现：
    - 已支持 surface_patch / section_patch 的局部 Markdown patch。
    - evidence_patch / regenerate_chapter / re_dispatch / rebuild_backbone 先结构化记录为 unresolved warning。
    - 当前仍是一次性路径：review_content -> repair_or_route -> merge_review。
  目标实现：
    - 支持最多两轮有限回流：review_content <-> repair_or_route。
    - 第二轮仍未解决的问题写入 unresolved_warnings 和 manifest。

merge_review
  输入：ReviewedChapterDraft[] / ChapterGenerationPlan / DocumentBackbone / ClaimLedger[] / ClaimEvidenceMap[] / EvidenceLedger[] / ConflictReport[] / DocumentConsistencyReport / ReviewAction[]
  输出：merged_markdown / chapter_metadatas / MergeReviewReport
    - merged_markdown：整本文档 Markdown。
    - chapter_metadatas：发布和 manifest 使用的章节元数据。
    - MergeReviewReport：章节完整性、manifest 完整性和最终来源覆盖报告。
  作用：合并章节，只做发布前收口，不承担最重的知识复核。

final_merge_patch
  输入：merged_markdown / chapter_metadatas / merge_review_report / unresolved_warnings
  输出：merged_markdown / chapter_metadatas / final_merge_patch_report
  作用：目标节点，只修合并后才暴露的小问题。
  允许：
    - 目录重复。
    - 跨章过渡缺失。
    - 重复摘要。
    - manifest 缺字段。
  禁止：
    - 重新检索。
    - 重写章节。
    - 改变 claim / evidence。
  当前状态：尚未独立实现。

finalize_titles
  输入：chapter_metadatas / confirmed_plan.chapter_plan / enhanced titles / merge_review_report
  输出：final_chapter_titles / updated chapter_metadatas / title_review_report
  作用：标题收口，保持 chapter_index 和 confirmed plan 映射。
  当前实现：
    - LLM 复核整本章节标题。
    - 同步改每章 Markdown 一级标题。
    - 失败时 fallback 到规则标题。
  约束：只统一标题表达，不推翻用户确认过的章节语义。

publish_document
  输入：merged_markdown / chapter_metadatas / docgen_artifacts / document_context
  输出：markdown files / docgen_manifest.json / KnowledgeDoc rows / version archive
    - docgen_artifacts：DocGenContext、DocumentBackbone、计划、章节、主张、证据、冲突、资产、练习、review 报告。
  作用：发布章节 Markdown、整本 Markdown、manifest、数据库记录和版本归档。
```

## 2. 当前实现映射

| 目标阶段 | 当前对应 | 状态 |
| --- | --- | --- |
| `load_context` | `load_context` | 已落地 |
| `prepare_context.enhance_plan_outline` | `prepare_parallel_inputs` 内部 | 已落地 |
| `prepare_context.infer_docgen_intent` | `prepare_parallel_inputs` 内部 | 已落地 |
| `prepare_context.summarize_files` | `prepare_parallel_inputs` 内部 | 已落地，已输出 evidence candidates |
| `merge_and_dispatch` | `confirm_and_dispatch` | 已落地，已输出 plan seed 和 backbone agenda |
| `build_document_backbone` | `build_document_backbone` | 已落地，含 fallback backbone |
| `generate_draft` | `generate_chapters` | 已落地，已输出 trace / evidence / claim / conflict |
| `enhance` | `enhance_chapters` | 已落地，需补 asset disabled manifest |
| `review_content.review_chapter` | `review_chapter` / `复核章节内容` | 已落地，LangGraph Send x N，LLM review + 规则兜底 |
| `review_content.document_consistency_review` | `document_consistency_review` / `复核整本一致性` | 已落地，章节 review fan-in 后执行 |
| `repair_or_route` | `repair_or_route` | 已落地局部 patch：可执行 surface/section patch；待补 evidence/regenerate 和真实 repair loop |
| `merge_review` | `merge_review` | 已落地 |
| `final_merge_patch` | 无 | 待新增，只处理合并后小问题 |
| `finalize_titles` | `finalize_titles` | 已落地，LLM 标题复核 + Markdown 一级标题同步 |
| `publish_document` | `publish_document` | 已落地，已写 docgen artifacts manifest |

## 3. 有限回流目标设计

当前 graph 是一次性路径：

```text
review_content -> repair_or_route -> merge_review
```

目标是升级为最多两轮的有限闭环：

```text
review_content
  ├─ good / publish_with_warnings
  │    -> merge_review
  └─ needs_repair
       -> repair_or_route
            ├─ surface_patch
            ├─ section_patch
            ├─ evidence_patch
            ├─ regenerate_chapter
            └─ record_only
       -> review_content
```

循环只允许发生在 `review_content <-> repair_or_route` 之间。`review_content` 是裁判，`repair_or_route` 是执行者。这样可以避免每个节点都自行决定“再修一次”，也避免变成不可控多 Agent 循环。

### 3.1 推荐新增 `RepairLoopState`

```text
RepairLoopState
  repair_round_total
  chapter_patch_rounds
  chapter_regenerate_rounds
  evidence_patch_rounds
  last_review_decision
  repair_trace
```

推荐上限：

```text
repair_round_total <= 2
chapter_patch_round_per_chapter <= 2
chapter_regenerate_round_per_chapter <= 1
evidence_patch_round_per_chapter <= 1
final_merge_patch_round <= 1
```

### 3.2 推荐扩展 `ReviewAction`

当前 `ReviewAction` 已经具备驱动局部 patch 的字段。后续接入 evidence/regenerate 时继续沿用这个结构：

```text
ReviewAction
  action_id
  action_type: surface_patch / section_patch / evidence_patch / regenerate_chapter / re_dispatch / rebuild_backbone
  chapter_index
  severity: info / warning / error
  reason
  target_anchor
  instruction
  constraints
  expected_effect
  status: recorded / applied / skipped / downgraded
```

`evidence_patch` 应该单独存在，不要继续把证据不足映射成 `regenerate_chapter`。证据不足通常只需要定向补来源和局部改写，不必重写整章。

### 3.3 修补动作分层

- `no_action`：复核通过，直接进入 `merge_review`。
- `surface_patch`：修标题层级、重复句、过渡句、Markdown 轻微问题；不得新增知识。
- `section_patch`：只改局部小节；不得改变章节边界、核心定义和 claim/evidence 对应关系。
- `evidence_patch`：针对缺口补检索、打开网页、压缩正文、补证据，再做局部改写；必须记录新来源、read_url_count、snippet fallback。
- `regenerate_chapter`：只重写问题章节。重写后必须重新经过 enhance 和 review。
- `record_only`：问题太大、证据不足、会推翻 confirmed plan 或超过预算时，只写 warning。
- `re_dispatch` / `rebuild_backbone`：第一版只记录，不自动执行；后续如果支持，也必须回到明确的计划确认或全局重建流程。

### 3.4 循环前必须先解决的 state 问题

当前这些字段是 `operator.add` fan-in：

```text
chapter_drafts
enhanced_chapter_drafts
research_traces
evidence_ledgers
claim_ledgers
claim_evidence_maps
conflict_reports
asset_manifests
practice_manifests
research_sources
```

如果直接引入 repair loop 或 regenerate chapter，会把旧版本和新版本都累加进 state。下一步必须明确：

- 哪些字段允许 append history。
- 哪些字段必须按 `chapter_index` 替换最新版本。
- manifest 里如何保留历史 trace，同时 publish 只消费最新版本。

推荐新增：

```text
chapter_artifact_versions
active_chapter_artifacts
repair_trace
```

或在 `repair_or_route` 后统一做按章去重替换。

## 4. 节点能力边界

### 4.1 `generate_chapters`

可以：

- 本地 RAG、文件切片读取、外部检索、网页打开、上下文压缩。
- 根据 confirmed plan、digest mode、planner context 和章节缺口决定检索重点。
- 生成 dense context、research trace、evidence ledger、claim ledger、conflict report 和章节草稿。

不能：

- 修改 confirmed plan 的章节数量、顺序和用户确认语义。
- 做标题最终收口。
- 把未打开或未压缩的搜索标题当作正文证据。

### 4.2 `enhance_chapters`

可以：

- Mermaid、图片请求降级、交互占位处理、公式清洗、Markdown 结构和本章自检。
- 根据 asset settings、digest mode 和章节合同决定表现层策略。

不能：

- 引入新的核心定义、结论、例题口径或证据主张。
- 改变 claim / evidence 对应关系。

### 4.3 `review_content`

可以：

- 逐章复核合同覆盖、证据支撑、章节边界和质量信号。
- 复核跨章术语、标题、前置关系、重复和风格一致性。
- 产出 `ReviewAction`、`DocumentConsistencyReport` 和后续路由判定。

不能：

- 检索、打开网页、调用工具。
- 直接 patch 正文。

### 4.4 `repair_or_route`

可以：

- 读取 `ReviewAction`，按严重度和预算执行 patch、补证据、重写或记录 warning。
- 调用检索、reader、writer 等工具，但必须写入 `repair_trace`。

不能：

- 无限循环。
- 静默推翻 confirmed plan。
- 在没有本地资料、已打开网页正文或明确 snippet fallback 的情况下补新断言。

### 4.5 `merge_review` / `final_merge_patch` / `finalize_titles`

`merge_review` 只做发布前收口，不再承担重知识复核。

`final_merge_patch` 只修合并后才暴露的小问题：

- 目录重复。
- 跨章过渡缺失。
- 重复摘要。
- manifest 缺字段。

`finalize_titles` 只执行一次，放在所有 patch 和最终一致性复核之后。

## 5. 当前重大问题判断

当前没有发现需要立刻推倒重写 DocGen 主图的问题。主线已经接近目标设计，重要能力也基本落点清楚。

值得后续重构的重点是：

| 优先级 | 问题 | 为什么重要 |
| --- | --- | --- |
| P0 | 文档与代码漂移 | 新人会按过期 README / 架构评估理解当前 graph，后续改动容易补错位置 |
| P1 | repair loop 还没形成闭环 | 复核只能记录，不能真正按问题级别修补 |
| P1 | evidence patch 尚未接入 | 证据不足目前只能结构化记录，不能定向补检索、补阅读、补 evidence binding |
| P1 | state append reducer 与回流冲突 | 引入循环后容易重复发布过期章节或重复 manifest |
| P1 | image 生成已接入，仍缺前端展示和失败重试策略 | 用户能拿到 manifest，但图片资产体验还需收口 |
| P2 | `final_merge_patch` 未实现 | 合并后小问题只能靠人工或间接收口 |
| P2 | research budget 仍偏静态 | 还没充分根据覆盖度、证据缺口和章节难度动态调度 |

## 6. 近期不要做

- 不把 DocGen 改成完整多 Agent 动态队列。
- 不让 DocGen 自动推翻 confirmed plan。
- 不把 Planner 重新变成 research 系统。
- 不恢复独立 prompt 扩展层。
- 不新建第二套 search/tool registry。
- 不让 `enhance_chapters` 修核心知识逻辑。
- 不把所有原文一次性塞进 writer prompt。
- 不随便给文档型 helper 补测试，除非它已经成为稳定核心合同。

## 7. 一句话收束

```text
DocGen 的核心不是把章节写出来，
而是在确认方案上补齐知识骨架、主张证据、冲突消解和有限复核，
让最终文档可读、可追踪、可修补、可被其他引擎复用。
```
