## 附录 A：当前已落地的核心合同

> 说明：以下以“当前代码已经存在的核心结构”为主，只在必要处补充下一步值得增强的字段。

### A.1 `DigestConfirmedPlanContract`

当前 canonical confirmed plan 合同位于：

- `backend/app/workflows/digest/shared/contracts.py`

它当前已经覆盖：

- `subject`
- `user_goal`
- `digest_mode`
- `tone`
- `selected_skillpacks`
- `chapter_plan`
- `research_queries`
- `media_plan`
- `build_constraints`
- `plan_summary`
- `selected_file_ids`
- `planner_session_id`
- `confirmed_plan_id`
- `mode_reason`

结论：confirmed plan 已经不是松散 JSON，而是 DocGen 真正可消费的 typed contract。

### A.2 `DigestChapterContract` / `DigestChapterExecutionContract`

当前 chapter-level 合同已经拆成两层：

- `DigestChapterContract`
- `DigestChapterExecutionContract`

关键字段包括：

- `chapter_index`
- `title`
- `resolved_title`
- `objective`
- `required_elements`
- `search_queries`
- `writing_instructions`
- `media_hints`
- `execution_contract`
- `source_file_ids`

而 execution contract 当前已经覆盖：

- `target_word_count`
- `min_word_count`
- `coverage_requirements`
- `min_coverage_score`
- `explanation_depth`
- `repair_enabled`
- `quality_hint`
- `media_quota`
- `practice_quota`

结论：模式差异和章节质量约束已经进入 execution contract，而不是只存在于 prompt 文本。

### A.3 `DocGenState` 关键字段

当前 DocGen lane state 位于：

- `backend/app/workflows/digest/docgen/state.py`

其中最关键的结构化字段已经包括：

- 基础输入：`subject / file_ids / build_session_id / planner_session_id / confirmed_plan_id`
- 模式与策略：`digest_mode / course_type / retrieval_profile / teaching_action / tone`
- skillpack：`selected_skillpacks / document_context`
- 中间产物：`chapter_assignments / chapter_materials / chapter_drafts / chapter_metadatas / exam_questions`
- 富媒体与练习：`mermaid_block_count / image_block_count / interactive_block_count / asset_count / asset_summary / practice_count`
- 最终产物：`merged_markdown / enriched_markdown / doc_ids / built_paths`
- 可观测性：`load_ms / research_ms / draft_ms / enrich_ms / examine_ms / finalize_ms / timing_summary / token_summary`

结论：DocGen state 已经能承载“研究、写作、富媒体、练习、发布、统计”这几类产物，不再只是纯 markdown 中转。

---

## 附录 B：DocGen research runtime 当前 metadata

当前 `DocGenChapterContextRuntime` 已经输出的关键 metadata 包括：

- `base_queries`
- `planned_queries`
- `gap_queries`
- `executed_queries`
- `fallback_queries`
- `requested_profile`
- `applied_profile`
- `configured_retrievers`
- `active_retrievers`
- `retriever_stats`
- `research_rounds`
- `research_round_count`
- `coverage_score`
- `gaps_remaining`
- `source_class_breakdown`
- `stop_reason`
- `selected_skillpacks`
- `recommended_tool_tags`

结论：research 已经具备足够强的运行时摘要与追踪输入，下一步重点是调优这些字段背后的算法，而不是继续补基础观测面。

---

## 附录 C：Digest lane summary 当前可聚合字段

当前 `backend/app/workflows/digest/observability.py` 已经能聚合：

### Docs Lane

- `selected_skillpacks`
- `retrieval_profiles`
- `teaching_actions`
- `requested_profiles / applied_profiles`
- `research_rounds / research_round_count_total / max_research_round_count`
- `source_class_breakdown`
- `mermaid_count / image_count / interactive_block_count / asset_count / asset_summary`
- `practice_count`
- `coverage_score / quality_score`

### KG / Curriculum Lane

- 各步骤耗时
- 节点 / 单元数量
- token summary
- slow item top-k

结论：Digest observability 文件当前的职责应该理解为 lane summary / timing report，而不是重新定义第二套 tracing API。

---

## 附录 D：当前关键实现位置

| 能力 | 当前文件 |
| --- | --- |
| confirmed plan / chapter contract | `backend/app/workflows/digest/shared/contracts.py` |
| planner graph | `backend/app/workflows/digest/planner/graph.py` |
| docgen graph | `backend/app/workflows/digest/docgen/graph.py` |
| chapter research runtime | `backend/app/workflows/digest/docgen/runtime/chapter_context.py` |
| writer runtime | `backend/app/workflows/digest/docgen/runtime/writer.py` |
| asset sidecar runtime | `backend/app/workflows/digest/docgen/runtime/assets.py` |
| docgen prompts | `backend/app/workflows/digest/prompts/docgen_prompts.py` |
| planner prompts | `backend/app/workflows/digest/prompts/planner_prompts.py` |
| teaching scaffold | `backend/app/teaching/documents/report_generation.py` |
| search factory / retrievers | `backend/app/shared/infra/search/*` |
| tracing 统一入口 | `backend/app/workflows/common/*` |
| Digest lane summary | `backend/app/workflows/digest/observability.py` |

---

## 附录 E：下一批值得显式化、但当前还不必伪装成已实现的字段

下面这些方向值得继续做，但当前不要写成“已经落地”：

- 学科特定 retrieval profile 参数表
- 更细的 gap 类型分类
- richer interactive / image asset contract
- animation 执行合同
- 跨引擎共享的学习画像合同
- 更强的章节级质量评分拆解

---

## 附录 F：当前最小检查表

- confirmed plan 是否始终以 typed contract 进入 DocGen
- `selected_skillpacks` 是否保持 planner -> confirmed plan -> docgen 一致
- `retrieval_profile` 是否真实影响 retriever 工厂，而不只是 trace 文本
- `research_rounds / coverage_score / gaps_remaining` 是否能从 trace 和 lane summary 看到
- `asset_summary / practice_count` 是否进入最终 summary
- `animation` 是否仍明确标注为预留位，而不是已落地能力