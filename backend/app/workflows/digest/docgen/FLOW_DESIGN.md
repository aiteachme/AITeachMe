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

### 1.2 有限迭代回流设计

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

```text
load_context
  输入：confirmed_plan / shared_inputs / planner_context
    - confirmed_plan：用户确认后的构建合同，包含章节、模式、目标、约束。
    - shared_inputs：资料理解包，包含文件、切片、画像、统计、资产索引。
    - planner_context：confirmed_plan 中固化的 Planner 会话摘要和修改意见。
  输出：DocumentContract / SourcePack / DocGenContext / chapter_assignments / document_context
    - DocumentContract：confirmed_plan 的执行语义，不允许静默漂移。
    - SourcePack：资料包，负责说明“从哪里找材料”。
    - DocGenContext：DocGen 全局运行上下文。
    - chapter_assignments：confirmed plan 章节转成的执行章节列表。
    - document_context：发布和写作共用的文档级上下文。
  作用：确认用户已确认的章节合同，补齐资料上下文、模式、语气和构建状态。

prepare_context
  ├─ enhance_plan_outline
  │    输入：chapter_assignments / material_stats_profile / material_sections / planner_context
  │      - chapter_assignments：用户确认的章节列表。
  │      - material_stats_profile：资料类型、题目密度、公式密度、学科画像等统计。
  │      - material_sections：切片级正文，可抽取高信息密度片段。
  │    输出：EnhancedChapterOutline[] / plan_mismatch_warnings[]
  │      - EnhancedChapterOutline：每章执行级小纲和重点目标。
  │      - plan_mismatch_warnings：模型输出和 confirmed plan 不一致时的 warning。
  │    作用：执行级细化章节，不新增、不删除、不重排 confirmed plan。
  │    注意：这里只做轻量 grounding，不做完整 Web research。
  ├─ infer_docgen_intent
  │    输入：user_goal / plan_summary / digest_mode / chapter_assignments / docgen_history_brief
  │      - user_goal：用户最终学习目标。
  │      - plan_summary：Planner 生成的方案摘要。
  │      - digest_mode：sprint 或 systematic。
  │      - docgen_history_brief：和文档生成有关的历史修改摘要。
  │    输出：DocGenIntentProfile
  │      - depth_level：讲解深度。
  │      - example_preference：定义优先、例题优先、比喻优先等偏好。
  │      - exam_orientation：考试导向强弱。
  │      - derivation_tolerance：是否允许详细推导。
  │      - redundancy_tolerance：是否允许重复强调。
  │      - avoidance_rules：尽量不写或不能写的内容。
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

merge_and_dispatch
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

build_document_backbone
  输入：ChapterGenerationPlanSeed / ChapterGenerationTaskSeed[] / SourcePack / high_confidence_evidence_units / backbone_research_agenda
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

generate_draft
  ├─ generate_chapter 0
  ├─ generate_chapter 1
  └─ generate_chapter N
  输入：单章 ChapterGenerationTask / SourcePack / DocumentBackbone / DocGenContext / retrieval_profile
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
  模式差异：sprint/systematic 的核心差异主要在 draft_chapter 体现。
    - sprint：短、密、题型导向，强调考点、速判、易错点、复盘清单。
    - systematic：长、稳、结构导向，强调定义、推理、例子、迁移和前置关系。

enhance
  ├─ enhance_chapter 0
  ├─ enhance_chapter 1
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

review_content
  ├─ review_chapter 0
  ├─ review_chapter 1
  ├─ review_chapter N
  └─ document_consistency_review
  输入：EnhancedChapterDraft[] / ChapterGenerationTask[] / DocumentBackbone / ClaimLedger[] / ClaimEvidenceMap[] / EvidenceLedger[] / ConflictReport[] / DocGenIntentProfile
  输出：ReviewedChapterDraft[] / ChapterReviewReport[] / DocumentConsistencyReport / ReviewAction[]
    - ReviewedChapterDraft：最终可合并章节稿。
    - ChapterReviewReport：单章覆盖率、质量分、缺失点、修补记录、warning。
    - DocumentConsistencyReport：跨章术语、符号、定义、前置关系和风格一致性报告。
    - ReviewAction：复核后的回流动作。
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

repair_or_route
  输入：ReviewAction[] / ChapterDraft[] / EnhancedChapterDraft[] / ChapterGenerationTask[] / DocumentBackbone
  输出：ReviewedChapterDraft[] / rerun_tasks / unresolved_warnings
  作用：按问题严重度决定是否 patch、重写章节、重派发任务或重建 backbone。
  回流级别：
    - surface_patch：标题微调、语句不通顺、小过渡、小引用补齐。
    - section_patch：小节逻辑弱、例题不好、易混点没讲清、定义需要局部改写。
    - regenerate_chapter：claim coverage 不够、关键证据缺失、核心定义冲突、章节边界偏移。
    - re_dispatch：单章任务合同本身不清楚，需要重新生成 ChapterGenerationTask。
    - rebuild_backbone：跨章术语漂移、概念顺序错、整本结构断裂。
  MVP：第一版可以只记录 ReviewAction[]，不自动回流；第二版再支持最多一轮有限回流。

merge_review
  输入：ReviewedChapterDraft[] / ChapterGenerationPlan / DocumentBackbone / ClaimLedger[] / ClaimEvidenceMap[] / EvidenceLedger[] / ConflictReport[] / DocumentConsistencyReport / ReviewAction[]
  输出：merged_markdown / chapter_metadatas / MergeReviewReport
    - merged_markdown：整本文档 Markdown。
    - chapter_metadatas：发布和 manifest 使用的章节元数据。
    - MergeReviewReport：章节完整性、manifest 完整性和最终来源覆盖报告。
  作用：合并章节，只做发布前收口，不承担最重的知识复核。

finalize_titles
  输入：chapter_metadatas / confirmed_plan.chapter_plan / enhanced titles / merge_review_report
  输出：final_chapter_titles / updated chapter_metadatas / title_review_report
  作用：标题收口，保持 chapter_index 和 confirmed plan 映射。
  约束：只统一标题表达，不推翻用户确认过的章节语义。

publish_document
  输入：merged_markdown / chapter_metadatas / docgen_artifacts / document_context
  输出：markdown files / docgen_manifest.json / KnowledgeDoc rows / version archive
    - docgen_artifacts：DocGenContext、DocumentBackbone、计划、章节、主张、证据、冲突、资产、练习、review 报告。
  作用：发布章节 Markdown、整本 Markdown、manifest、数据库记录和版本归档。
```

manifest 需要尽量保留：

```text
document_backbone_snapshot
chapter_generation_plan
claim_ledgers
claim_evidence_maps
conflict_reports
document_consistency_report
review_actions
unresolved_warnings
source_trust_summary
asset_manifest
practice_manifest
```

## 2. 当前实现映射

当前 graph：

```text
load_context
  -> prepare_parallel_inputs
  -> confirm_and_dispatch
  -> generate_chapters
  -> enhance_chapters
  -> merge_review
  -> publish_document
```

目标映射：

| 目标阶段 | 当前对应 | 状态 |
| --- | --- | --- |
| `load_context` | `load_context` | 已落地 |
| `prepare_context.enhance_plan_outline` | `prepare_parallel_inputs` 内部 | 已落地，保持轻量 grounding |
| `prepare_context.infer_docgen_intent` | `prepare_parallel_inputs` 内部 | 已落地 |
| `prepare_context.summarize_files` | `prepare_parallel_inputs` 内部 | 已落地，需输出 evidence units |
| `merge_and_dispatch` | `confirm_and_dispatch` | 已落地，需输出 plan seed 和 backbone agenda |
| `build_document_backbone` | 无 | 待新增，位于 merge_and_dispatch 后 |
| `generate_draft` | `generate_chapters` | 已落地，需加入 claim/evidence/conflict |
| `enhance` | `enhance_chapters` | 已落地，需限制为表现层 |
| `review_content.review_chapter` | `generate_chapters` 内部 critic/rewrite | 待移到 enhance 后并拆独立节点 |
| `review_content.document_consistency_review` | `merge_review` 的一小部分 | 待新增 |
| `repair_or_route` | 无 | 待新增，MVP 可只记录 ReviewAction |
| `merge_review` | `merge_review` | 已落地，后续只做收口 |
| `finalize_titles` | 分散在 generation / merge / publish 中 | 待补独立节点 |
| `publish_document` | `publish_document` | 已落地，需扩 manifest |

## 3. MVP 落地顺序

### Phase 1：强化 prepare_context 和初版派发

```text
1. prepare_context 保持轻量，只产出 outline / intent / file summaries / evidence candidates。
2. merge_and_dispatch 先输出 ChapterGenerationPlanSeed / ChapterGenerationTaskSeed[]。
3. merge_and_dispatch 同时输出 backbone_research_agenda。
```

### Phase 2：在 merge_and_dispatch 后补知识骨架

```text
1. 新增 DocumentBackbone 模型。
2. 新增 build_document_backbone 节点。
3. 基于 task seeds、evidence candidates 和必要检索生成 glossary / claim_pool / confusion_map。
4. 回填 ChapterGenerationPlan / ChapterGenerationTask[]。
5. manifest 写入 document_backbone_snapshot。
```

### Phase 3：强化单章合同

```text
1. 强化 ChapterGenerationTask。
2. 增加 required / forbidden / dependencies / claims / confusion targets。
3. 增加 coverage / evidence / patch 阈值。
```

### Phase 4：单章研究式生成

```text
1. generate_chapter 内部加入 extract_claims。
2. 加入 ClaimLedger。
3. 加入 ClaimEvidenceMap。
4. 加入 ConflictReport。
5. writer 基于 resolved claims 写正文。
```

### Phase 5：表现层增强降权

```text
1. enhance_chapter 只处理资产、格式、自检。
2. 自检题从 ClaimLedger / ConfusionMap 派生。
3. 禁止 enhance 生成新的核心知识结论。
```

### Phase 6：双层复核和回流记录

```text
1. review_chapter 独立出来。
2. document_consistency_review 独立出来。
3. 输出 ReviewAction[]。
4. 第一版只记录回流建议，不自动执行。
```

### Phase 7：发布与追踪

```text
1. manifest 写入 backbone / ledgers / maps / reports。
2. KnowledgeDoc 保留 chapter metadata 和 source trust summary。
3. 后续给 Interact / Examine / Profile 复用。
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
