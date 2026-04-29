# DocGen 流程设计

最后更新：2026-04-28

这份文档是 `backend/app/workflows/digest/docgen/` 当前唯一的文档文件，同时兼任入口说明和流程权威文档。

如果 `docgen/` 下的文档、上游设计文档和当前实现之间出现冲突，按下面顺序判断：

1. 当前代码：`graph.py`、`state.py`、`nodes/`、`lib/models.py`
2. 当前文档：`FLOW_DESIGN.md`

使用约定：

- `FLOW_DESIGN.md` 负责维护 DocGen 的目录入口、公开运行面、真实流程、节点合同、当前实现映射和演进约束。
- `docgen/` 目录下不再保留第二份入口 README，也不再保留独立的架构评估文档。
- 其他上游文档如果需要引用 DocGen 文档，应显式指向本文件，不应复制一份新的节点级流程合同。

## 0. 文档维护硬约束

`FLOW_DESIGN.md` 必须长期同时保留两类流程说明：

- **短流程总览**：快速看懂所有节点、并行关系、fan-out/fan-in、流水线顺序和每个节点作用。
- **长流程执行合同**：逐节点写清输入、输出、作用、内部步骤和约束，作为后续实现和重构的详细合同。

后续任何人改 DocGen 流程时，必须同时更新短流程和长流程。不能只改代码映射表，也不能只改长流程。

如果目标阶段名和当前代码节点名不一致，必须显式写出映射，例如：

```text
prepare_global_seed / 当前 prepare_global_seed
seed_backbone / 当前 confirm_and_seed_backbone
prepare_chapter_execution / 当前 build_chapter_execution_briefs + assemble_chapter_tasks
generate_draft / 当前 generate_chapters
enhance / 当前 enhance_chapters
```

核心判断：

```text
Planner 定方向，DocGen 构建知识文档。
```

DocGen 与知识图谱的协作口径：

```text
DocGen 主路径只负责知识文档质量和发布；KG 预抽取是 sidecar，不是 DocGen 节点。
```

当 `knowledge_graph.prefetch_during_docgen` 开启时，DocGen 在章节进入稳定增强态后会启动
非阻塞 `kg_prefetch sidecar`。这个 sidecar 只做 section 级候选抽取缓存，不写
`knowledge_unit / knowledge_edge`，也不参与 DocGen 的路由、复核和发布判定。发布成功后，
`kg_doc_sync` 会用最终发布 Markdown 的 section hash 校验缓存，命中则复用，未命中则补抽。

DocGen 不是“重新想一个大纲再写全文”，而是消费用户确认过的 `confirmed_plan`，在不推翻用户确认语义的前提下完成：

- 章节执行合同细化。
- 整本文档知识骨架构建。
- 单章研究、证据、主张、冲突记录。
- 表现层增强。
- 内容复核、有限回流和发布级 manifest。

### 0.1 本文件同时承担的入口信息

当前 `docgen/` 目录：

```text
docgen/
  __init__.py          # lane 稳定导出面
  graph.py             # LangGraph 定义、Send 分发、单次运行入口
  state.py             # DocGenState TypedDict
  nodes/               # 顶层图节点
  lib/                 # 节点内部复用逻辑和 Pydantic 合同
  prompts/             # prompt builder / template
  FLOW_DESIGN.md       # 当前唯一文档文件
```

公开入口与阅读顺序：

1. `backend/app/workflows/digest/docgen/FLOW_DESIGN.md`
2. `backend/app/workflows/digest/docgen/graph.py`
3. `backend/app/workflows/digest/docgen/state.py`
4. `backend/app/workflows/digest/docgen/lib/models.py`
5. `backend/app/workflows/digest/docgen/nodes/*.py`

运行入口说明：

- `__init__.py` 只保留稳定导出。
- `graph.py` 承接图定义、Send fan-out/fan-in 和单次 `run_docgen_workflow`。
- LangGraph 节点的 `node_description`、输入输出字段和 metadata 统一通过 `digest.common.node_tracing` 生成，避免文档化信息在多个 graph 里漂移。
- `lib/build_lifecycle.py` 承接 API 触发后的构建锁、后台任务、状态装配和结果组装。
- `graph.get_langgraph_dev_docgen_graph()` 只服务 `langgraph dev` / 图可视化调试，不是业务运行入口。

## 1. 流程总览与执行合同

### 1.1 短流程总览

这一节面向快速阅读，必须写清所有节点、并行关系、fan-out/fan-in、流水线关系和节点作用。字段级输入输出放在 `1.2 长流程执行合同`。

### 1.1.1 当前模型槽位总览

本节只描述 **当前代码真实使用的逻辑模型槽位**。最终 provider 模型名来自：

- `backend/app/shared/infra/settings/defaults.py`
- `backend/app/shared/infra/settings/settings.py`

当前默认映射是：

```text
reason  -> qwen-max
primary -> qwen-flash
light   -> qwen-flash
image_generation -> settings.models.image_generation（默认未配置）
```

注意：

- 这里说的 `reason / primary / light` 是逻辑模型槽位，不是固定 provider 名。
- 如果运行时 settings 覆盖了 `settings.models.*`，实际模型名会随之变化。
- `docgen` 当前没有使用 `extract` 槽位。
- DocGen 的 `call_purpose + model slot` 分配统一由 `lib/model_policy.py` 维护；节点和 lib 不应各自硬编码模型槽位。

按当前代码，DocGen 各阶段的大模型使用如下：

| 阶段 / 子步骤 | 当前代码位置 | 调用类型 | 逻辑模型槽位 | 当前默认模型 | 这一步做什么 | 为什么这样配 |
| --- | --- | --- | --- | --- | --- | --- |
| `prepare_global_seed.infer_intent_core` | `lib/intent.py` | 结构化 | `reason` | `qwen-max` | 只做文档级短意图判断，不再生成按章长提示 | 保留策略判断能力，但缩短输出，避免全局重调用过长 |
| `prepare_global_seed.summarize_files` | `lib/file_summaries.py` | 结构化 | `light` | `qwen-flash` | 为每个文件生成摘要、概念、公式、例题和章节亲和度 | 文件任务数量多，适合轻量并发 |
| `lock_titles_for_chapters.lock_title_for_chapter` | `lib/title_lock.py` | 结构化 | `reason` | `qwen-max` | 节点内部按章并行锁定最终标题 | 标题仍需高质量推理，但输出极短，适合收在单节点内部并行 |
| `confirm_and_seed_backbone` | 当前纯规则 | 无 LLM | 无 | 无 | 基于 confirmed plan、locked titles、source signals 组装骨架 seed | 这是规则收口，不需要额外模型推理 |
| `build_document_backbone` | 当前纯规则 | 无 LLM | 无 | 无 | 构建整本文档的术语表、主张池、依赖关系和易混点骨架 | 全局一致性优先用规则保持稳定 |
| `build_chapter_execution_briefs.build_chapter_execution_brief` | `lib/chapter_execution_brief.py` | 结构化 | `reason` | `qwen-max` | 节点内部按章并行生成最小执行 brief | 章级小任务，保留推理能力但严格限制输出字段和长度 |
| `assemble_chapter_tasks` | 当前纯规则 | 无 LLM | 无 | 无 | 合并 locked title、intent core、backbone、chapter brief，组装最终章节任务 | 任务装配是规则问题，不需要再调用模型 |
| `generate_chapters.query_planning` | `lib/query_planning.py` | 结构化 | `reason` | `qwen-max` | 把章节目标拆成 research sub-queries / gap queries | 研究问题拆解仍然适合推理式规划 |
| `generate_chapters.research_purify` | `lib/chapter_context.py` | 文本 | `light` | `qwen-flash` | 对 dense context 做轻量清洗，去掉噪声与重复 | 只是净化材料，不做深度推理 |
| `generate_chapters.writer` | `lib/writer.py` | 文本 | `systematic -> reason` / `sprint -> primary` | `qwen-max` / `qwen-flash` | 把研究材料和执行合同写成章节正文 | 系统课更偏结构推理，冲刺课更偏快速成文 |
| `generate_chapters.heading_repair` | `lib/writer.py` | 文本 | `light` | `qwen-flash` | 修正章节标题层级、学习脚手架和结构格式 | 轻量结构修正，不值得用更贵模型 |
| `generate_chapters.rewrite` | `lib/chapter_revision.py` | 文本 | `primary` | `qwen-flash` | 当章节质量不够时做一次 bounded rewrite | 正文改写质量要求高于 light，但不需要最重推理 |
| `enhance_chapters.mermaid_placeholder` | `lib/asset_rendering.py` | 文本 | `light` | `qwen-flash` | 把 Mermaid 占位符变成真正可渲染的结构图内容 | 资产生成是辅助增强，轻量模型足够 |
| `enhance_chapters.interactive_html_sidecar` | `lib/interactive_html.py` | 文本 | `primary` | `qwen-flash` | 为少量高价值章节生成独立 HTML 交互页 sidecar | 交互页比文生图更适合参数变化、步骤展开和几何/函数/方程可视化 |
| `review_content.review_chapter` | `lib/chapter_review.py` | 结构化 | `light` | `qwen-flash` | 逐章复核覆盖率、证据支撑和写作质量，产出 review action | 并行、轻量、结构化审稿场景，优先控制成本和速度 |
| `document_consistency_review` | 当前纯规则 | 无 LLM | 无 | 无 | 对整本文档做术语、章节数、重复和风格一致性检查 | 全局复核先用规则收口，减少漂移 |
| `repair_or_route.surface/section patch` | `lib/repair.py` | 文本 | `primary` | `qwen-flash` | 按 review action 对章节做局部 patch 或记录 unresolved warning | 已经直接改正文，不能太轻；但又不需要最重 reason |
| `merge_review` | 当前纯规则 | 无 LLM | 无 | 无 | 合并章节、整理 metadata、做发布前完整性检查 | 发布前规则收口，不负责重新思考内容 |
| `sync_locked_titles` | 当前纯规则 | 无 LLM | 无 | 无 | 只把已锁定标题同步到最终 Markdown，不重新起标题 | 当前明确禁止 LLM 改标题，防止推翻 confirmed plan 语义 |
| `publish_document` | 当前纯规则 | 无 LLM | 无 | 无 | 写出 Markdown、manifest、版本归档和数据库记录 | 发布阶段只做持久化，不承担内容生成 |
| `cover sidecar` | `lib/cover.py` | 文生图 | `image_generation` | 取决于 `settings.models.image_generation` | 为整本文档生成横向抽象封面图 | 封面是独立 sidecar，不干扰正文链路 |

当前主线：

```text
load_context
  读取 confirmed plan、资料理解包、Planner 上下文和构建入口参数。
  校验用户已经确认章节合同，生成 DocGen 全局上下文、章节 assignment 和发布上下文。
  |
  v
prepare_global_seed
  全局轻准备，只做两件事：
    ├─ infer_intent_core
    │    只推断文档级短意图，不再产按章长提示。
    └─ summarize_files
         摘要文件、判断章节亲和度、抽取高置信证据候选。
  这一步不再做整本 outline enhance。
  |
  v
lock_titles_for_chapters
  单节点内部按章节并行执行：
    - lock_title_for_chapter x N
  锁定最终标题，只输出标题相关字段。
  |
  v
confirm_and_seed_backbone
  合并 confirmed plan、locked titles、文件摘要、章节亲和度和证据候选。
  生成 ChapterGenerationPlanSeed、ChapterGenerationTaskSeed 和 backbone_research_agenda。
  |
  v
build_document_backbone
  基于章节 seed、资料摘要和证据候选，构建整本文档知识骨架。
  统一术语、概念依赖、符号、核心主张和易混点。
  |
  v
build_chapter_execution_briefs
  单节点内部按章节并行执行：
    - build_chapter_execution_brief x N
  每章生成最小执行 brief，不再产完整执行大纲。
  |
  v
assemble_chapter_tasks
  合并 locked title、intent core、document backbone、chapter brief。
  组装最终 ChapterGenerationPlan / ChapterGenerationTask。
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
  处理 Mermaid、交互 HTML sidecar、公式清洗、Markdown 结构，以及按构建约束追加例题/练习。
  如果图谱预抽取开启，则在本阶段完成后启动非阻塞 kg_prefetch sidecar：
    - 使用增强后的章节 Markdown 预抽取 section payload。
    - 默认最多 6 路 LLM 并发，并先让后续 DocGen review 调度。
    - 不等待、不落库、不影响后续 review_content。
  |
  v
review_content / 当前 review_chapter Send x N + document_consistency_review
  按章并行复核，然后执行整本一致性检查。
  |
  v
repair_or_route
  当前实现：对 surface_patch / section_patch 执行局部 Markdown patch；对 evidence_patch / regenerate_chapter / re_dispatch / rebuild_backbone 等重动作结构化记录。
  当前流水线：review_content -> repair_or_route -> merge_review。
  |
  v
merge_review
  reviewed drafts fan-in 后按 chapter_index 去重、排序、收口 chapter metadata。
  |
  v
sync_locked_titles
  不再生成新标题；只同步 lock_titles_for_chapters 阶段已经锁定的标题。
  |
  v
publish_document
  发布章节 Markdown、整本 Markdown、docgen_manifest.json、版本归档和 KnowledgeDoc rows。
```

并行与 fan-in/fan-out 关系摘要：

```text
prepare_global_seed
  infer_intent_core ┐
  summarize_files   ┘

lock_titles_for_chapters
  单节点内部并行执行 lock_title_for_chapter x N
  完成后进入 confirm_and_seed_backbone

build_chapter_execution_briefs
  单节点内部并行执行 build_chapter_execution_brief x N
  完成后进入 assemble_chapter_tasks

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

kg_prefetch sidecar
  enhanced_chapter 1 ┐
  enhanced_chapter 2 ├─ 后台预抽取候选，仅缓存 section payload
  enhanced_chapter N ┘
  发布成功后由 kg_doc_sync 消费；发布失败或构建取消时丢弃。
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
  当前模型方案：
    - 当前无 LLM 调用；纯合同校验与上下文组装。

prepare_global_seed
  输入：user_prompt / plan_summary / digest_mode / chapter_assignments / docgen_history_brief / source_packets / section_packets
    - chapter_assignments：用户确认的章节列表。
    - source_packets / section_packets：文件级正文包和切片级正文包。
    - docgen_history_brief：和文档生成有关的历史修改摘要。
  输出：intent_core / FileMaterialSummary[] / source_affinity_by_chapter / high_confidence_evidence_units
    - intent_core：文档级短意图，只包含 document style、深度、例子偏好、考试导向和 avoid_list。
    - FileMaterialSummary：文件摘要、核心概念、公式、例题、高价值 section、章节亲和度和 `chapter_slices`。
    - chapter_slices：文件摘要 LLM 根据切片目录做“章节 -> 原文片段”路由，记录 section_ref、行号、用途、原因和片段摘要。
    - source_affinity_by_chapter：每章优先使用哪些文件、切片和 LLM 预选 source_slices。
    - high_confidence_evidence_units：高置信证据单元。
  作用：把前置阶段收口成“全局轻准备”，不再在这里生成整本执行大纲。
  当前模型方案：
    - `infer_intent_core`
      - `call_purpose=CLASSIFY`
      - `model="reason"`
      - 默认映射到 `qwen-max`
    - `summarize_files`
      - `call_purpose=DOCGEN_LIGHT`
      - `model="light"`
      - 默认映射到 `qwen-flash`
      - 同时接收 section catalog，让 LLM 为后续章节写作选择原文切片，而不是只做文件级摘要。

lock_titles_for_chapters
  输入：course / digest_mode / user_prompt / plan_summary / docgen_history_brief / chapter_assignment
    - chapter_assignment：单章 confirmed contract。
  输出：LockedChapterTitle[]
    - LockedChapterTitle：单章锁定标题记录，只包含 confirmed_title / enhanced_title / warnings / fallback_used。
  作用：把标题锁定从原来的整本 outline enhance 中拆出来，改成收在单节点里的章节级并行极短结构化任务。
  约束：
    - 只锁标题。
    - 不生成 teaching outline。
    - 不生成 retrieval queries。
    - 不生成 media requests。
  当前模型方案：
    - `call_purpose=REASONING`
    - `model="reason"`
    - 默认映射到 `qwen-max`

confirm_and_seed_backbone
  输入：confirmed_plan payload / LockedChapterTitle[] / FileMaterialSummary[] / source_affinity_by_chapter / high_confidence_evidence_units
  输出：ChapterGenerationPlanSeed / ChapterGenerationTaskSeed[] / backbone_research_agenda / locked_titles
    - ChapterGenerationPlanSeed：整轮写作规则、格式和预算初稿。
    - ChapterGenerationTaskSeed：单章 seed，只保留标题、章节目标、required_elements、最小 retrieval seed 和 source seed。
    - backbone_research_agenda：构建全局知识骨架需要优先检索和打开的主题、切片、证据方向。
    - locked_titles：按 chapter_index 排序后的稳定标题记录。
  作用：在标题锁定之后，用规则把 confirmed plan 和 source signals 收口成 backbone seed。
  当前模型方案：
    - 当前无 LLM 调用；纯规则收口和 seed/agenda 派生。

build_document_backbone
  输入：ChapterGenerationTaskSeed[] / shared_inputs / high_confidence_evidence_units / backbone_research_agenda
  输出：DocumentBackbone / backbone_conflict_warnings
    - DocumentBackbone：整本文档的全局知识骨架。
    - backbone_conflict_warnings：全局术语、定义、符号或来源冲突 warning。
  作用：在 seed 基础上做全局证据采样和统一建模，但不在这里直接组装最终 ChapterGenerationTask。
  DocumentBackbone 包含：
    - CanonicalGlossary：全局术语表，统一术语、别名、定义。
    - ConceptDependencyGraph：概念依赖图，约束前置关系。
    - NotationRegistry：符号和记号规范。
    - CanonicalClaimPool：整本文档必须讲清的核心主张池。
    - ConfusionMap：易混点、误区和边界。
  当前模型方案：
    - 当前无 LLM 调用；纯规则骨架构建 + fallback backbone。

build_chapter_execution_briefs
  输入：ChapterGenerationTaskSeed / DocumentBackbone / intent_core
  输出：ChapterExecutionBrief[]
    - ChapterExecutionBrief：单章最小执行脚手架。
  作用：把原来整本 outline enhance 中“每章怎么讲”的部分拆出来，改成收在单节点里的章节级并行小任务。
  约束：
    - teaching_outline 最多 3 条。
    - concept_targets / definition_targets / formula_targets / example_targets / pitfall_targets 各最多 2 条。
    - retrieval_queries 最多 2 条。
    - 不允许顺带改标题。
    - 不输出 media_requests。
    - 不输出 practice_seed_policy。
  当前模型方案：
    - `call_purpose=REASONING`
    - `model="reason"`
    - 默认映射到 `qwen-max`

assemble_chapter_tasks
  输入：confirmed_plan payload / locked_titles / intent_core / ChapterGenerationTaskSeed[] / ChapterExecutionBrief[] / DocumentBackbone / FileMaterialSummary[] / source_affinity_by_chapter
  输出：ChapterGenerationPlan / ChapterGenerationTask[] / chapter_execution_briefs
    - ChapterGenerationPlan：最终整轮执行计划。
    - ChapterGenerationTask：最终单章执行合同。
    - chapter_execution_briefs：排序后的章节 brief 快照。
  作用：用规则把 locked title、intent core、document backbone 和 chapter brief 合并成最终章节任务。
  ChapterGenerationTask 至少包含：
    - chapter_index / confirmed_title / enhanced_title / objective
    - required_elements / forbidden_scope
    - retrieval_queries / priority_section_refs / source_slices / preferred_sources / fallback_policy
    - concept_targets / definition_targets / formula_targets / example_targets / pitfall_targets
    - allowed_assets / practice_seed_policy（由规则装配阶段派生，不再由 chapter brief 直接产出）
    - dependency_refs / forward_refs / claim_targets / confusion_targets
  当前模型方案：
    - 当前无 LLM 调用；纯规则装配和 backbone 回填。

generate_chapters
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
    1. hydrate_source_slices：先按 `source_slices` 精确读取原文行并合并切片摘要，作为本章确定性本地上下文。
    2. retrieve_for_chapter：取 retrieval_queries / priority_section_refs，先本地，资料不足时外部补洞。
       当前模型方案：
         - 子查询规划 `generate_sub_queries` / `generate_gap_queries`
         - `call_purpose=REASONING`
         - `model="reason"`
         - 默认映射到 `qwen-max`
    3. compress_context：读取命中内容并压缩为 dense_context，同时抽取 evidence_units。
       当前模型方案：
         - 当前主要依赖检索、reader、compressor 规则链。
         - 若触发 `research_purify`，使用：
           - `call_purpose=DOCGEN_LIGHT`
           - `model="light"`
           - 默认映射到 `qwen-flash`
    4. extract_claims：基于 ChapterGenerationTask、dense_context 和 CanonicalClaimPool 生成 ClaimLedger。
    5. align_evidence：把 ClaimLedger 映射到 evidence_units，生成 ClaimEvidenceMap 和 EvidenceLedger。
    6. resolve_conflicts：处理定义冲突、记号冲突、来源口径差异和例子冲突。
    7. draft_chapter：基于 resolved claims 和 claim-evidence map 写章节草稿，留下增强占位符。
       当前模型方案：
         - writer 主调用：
           - `call_purpose=DOCGEN`
           - `digest_mode=systematic -> model="reason"`
           - `digest_mode=sprint -> model="primary"`
         - 默认映射到 `qwen-max / qwen-flash`
         - heading repair：
           - `call_purpose=DOCGEN_LIGHT`
           - `model="light"`
           - 默认映射到 `qwen-flash`
    8. critic/rewrite：当前代码仍在单章内做轻量 critic 和最多一次 rewrite；目标上应逐步前移到 review_content。
       当前模型方案：
         - critic 本身是规则判断，不调模型
         - 若触发 rewrite：
           - `call_purpose=DOCGEN`
           - `model="primary"`
           - 默认映射到 `qwen-flash`
  模式差异：sprint/systematic 的核心差异主要在 draft_chapter 体现。
    - sprint：短、密、题型导向，参考突击课常见的“考点/分值感/题型 -> 题眼 -> 最短方法 -> 变式练习 -> 易错辨析”节奏。
    - systematic：长、稳、结构导向，参考系统课常见的“知识地图 -> 定义/性质 -> 推理路径 -> 例题落地 -> 迁移练习 -> 边界回收”节奏。
    - 这些节奏只作为写作建议，不是固定目录；章节标题应由本章内容自然决定。

enhance_chapters
  ├─ enhance_chapter 1
  ├─ enhance_chapter 2
  └─ enhance_chapter N
  输入：ChapterDraft / ClaimLedger / ConfusionMap / placeholder_requests / asset settings / digest_mode
  输出：EnhancedChapterDraft[] / AssetManifest[] / PracticeManifest[]
    - EnhancedChapterDraft：增强后的章节正文。
    - AssetManifest：Mermaid、交互块等资产清单。
    - PracticeManifest：典型例题解析、变式题和迁移练习种子。
  作用：处理 Mermaid、交互 HTML sidecar、公式清洗、例题解析与练习；image 占位会被剥离，不进入发布正文。
  enhance_chapter 内部步骤：
    1. 解析章节中的 Mermaid / interactive 占位符，并清理残留 image 占位。
       当前模型方案：
         - Mermaid 占位生成：
           - `call_purpose=DOCGEN_LIGHT`
           - `model="light"`
           - 默认映射到 `qwen-flash`
         - interactive HTML sidecar：
           - `call_purpose=DOCGEN`
           - `model="primary"`
           - 默认映射到 `qwen-flash`
         - image 当前不走大模型生成正文资产
    2. 对少量高价值章节生成独立、自包含的 HTML 交互页 sidecar，并在 Markdown 中插入新标签页打开链接。
    3. 统一公式、Mermaid、Markdown 结构。
    4. 根据 ClaimLedger、ConfusionMap 和构建约束决定是否追加例题/练习；若正文已有自然练习小节，不重复追加固定标题。
    5. 产出 asset / practice manifest。
  约束：
    - 不大幅改写知识内容。
    - 不修核心定义。
    - 不自行引入新结论。
    - 不改变 claim / evidence 关系。
    - 不把原始 HTML 直接嵌进正文 Markdown。
    - 交互页默认走独立 sidecar 资产，由前端预览页以 sandboxed iframe 打开。

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
  当前模型方案：
    - `review_chapter`
      - `call_purpose=DOCGEN`
      - `model="light"`
      - 默认映射到 `qwen-flash`
    - `document_consistency_review`
      - 当前无 LLM 调用；纯规则一致性检查。

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
    - repair 执行策略已经收口为“按章节并行、章内顺序 patch”：
      - 不同章节的 patch 会并行执行。
      - 同一章节内部仍保持顺序，避免多个 patch 同时改同一份 Markdown。
      - 一旦某章已应用一次实质性 patch，同轮后续 patch 默认跳过；只有 `Markdown 渲染结构异常` 这类确定性表层修补不会锁死该章。
  当前模型方案：
    - `surface_patch / section_patch`
      - `call_purpose=DOCGEN`
      - `model="primary"`
      - 默认映射到 `qwen-flash`
    - `evidence_patch / regenerate_chapter / re_dispatch / rebuild_backbone`
      - 当前只记录，不自动发起新的大模型调用
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
  当前模型方案：
    - 当前无 LLM 调用；纯规则合并和检查。

未来可选 final_merge_patch
  当前状态：不在主图中，当前发布收口由 merge_review + sync_locked_titles 承担。
  设计边界：如果未来新增，只允许修合并后才暴露的小问题，例如目录重复、跨章过渡缺失、重复摘要或 manifest 缺字段。
  明确禁止：重新检索、重写章节、改变 claim / evidence。

sync_locked_titles
  输入：chapter_metadatas / confirmed_plan.chapter_plan / enhanced titles / merge_review_report
  输出：final_chapter_titles / updated chapter_metadatas / title_review_report
  作用：标题收口，保持 chapter_index 和 confirmed plan 映射。
  当前实现：
    - 不调用 LLM，不生成新标题。
    - 只使用 lock_titles_for_chapters 阶段已经锁定的章节标题。
    - 同步改每章 Markdown 一级标题。
    - 重建整本 Markdown。
  约束：只统一标题表达，不推翻用户确认过的章节语义。
  当前模型方案：
    - 当前无 LLM 调用。

publish_document
  输入：merged_markdown / chapter_metadatas / docgen_artifacts / document_context
  输出：markdown files / docgen_manifest.json / KnowledgeDoc rows / version archive
    - docgen_artifacts：DocGenContext、DocumentBackbone、计划、章节、主张、证据、冲突、资产、练习、review 报告。
  作用：发布章节 Markdown、整本 Markdown、manifest、数据库记录和版本归档。
  当前模型方案：
    - 当前无文本 LLM 调用。
    - 若启用了封面 sidecar，会额外走：
      - `agenerate_image(...)`
      - `model="image_generation"`
      - 实际 provider 模型取决于 `settings.models.image_generation`
```

## 2. 当前实现映射

| 目标阶段 | 当前代码对应 | 重构状态 |
| --- | --- | --- |
| `load_context` | `load_context` | 已落地 |
| `prepare_global_seed.infer_intent_core` | `prepare_global_seed` 内部 | 已落地 |
| `prepare_global_seed.summarize_files` | `prepare_global_seed` 内部 | 已落地，已输出 evidence candidates |
| `lock_titles_for_chapters` | `lock_titles_for_chapters` | 已落地 |
| `confirm_and_seed_backbone` | `confirm_and_seed_backbone` | 已落地 |
| `build_document_backbone` | `build_document_backbone` | 已落地，含 fallback backbone |
| `build_chapter_execution_briefs` | `build_chapter_execution_briefs` | 已落地 |
| `assemble_chapter_tasks` | `assemble_chapter_tasks` | 已落地 |
| `generate_draft` | `generate_chapters` | 已落地，已输出 trace / evidence / claim / conflict |
| `enhance` | `enhance_chapters` | 已落地，当前只保留 Mermaid 与交互占位清理 |
| `review_content.review_chapter` | `review_chapter` / `复核章节内容` | 已落地，LangGraph Send x N，LLM review + 规则兜底 |
| `review_content.document_consistency_review` | `document_consistency_review` / `复核整本一致性` | 已落地，章节 review fan-in 后执行 |
| `repair_or_route` | `repair_or_route` | 已落地局部 patch：可执行 surface/section patch；待补 evidence/regenerate 和真实 repair loop |
| `merge_review` | `merge_review` | 已落地 |
| `final_merge_patch` | 无 | 未来可选，不属于当前主图；当前由 `merge_review + sync_locked_titles` 收口 |
| `sync_locked_titles` | `sync_locked_titles` | 已落地，锁定标题同步 + Markdown 一级标题同步；不再 LLM 改标题 |
| `publish_document` | `publish_document` | 已落地，已写 docgen artifacts manifest |

说明：

- 当前主图已切换到“全局轻准备 + 两个单节点内部并行阶段 + 规则装配”的结构，不再让一次 outline enhance 调用承担完整执行大纲生成。
- 过渡期旧节点及配套整本 outline enhancement 代码已移除，避免旧流程和当前主图并存造成误读。

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

- Mermaid、交互占位处理、公式清洗、Markdown 结构，以及按需追加例题/练习。
- 根据 digest mode 和章节合同决定表现层策略；正文表现优先使用标准 Markdown 表格、加粗和 `[!IMPORTANT]` / `[!TIP]` / `[!WARNING]` callout，让前端渲染出清晰的重点、技巧和易错提示；当前不再生成讲义配图。

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

### 4.5 `merge_review` / `sync_locked_titles` / 未来 `final_merge_patch`

`merge_review` 只做发布前收口，不再承担重知识复核。

当前主图没有独立 `final_merge_patch` 节点。发布前小问题先由 `merge_review` 的规则检查和
`sync_locked_titles` 的标题同步收口。

未来如果新增 `final_merge_patch`，它只修合并后才暴露的小问题：

- 目录重复。
- 跨章过渡缺失。
- 重复摘要。
- manifest 缺字段。

`sync_locked_titles` 只执行一次，放在所有 patch 和最终一致性复核之后；它只同步已锁定标题，不再生成新标题。

## 5. 当前重大问题判断

当前没有发现需要立刻推倒重写 DocGen 主图的问题。现有主图已经清晰拆成：

```text
入口合同冻结 -> 全局轻准备 -> 标题锁定 -> 骨架 seed -> 文档骨架
-> 章节 brief -> 章节任务装配 -> 章节生成 Send fan-out
-> 内容增强 -> 章节复核 Send fan-out -> 整本一致性复核
-> 有限局部修补 -> 合并收口 -> 同步锁定标题 -> 发布
```

当前最需要关注的是“继续演进时不要把当前清晰主线弄乱”：

| 优先级 | 关注点 | 为什么重要 |
| --- | --- | --- |
| P1 | repair loop 尚未形成真正闭环 | 当前只能执行局部 patch 并记录重动作 warning；后续如果接入回流，必须先处理 reducer 去重和版本覆盖 |
| P1 | evidence patch 尚未接入 | 证据不足目前只能结构化记录，不能定向补检索、补阅读、补 evidence binding |
| P1 | 回流前的 state reducer 策略 | 引入循环后容易重复发布过期章节、重复 manifest 或重复 review action |
| P1 | 复杂可视化仍是后续方向 | Mermaid 适合结构图，复杂可视化后续应走可交互 HTML/scene 路线 |
| P2 | 未来 `final_merge_patch` | 可选增强，只处理合并后小问题；当前不属于主图 |
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
