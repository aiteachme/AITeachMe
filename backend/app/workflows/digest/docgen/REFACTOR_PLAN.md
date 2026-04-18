# DocGen Deep Research 重构落地计划

最后更新：2026-04-18

本文档是 `FLOW_DESIGN.md` 的执行版。目标不是推翻当前 graph，而是在现有主线上逐步补齐：

```text
load_context
  -> prepare_context
  -> merge_and_dispatch
  -> build_document_backbone
  -> generate_draft
  -> enhance
  -> review_content
  -> repair_or_route
  -> merge_review
  -> finalize_titles
  -> publish_document
```

当前代码仍以 `README.md` 和 `graph.py` 为准。重构按阶段小步落地，每阶段都保持可运行。

## 0. 总原则

- 不让 DocGen 推翻 confirmed plan。
- 不恢复旧 `research_chapters / write_chapters / enrich_assets / append_practice` 顶层节点。
- 不把 Planner 重新变成 research 系统。
- 不新增第二套 search/tool registry。
- 不让 `enhance` 修改核心知识逻辑。
- MVP 先记录回流动作，不自动执行复杂循环。

## 1. 当前基线

当前 graph：

```text
load_context
  -> prepare_parallel_inputs
  -> confirm_and_dispatch
  -> generate_chapters (Send x N)
  -> enhance_chapters
  -> merge_review
  -> publish_document
```

当前核心文件：

```text
graph.py
state.py
nodes/load_context_node.py
nodes/prepare_parallel_inputs_node.py
nodes/confirm_and_dispatch_node.py
nodes/generate_chapters_node.py
nodes/enhance_chapters_node.py
nodes/merge_review_node.py
nodes/publish_document_node.py
lib/models.py
lib/chapter_context.py
lib/chapter_generation.py
lib/chapter_critic.py
lib/chapter_enhancement.py
lib/merge_review.py
lib/publish.py
```

## 2. Phase 1：准备层增强

目标：保持 `prepare_parallel_inputs` 轻量，但让它输出后续构建 backbone 需要的证据候选。

### 需要改的文件

```text
lib/models.py
lib/file_summaries.py
nodes/prepare_parallel_inputs_node.py
prompts/file_summaries.py
```

### 新增或扩展模型

```text
HighConfidenceEvidenceUnit
SourceAffinityByChapter
```

建议字段：

```text
HighConfidenceEvidenceUnit:
  evidence_id
  source_ref
  source_type
  evidence_type
  text
  chapter_affinity
  confidence

SourceAffinityByChapter:
  chapter_index
  file_ids
  section_refs
  reason
```

### 节点输出变化

`prepare_parallel_inputs` 额外输出：

```text
source_affinity_by_chapter
high_confidence_evidence_units
```

### 验收

- 无资料时 fallback 正常。
- 文件摘要失败时仍能输出规则 evidence candidates。
- `compileall` 通过。

## 3. Phase 2：初版派发与 backbone agenda

目标：`confirm_and_dispatch` 不直接产出最终合同，而是先产出 seed 和 backbone research agenda。

### 需要改的文件

```text
lib/models.py
lib/chapter_generation.py
nodes/confirm_and_dispatch_node.py
prompts/outline_enhance.py
```

### 新增模型

```text
ChapterGenerationPlanSeed
ChapterGenerationTaskSeed
BackboneResearchAgenda
```

建议字段：

```text
ChapterGenerationTaskSeed:
  chapter_index
  confirmed_title
  enhanced_title
  chapter_goal
  mode
  required_elements
  forbidden_scope
  retrieval_queries
  priority_section_refs
  preferred_sources
  fallback_policy
  target_length
  style_rules
  citation_policy
  uncertainty_policy
  allowed_assets

BackboneResearchAgenda:
  topics
  section_refs
  evidence_unit_ids
  glossary_candidates
  notation_candidates
  confusion_candidates
```

### 节点输出变化

`confirm_and_dispatch` 输出：

```text
chapter_generation_plan_seed
chapter_task_seeds
backbone_research_agenda
```

`confirm_and_dispatch` 显式消费：

```text
enhanced_chapter_outlines
intent_profile
file_summaries
source_affinity_by_chapter
high_confidence_evidence_units
chapter_assignments
```

当前 `chapter_tasks` 可以先由 seed 兼容生成，避免一次性改 graph。

### 验收

- 当前 `generate_chapters` 仍能消费兼容后的 `chapter_tasks`。
- manifest 暂时可记录 seed。

## 4. Phase 3：新增 build_document_backbone

目标：在初版章节研究范围之后，构建整本文档的稳定语义中心，并回填最终章节合同。

### 需要改的文件

```text
graph.py
state.py
nodes/build_document_backbone_node.py
nodes/__init__.py
lib/models.py
lib/document_backbone.py
prompts/document_backbone.py
README.md
FLOW_DESIGN.md
```

### 新增模型

```text
DocumentBackbone
CanonicalGlossaryItem
ConceptDependencyEdge
NotationItem
CanonicalClaim
ConfusionItem
BackboneConflictWarning
```

建议字段：

```text
DocumentBackbone:
  canonical_glossary
  concept_dependency_graph
  notation_registry
  canonical_claim_pool
  confusion_map
  source_trust_summary

CanonicalClaim:
  claim_id
  claim_type
  claim_text
  target_chapter
  importance
  requires_evidence
  source_hint
```

### Graph 变化

```text
confirm_and_dispatch
  -> build_document_backbone
  -> generate_chapters
```

`build_document_backbone` 输出：

```text
document_backbone
chapter_generation_plan
chapter_tasks
backbone_conflict_warnings
```

### 验收

- 没有本地资料时能基于 seed 和外部策略生成弱 backbone。
- backbone 失败时可回退为 seed 生成的 chapter tasks。
- graph 编译通过。

## 5. Phase 4：强化单章合同

目标：`ChapterGenerationTask` 变成真正的单章执行合同。

### 需要改的文件

```text
lib/models.py
lib/chapter_generation.py
nodes/generate_chapters_node.py
prompts/outline_enhance.py
prompts/common.py
```

### 扩展字段

```text
dependency_refs
forward_refs
claim_targets
concept_targets
confusion_targets
coverage_threshold
evidence_support_threshold
repetition_tolerance
patch_tolerance
```

### 验收

- sprint/systematic 预算仍正确。
- confirmed plan 的章节数量和顺序不被改变。
- task 中保留 confirmed_title 和 enhanced_title。

## 6. Phase 5：单章研究式生成

目标：`generate_chapters` 内部从“检索 + 写”升级为“研究 + 主张 + 证据 + 冲突 + 写”。

### 需要改的文件

```text
lib/models.py
lib/chapter_context.py
lib/claims.py
lib/evidence.py
lib/conflicts.py
lib/writer.py
nodes/generate_chapters_node.py
prompts/claims.py
prompts/common.py
```

### 新增模型

```text
ClaimLedger
ClaimItem
ClaimEvidenceMap
ClaimEvidenceBinding
ConflictReport
ConflictItem
EvidenceUnit
```

### generate_chapter 内部步骤

```text
retrieve_for_chapter
compress_context
extract_claims
align_evidence
resolve_conflicts
draft_chapter
```

### 输出变化

```text
claim_ledgers
claim_evidence_maps
conflict_reports
evidence_ledgers
research_traces
chapter_drafts
```

### 验收

- 单章检索失败时仍 fallback 写作。
- claim/evidence 失败时可以降级为旧 EvidenceLedger。
- writer prompt 不直接吃无限原文。

## 7. Phase 6：限制 enhance 为表现层

目标：`enhance_chapters` 只处理资产、格式、自检，不修核心知识。

### 需要改的文件

```text
lib/chapter_enhancement.py
lib/assets.py
nodes/enhance_chapters_node.py
lib/models.py
```

### 规则

- 允许：Mermaid、图片占位、交互块、公式清洗、自检题、markdown 结构。
- 不允许：修核心定义、新增核心结论、改变 claim/evidence。

### 输出变化

`EnhancedChapterDraft` 保留：

```text
source_scope
claim_ledger_ref
conflict_warning_refs
fallback_used
```

### 验收

- 增强失败时保留原草稿。
- 自检题优先从 ClaimLedger / ConfusionMap 派生。

## 8. Phase 7：review_content 独立化

目标：把当前 `generate_chapters` 内部的 critic/rewrite 移到 enhance 后面，并拆成章节复核和整本一致性复核。

### 需要改的文件

```text
graph.py
state.py
nodes/review_content_node.py
nodes/__init__.py
lib/chapter_review.py
lib/document_consistency.py
lib/models.py
prompts/chapter_review.py
prompts/document_consistency.py
```

### 新增模型

```text
ReviewedChapterDraft
ChapterReviewReport
DocumentConsistencyReport
ReviewAction
```

### Graph 变化

```text
enhance_chapters
  -> review_content
  -> merge_review
```

### ReviewAction 分级

```text
surface_patch
section_patch
regenerate_chapter
re_dispatch
rebuild_backbone
```

MVP：只记录 ReviewAction，不自动回流。

### 验收

- review 失败不阻断发布，记录 warning。
- patch 不破坏增强块。
- document consistency report 进入 manifest。

## 9. Phase 8：repair_or_route

目标：接收 ReviewAction，决定是否 patch、重写或只记录 warning。

### 需要改的文件

```text
graph.py
state.py
nodes/repair_or_route_node.py
lib/repair.py
lib/models.py
```

### MVP 行为

```text
surface_patch：可执行轻量 patch
section_patch：记录为 warning
regenerate_chapter：记录为 warning
re_dispatch：记录为 warning
rebuild_backbone：记录为 warning
```

输出仍回到：

```text
reviewed_chapter_drafts
unresolved_warnings
```

第二版再支持最多一轮有限回流。

## 10. Phase 9：merge_review / finalize_titles / publish

目标：把最重知识复核前移，`merge_review` 只做发布前收口。

### 需要改的文件

```text
nodes/merge_review_node.py
nodes/finalize_titles_node.py
nodes/publish_document_node.py
lib/merge_review.py
lib/publish.py
lib/models.py
```

### Graph 变化

```text
repair_or_route
  -> merge_review
  -> finalize_titles
  -> publish_document
```

### manifest 新增

```text
document_backbone_snapshot
claim_ledgers
claim_evidence_maps
conflict_reports
document_consistency_report
review_actions
unresolved_warnings
source_trust_summary
```

## 11. 测试和验证

每阶段至少做：

```text
conda run -n atm python -m compileall backend/app/workflows/digest/docgen
```

关键阶段额外做：

```text
graph compile smoke test
小资料 sprint 构建
小资料 systematic 构建
无本地资料 web-first fallback
LLM 失败 fallback
manifest 字段检查
```

优先补的测试：

```text
models validate
build_document_backbone fallback
claim/evidence alignment fallback
review_content warning fallback
publish manifest snapshot
```

## 12. 提交拆分建议

```text
feat: 新增 DocGen 文档知识骨架模型
feat: 增加 DocGen 知识骨架构建节点
refactor: 强化 DocGen 章节执行合同
feat: 增加章节主张和证据对齐
refactor: 限制章节增强为表现层处理
feat: 增加 DocGen 内容复核节点
feat: 增加 DocGen 回流动作记录
feat: 扩展 DocGen manifest 追踪信息
```
