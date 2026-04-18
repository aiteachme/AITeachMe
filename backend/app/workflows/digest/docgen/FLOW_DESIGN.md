# DocGen 流程设计

最后更新：2026-04-19

这份文档描述 `digest/docgen` 的当前流程和目标演进。当前实现以 `graph.py`、`state.py`、`nodes/`、`lib/models.py` 为准；本文用于解释节点边界、输入输出合同和后续重构方向。

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

## 1. 当前总流程

当前代码主线：

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

等价产品语义：

```text
读取确认方案
  -> 准备写作上下文
  -> 生成章节执行合同
  -> 建立整本知识骨架
  -> 按章研究和写草稿
  -> 增强 Markdown / 图示 / 自检
  -> 复核章节和整本一致性
  -> 安全修补或记录 warning
  -> 合并并检查发布产物
  -> 收口标题
  -> 发布文件、manifest 和数据库记录
```

## 2. 完整输入输出合同

这里写的是 workflow state 层面的合同，不是 HTTP API schema。真实字段以 `state.py`、`lib/models.py` 和各节点返回值为准。

### 2.1 `load_context`

输入：

- `confirmed_plan`：用户确认后的构建合同，包含 `user_goal`、`digest_mode`、`chapter_plan`、`plan_summary`、`plan_steps`、`planner_context`。
- `shared_inputs`：资料理解包；如果上游没传入，则根据 `subject` / `file_ids` / `user_prompt` 重新准备。
- `file_ids` / `user_prompt` / `planner_session_id` / `confirmed_plan_id`。

处理：

- 校验 `confirmed_plan`，没有章节合同时直接失败。
- 解析 `digest_mode`、`course_type`、`retrieval_profile`。
- 从 confirmed plan 固化 Planner 上下文，不在 DocGen 重新决定模式。
- 生成 `document_context` 和 `DocGenContext`，供写作、发布、manifest 共用。
- 初始化构建状态与章节进度。

输出：

- `shared_inputs`
- `raw_chunks`
- `subject_profile`
- `confirmed_plan`
- `chapter_assignments`
- `docgen_context`
- `document_context`
- `digest_mode`
- `course_type`
- `retrieval_profile`

### 2.2 `prepare_parallel_inputs`

并行子任务：

```text
enhance_plan_outline
infer_docgen_intent
summarize_files
```

输入：

- `docgen_context`：主题、目标、模式、Planner 摘要、历史修改、资料统计。
- `confirmed_plan` / `chapter_assignments`：用户确认过的章节合同。
- `shared_inputs`：`source_packets`、`section_packets`、`material_profile`。

处理：

- `enhance_plan_outline`：把用户确认的大纲增强成执行级小纲，不新增、不删除、不重排章节。
- `infer_docgen_intent`：识别深度、考试倾向、例子偏好、定义粒度和避让项。
- `summarize_files`：总结文件，推断章节亲和度，抽取高置信证据候选。
- `derive_source_affinity_and_evidence`：从资料和摘要中派生章节来源亲和度与证据候选。

输出：

- `enhanced_chapter_outlines`
- `intent_profile`
- `file_summaries`
- `source_affinity_by_chapter`
- `high_confidence_evidence_units`
- `plan_mismatch_warnings`
- `prepare_ms`

### 2.3 `confirm_and_dispatch`

目标阶段名：`merge_and_dispatch`。当前代码节点名：`confirm_and_dispatch`。

输入：

- `docgen_context`
- `enhanced_chapter_outlines`
- `intent_profile`
- `file_summaries`
- `source_affinity_by_chapter`
- `high_confidence_evidence_units`
- `chapter_assignments`
- `plan_mismatch_warnings`

处理：

- 合并 prepare 阶段三路结果。
- 生成 `ChapterGenerationPlan` / `ChapterGenerationTask` 兼容合同。
- 生成 `ChapterGenerationPlanSeed` / `ChapterGenerationTaskSeed`。
- 生成 `BackboneResearchAgenda`，供整本知识骨架使用。
- 计算初始章节预算、来源优先级、写作规则、媒体占位请求。

输出：

- `chapter_generation_plan_seed`
- `chapter_task_seeds`
- `backbone_research_agenda`
- `chapter_generation_plan`
- `chapter_tasks`
- `dispatch_ms`

### 2.4 `build_document_backbone`

输入：

- `chapter_generation_plan_seed`
- `chapter_task_seeds`
- `backbone_research_agenda`
- `file_summaries`
- `high_confidence_evidence_units`

处理：

- 构建整本文档的术语表、概念依赖、符号表、核心主张池和易混点。
- 生成 `source_trust_summary`。
- 如果资料或模型不足，fallback 为基于章节 seed 的弱骨架。
- 将 backbone 回填到章节任务，形成最终执行合同。

输出：

- `document_backbone`
- `chapter_generation_plan`
- `chapter_tasks`
- `backbone_conflict_warnings`
- `backbone_ms`

### 2.5 `generate_chapters`

目标阶段名：`generate_draft`。当前代码节点：`generate_chapters`，通过 LangGraph `Send x N` 按章并行。

输入：

- 单章 `chapter_task`
- `total_chapters`
- `shared_inputs.section_packets`
- `docgen_context`
- `document_backbone`
- `digest_mode`
- `course_type`
- `retrieval_profile`

处理：

- `DocGenChapterContextRuntime.run`：按章节预算执行本地 RAG、外部检索、gap queries、网页读取和上下文压缩。
- `build_evidence_ledger`：从 dense context 和 source details 中构建证据账本。
- `build_claim_ledger`：结合章节合同和 `DocumentBackbone` 生成主张账本。
- `align_claim_evidence`：将主张映射到证据。
- `resolve_conflicts_for_chapter`：记录定义、符号、来源口径和例子冲突。
- `DocGenWriterRuntime.run`：基于 dense context、claim/evidence 和冲突提示写章节草稿。
- `critique_chapter` / `maybe_rewrite_chapter`：当前仍在单章内做轻量 critic 和最多一次 rewrite。

输出：

- `chapter_drafts`
- `research_traces`
- `evidence_ledgers`
- `claim_ledgers`
- `claim_evidence_maps`
- `conflict_reports`
- `research_sources`
- `research_ms`
- `draft_ms`
- `llm_calls_total`

### 2.6 `enhance_chapters`

目标阶段名：`enhance`。

输入：

- `chapter_drafts`
- `claim_ledgers`
- `document_backbone`
- `digest_mode`
- asset settings

处理：

- 并发增强所有章节草稿。
- 处理 Mermaid 内部请求，生成 Mermaid markdown 或 fallback。
- 清理 image / interactive 内部占位。
- 清洗公式、校验 LaTeX、规范 Markdown 结构。
- 从 `ClaimLedger` / `DocumentBackbone.confusion_map` 派生本章自检题。
- 当前不应引入新的核心定义、结论或证据主张。

输出：

- `enhanced_chapter_drafts`
- `asset_manifests`
- `practice_manifests`
- `enhance_ms`

注意：

- 图片生成未启用时，当前代码更偏向移除 image 请求；目标上应在 `AssetManifest` 中显式记录 `disabled`，避免 manifest 无法解释降级。

### 2.7 `review_content`

输入：

- `enhanced_chapter_drafts`
- `chapter_tasks`
- `document_backbone`
- `claim_ledgers`
- `claim_evidence_maps`
- `conflict_reports`
- `intent_profile`

处理：

- `review_chapter`：检查单章合同覆盖、证据支撑、质量信号、长度和冲突风险。
- `review_document_consistency`：检查章节数量、重复标题、骨架术语覆盖和整本来源摘要。
- 只做判断，不检索、不打开网页、不调工具、不改正文。

输出：

- `reviewed_chapter_drafts`
- `chapter_review_reports`
- `document_consistency_report`
- `review_actions`
- `review_ms`

当前缺口：

- 还没有显式 `review_decision` 字段。
- `ReviewAction` 只能粗分 `surface_patch`、`section_patch`、`regenerate_chapter`、`re_dispatch`、`rebuild_backbone`，尚不能直接驱动定向修补。

### 2.8 `repair_or_route`

输入：

- `reviewed_chapter_drafts`
- `review_actions`

当前处理：

- 对 `surface_patch` 标记 `applied`。
- 对 `section_patch`、`regenerate_chapter`、`re_dispatch`、`rebuild_backbone` 记录为 unresolved warning。
- 不自动重新检索、不重写章节、不回到 `review_content`。

输出：

- `reviewed_chapter_drafts`
- `review_actions`
- `unresolved_warnings`
- `repair_ms`

当前缺口：

- `surface_patch` 的状态语义偏乐观，因为当前没有真正修改正文。
- 尚无 `RepairLoopState`、`repair_trace`。
- 尚未实现 `review_content <-> repair_or_route` 的最多两轮闭环。

### 2.9 `merge_review`

输入：

- `reviewed_chapter_drafts`；为空时 fallback 到 `enhanced_chapter_drafts`。
- `chapter_generation_plan`
- `document_backbone`
- `claim_ledgers`
- `claim_evidence_maps`
- `conflict_reports`
- `chapter_review_reports`
- `document_consistency_report`
- `review_actions`
- `unresolved_warnings`

处理：

- 按 `chapter_index` 去重和排序。
- 构造 `chapter_metadatas`，收口 manifest 字段。
- 合并整本 Markdown。
- 做发布前完整性检查：章节数、标题重复、质量低分、缺来源等。

输出：

- `chapter_metadatas`
- `merged_markdown`
- `enriched_markdown`
- `merge_review_report`
- `merge_review_ms`

### 2.10 `final_merge_patch`

当前状态：目标节点，尚未独立实现。

目标输入：

- `merged_markdown`
- `chapter_metadatas`
- `merge_review_report`
- `unresolved_warnings`

目标处理：

- 只修合并后才暴露的小问题，例如目录重复、跨章过渡、重复摘要、manifest 缺字段。
- 不重新检索、不重写章节、不改变 claim/evidence。

目标输出：

- `merged_markdown`
- `chapter_metadatas`
- `final_merge_patch_report`

### 2.11 `finalize_titles`

输入：

- `chapter_metadatas`
- `chapter_assignments`
- `merged_markdown`
- `merge_review_report`

处理：

- 统一标题表达。
- 保持 `chapter_index` 和 confirmed plan 映射。
- 不推翻用户确认语义。
- 重新生成整本 `merged_markdown`。

输出：

- `chapter_metadatas`
- `merged_markdown`
- `enriched_markdown`
- `final_chapter_titles`
- `title_review_report`
- `finalize_ms`

### 2.12 `publish_document`

输入：

- `chapter_metadatas`
- `chapter_assignments`
- `document_context`
- `merged_markdown`
- `docgen_artifacts`

处理：

- 写入 `_build` 章节 Markdown、`_build/merged_knowledge_base.md`、`_build/docgen_manifest.json`。
- 发布当前章节 Markdown、`merged_knowledge_base.md`、`docgen_manifest.json`。
- 写入版本归档。
- 写入 `KnowledgeDoc` rows。
- 写入知识文档 manifest 和构建状态。

输出：

- `doc_ids`
- `built_paths`
- `merged_markdown`
- `user_prompt`
- `finalize_ms`

## 3. 当前实现映射

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
| `review_content.review_chapter` | `review_content` 内部 | 已落地 |
| `review_content.document_consistency_review` | `review_content` 内部 | 已落地 |
| `repair_or_route` | `repair_or_route` | 已落地 MVP：记录或标记轻动作；待补真实 repair loop |
| `merge_review` | `merge_review` | 已落地 |
| `final_merge_patch` | 无 | 待新增，只处理合并后小问题 |
| `finalize_titles` | `finalize_titles` | 已落地 |
| `publish_document` | `publish_document` | 已落地，已写 docgen artifacts manifest |

## 4. 有限回流目标设计

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

### 4.1 推荐新增 `RepairLoopState`

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

### 4.2 推荐扩展 `ReviewAction`

当前 `ReviewAction` 只有 action 类型、章节、严重度、原因和状态。目标结构：

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

### 4.3 修补动作分层

- `no_action`：复核通过，直接进入 `merge_review`。
- `surface_patch`：修标题层级、重复句、过渡句、Markdown 轻微问题；不得新增知识。
- `section_patch`：只改局部小节；不得改变章节边界、核心定义和 claim/evidence 对应关系。
- `evidence_patch`：针对缺口补检索、打开网页、压缩正文、补证据，再做局部改写；必须记录新来源、read_url_count、snippet fallback。
- `regenerate_chapter`：只重写问题章节。重写后必须重新经过 enhance 和 review。
- `record_only`：问题太大、证据不足、会推翻 confirmed plan 或超过预算时，只写 warning。
- `re_dispatch` / `rebuild_backbone`：第一版只记录，不自动执行；后续如果支持，也必须回到明确的计划确认或全局重建流程。

### 4.4 循环前必须先解决的 state 问题

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

## 5. 节点能力边界

### 5.1 `generate_chapters`

可以：

- 本地 RAG、文件切片读取、外部检索、网页打开、上下文压缩。
- 根据 confirmed plan、digest mode、planner context 和章节缺口决定检索重点。
- 生成 dense context、research trace、evidence ledger、claim ledger、conflict report 和章节草稿。

不能：

- 修改 confirmed plan 的章节数量、顺序和用户确认语义。
- 做标题最终收口。
- 把未打开或未压缩的搜索标题当作正文证据。

### 5.2 `enhance_chapters`

可以：

- Mermaid、图片请求降级、交互占位处理、公式清洗、Markdown 结构和本章自检。
- 根据 asset settings、digest mode 和章节合同决定表现层策略。

不能：

- 引入新的核心定义、结论、例题口径或证据主张。
- 改变 claim / evidence 对应关系。

### 5.3 `review_content`

可以：

- 逐章复核合同覆盖、证据支撑、章节边界和质量信号。
- 复核跨章术语、标题、前置关系、重复和风格一致性。
- 产出 `ReviewAction`、`DocumentConsistencyReport` 和后续路由判定。

不能：

- 检索、打开网页、调用工具。
- 直接 patch 正文。

### 5.4 `repair_or_route`

可以：

- 读取 `ReviewAction`，按严重度和预算执行 patch、补证据、重写或记录 warning。
- 调用检索、reader、writer 等工具，但必须写入 `repair_trace`。

不能：

- 无限循环。
- 静默推翻 confirmed plan。
- 在没有本地资料、已打开网页正文或明确 snippet fallback 的情况下补新断言。

### 5.5 `merge_review` / `final_merge_patch` / `finalize_titles`

`merge_review` 只做发布前收口，不再承担重知识复核。

`final_merge_patch` 只修合并后才暴露的小问题：

- 目录重复。
- 跨章过渡缺失。
- 重复摘要。
- manifest 缺字段。

`finalize_titles` 只执行一次，放在所有 patch 和最终一致性复核之后。

## 6. 当前重大问题判断

当前没有发现需要立刻推倒重写 DocGen 主图的问题。主线已经接近目标设计，重要能力也基本落点清楚。

值得后续重构的重点是：

| 优先级 | 问题 | 为什么重要 |
| --- | --- | --- |
| P0 | 文档与代码漂移 | 新人会按旧 README / 旧架构评估理解当前 graph，后续改动容易补错位置 |
| P1 | repair loop 还没形成闭环 | 复核只能记录，不能真正按问题级别修补 |
| P1 | `ReviewAction` 合同不足 | 无法驱动定向 patch、补证据和局部重写 |
| P1 | state append reducer 与回流不兼容 | 引入循环后容易重复发布旧章节或重复 manifest |
| P1 | image disabled manifest 缺失 | 用户和后续系统看不到图片降级原因 |
| P2 | `final_merge_patch` 未实现 | 合并后小问题只能靠人工或间接收口 |
| P2 | research budget 仍偏静态 | 还没充分根据覆盖度、证据缺口和章节难度动态调度 |

## 7. 近期不要做

- 不把 DocGen 改成完整多 Agent 动态队列。
- 不让 DocGen 自动推翻 confirmed plan。
- 不把 Planner 重新变成 research 系统。
- 不恢复独立 prompt 扩展层。
- 不新建第二套 search/tool registry。
- 不让 `enhance_chapters` 修核心知识逻辑。
- 不把所有原文一次性塞进 writer prompt。
- 不随便给文档型 helper 补测试，除非它已经成为稳定核心合同。

## 8. 一句话收束

```text
DocGen 的核心不是把章节写出来，
而是在确认方案上补齐知识骨架、主张证据、冲突消解和有限复核，
让最终文档可读、可追踪、可修补、可被其他引擎复用。
```
