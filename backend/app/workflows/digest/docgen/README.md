# DocGen 链路

最后更新：2026-06-15

职责：根据 `confirmed_plan` 生成正式知识文档。

```text
输入: confirmed_plan + shared_inputs + profile + diagnose
输出: KnowledgeDoc + markdown + manifest + graph_sync_status
```

## 主流程

```text
load_context
  -> prepare_global_seed
  -> generate_cover
  -> lock_titles_for_chapters
  -> confirm_backbone_seed
  -> build_document_backbone
  -> build_chapter_execution_briefs
  -> assemble_chapter_tasks
  -> generate_chapters
  -> generate_unit_tests
  -> enhance_chapters
  -> review_chapters
  -> document_consistency_review
  -> repair_or_route
  -> merge_review
  -> sync_locked_titles
  -> prepare_knowledge_graph
  -> publish_document
  -> sync_knowledge_graph
```

## 0. 构建入口

`trigger_docgen_build`

输入：`course_id`, `user_id`, `confirmed_plan_id`

动作：读取 `ConfirmedBuildPlan`；检查文件状态和构建锁；写 docgen `accepted`。

输出：`build_session_id`, background task

`run_docgen_background`

输入：confirmed plan payload, `build_session_id`

动作：标记 `building`；执行 `run_docgen_workflow`；成功写 `completed`，失败写 `failed`。

输出：DocGen final state，可选 KG 同步结果。

## 1. `load_context`

输入：`course_id`, `user_id`, `file_ids`, `user_prompt`, `confirmed_plan`, `digest_mode`, `model_override`

动作：校验 confirmed plan；准备 `shared_inputs`；生成 `chapter_assignments`；读取 `diagnose` 和 Profile；生成 `learner_profile_text`。

输出：`shared_inputs`, `raw_chunks`, `chapter_assignments`, `retrieval_policy`, `learner_profile_context`, `learner_profile_text`, `document_context`, `docgen_context`

关键字段：

```text
document_context.diagnose
document_context.diagnose_status
document_context.diagnose_note
document_context.diagnose_brief
document_context.learner_profile_text
```

## 2. `prepare_global_seed`

输入：`docgen_context`, `chapter_assignments`, `shared_inputs`, `learner_profile_text`

动作：并行执行 `infer_intent_core` 和 `summarize_files`。

输出：`intent_core`, `intent_enhanced`, `file_summaries`, `summary_enhanced`, `user_profile`, `source_affinity_by_chapter`, `high_confidence_evidence_units`

关键字段：

```text
intent_enhanced.learning_goal_text
intent_enhanced.teaching_intent
summary_enhanced.high_confidence_evidence
summary_enhanced.chapter_source_affinity
user_profile.prompt_addendum
```

## 3. `generate_cover`

输入：`course_name`, `intent_enhanced`, `summary_enhanced`

动作：生成可选封面；失败不阻断正文。

输出：`cover_artifact`, `cover_markdown`

## 4. `lock_titles_for_chapters`

输入：`chapter_assignments`, `confirmed_plan`, `intent_enhanced`

动作：按章并行锁定最终标题；只锁标题，不改章节语义。

输出：`locked_titles`

## 5. `confirm_backbone_seed`

输入：`locked_titles`, `chapter_assignments`, `file_summaries`, `source_affinity_by_chapter`, `high_confidence_evidence_units`

动作：不调 LLM；把 confirmed plan 收成骨架种子。

输出：`chapter_generation_plan_seed`, `chapter_task_seeds`, `chapters_enhanced`, `backbone_research_agenda`

`chapters_enhanced[]`：`chapter_index`, `title`, `objective`, `required_elements`, `retrieval_queries`, `source_slices`, `evidence_ids`

## 6. `build_document_backbone`

输入：`chapter_task_seeds`, `summary_enhanced`, `backbone_research_agenda`

动作：生成全文写作骨架和一致性规则。

输出：`document_backbone`, `guideline`, `backbone_conflict_warnings`

`guideline`：`writing_rules`, `canonical_glossary`, `dependency_edges`, `notation_rules`, `confusion_checks`, `claim_count`

## 7. `build_chapter_execution_briefs`

输入：`chapter_task_seeds`, `intent_core`, `document_backbone`, `guideline`, `summary_enhanced`, `user_profile`

动作：按章并行生成 brief，说明每章讲什么、怎么讲、覆盖哪些点；brief fan-in 后可非阻塞启动早期 KG prefetch sidecar。

输出：`chapter_execution_briefs`, `kg_prefetch_status`, `kg_prefetch_ready`

## 8. `assemble_chapter_tasks`

输入：`chapter_execution_briefs`, `chapter_task_seeds`, `summary_enhanced`, `guideline`

动作：生成最终章节任务、资料分配表和写作期 KG 骨架。

输出：`chapter_generation_plan`, `chapter_tasks`, `chapters_enhanced`, `dispatch_table`, `preliminary_kg`

`dispatch_table.items[]`：`chapter_index`, `title`, `source_file_ids`, `source_slices`, `evidence_ids`, `retrieval_queries`, `claim_targets`, `confusion_targets`

`preliminary_kg`：`nodes[]`, `edges[]`。它只做写作参考，不是最终落库图谱。

## 9. `generate_chapters`

输入：`chapter_task`, `guideline`, `dispatch_table`, `summary_enhanced`, `user_profile`

动作：LangGraph `Send` 按章 fan-out；每章检索资料、压缩上下文、生成正文。

输出：`chapter_drafts`, `research_traces`, `claim_ledgers`, `claim_evidence_maps`, `evidence_ledgers`, `conflict_reports`

## 10. `generate_unit_tests`

输入：`chapter_drafts`, `summary_enhanced`

动作：给每章追加单元测试。

输出：`unit_test_chapter_drafts`, `unit_test_items`

## 11. `enhance_chapters`

输入：`unit_test_chapter_drafts`, `intent_profile`, `summary_enhanced`, `preliminary_kg`

动作：增强 Mermaid、静态图、交互 HTML、练习资产；可选用完整章节刷新 KG prefetch sidecar，并保留早期候选。

输出：`enhanced_chapter_drafts`, `asset_manifests`, `practice_manifests`

## 12. `review_chapters`

输入：`enhanced_chapter_draft`, `guideline`, `dispatch_table`, `chapters_enhanced`, `summary_enhanced`, `user_profile`

动作：按章 review 覆盖、证据、结构、练习和风险；同步产出章节级 KG refinement。

输出：`reviewed_chapter_overlay_items`, `chapter_review_report_items`, `review_action_items`, `kg_refinement_items`

## 13. `document_consistency_review`

输入：`reviewed_chapter_overlay_items`, `enhanced_chapter_drafts`, `guideline`, `dispatch_table`

动作：检查全文术语、符号、范围、重复和前置关系。

输出：`reviewed_chapter_drafts`, `document_consistency_report`, `review_decision`, `review_actions`

## 14. `repair_or_route`

输入：`reviewed_chapter_drafts`, `review_actions`, `document_consistency_report`

动作：只修真正的问题；无法安全修的问题写入 warning；无论是否 patch 都用最新 review/repair 上下文刷新 KG prefetch sidecar，patch 成功时追加修补后的 KG refinement。

输出：`reviewed_chapter_drafts`, `repair_trace`, `unresolved_warnings`, `kg_refinement_items`, `kg_prefetch_status`

## 15. `merge_review`

输入：`reviewed_chapter_drafts`, `cover_markdown`

动作：按章节顺序合并整本文档。

输出：`merged_markdown`, `enriched_markdown`, `chapter_metadatas`, `merge_review_report`

## 16. `sync_locked_titles`

输入：`merged_markdown`, `chapter_metadatas`, `locked_titles`

动作：确保最终标题和 `locked_titles` 一致。

输出：`final_chapter_titles`, `title_review_report`, `merged_markdown`, `enriched_markdown`

## 17. `prepare_knowledge_graph`

输入：`chapter_metadatas`, `title_review_report`, `reviewed_chapter_drafts`, `document_backbone`, `preliminary_kg`, `kg_refinement_items`, `build_session_id`

动作：在最终标题同步后、发布前等待或刷新 KG prefetch，并生成 `docgen_kg_draft`。质量门只决定该草稿能否在文档发布后被 fast-finalize 复用，不在此节点写图谱表。

输出：`docgen_kg_draft`, `kg_prefetch_metrics`, `kg_prefetch_ready`, `kg_draft_early_persist_metrics`

质量门会检查章节覆盖、边端点唯一性、关系方向、可考核/画像节点、诊断型节点和结构关系。`kg_draft_early_persist_metrics` 为兼容既有状态结构保留，当前构建固定记录 `deferred_until_document_publish` 且发布前计数为 0。

`KnowledgeUnit`、`KnowledgeEdge`、`KnowledgeGraphSourceRef`、补抽和废弃收口统一由 KnowledgeDoc 发布后的 `sync_knowledge_graph` 完成。因此进程在发布前退出时不会留下本轮 query-visible KG 半成品；`rollback_knowledge_graph` 仅保留旧版 early-persist 状态的兼容清理。

## 18. `publish_document`

输入：`merged_markdown`, `chapter_metadatas`, `intent_enhanced`, `summary_enhanced`, `user_profile`, `chapters_enhanced`, `dispatch_table`, `preliminary_kg`, `docgen_kg_draft`, `kg_draft_early_persist_metrics`, `guideline`

动作：发布 markdown；写 `docgen_manifest`；写 `KnowledgeDoc`；更新课程文档摘要。

输出：`doc_ids`, `built_paths`, `build_group_id`, `merged_path`

## 19. `sync_knowledge_graph`

输入：`doc_ids`, `merged_markdown`, `chapter_metadatas`, `docgen_kg_draft`, `build_session_id`

动作：在同一条 DocGen trace 下运行 KG Doc Sync。若 `docgen_kg_draft` quality-ready 且覆盖最终章节，优先 fast-finalize；否则复用 content hash 命中的 prefetch section，对缺失/变更 section 补抽。

输出：`graph_sync_status`, `graph_sync_metrics`

## Diagnose/Profile 入口

```text
confirmed_plan.diagnose -> diagnose_brief -> learner_profile_text
user.profile_json + course.profile_json -> learner_profile_text -> user_profile.prompt_addendum
```

影响：`chapter_execution_briefs`, `generate_chapters`, `review_chapters`, `document_consistency_review`

## 修改检查

- 新字段进 `state.py`。
- 新 LLM 调用进 `lib/model_policy.py`。
- 批量 LLM 用 `run_llm_tasks(...)`。
- DocGen 不直接写 `KnowledgeUnit/KnowledgeEdge`。
