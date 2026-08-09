# DocGen 链路

最后更新：2026-08-09

职责：根据 `confirmed_plan` 生成正式知识文档。

```text
输入: confirmed_plan + shared_inputs + profile + diagnose
输出: KnowledgeDoc + markdown + manifest + graph_sync_status
```

## 主流程

```text
load_context
  -> [prepare_global_seed || lock_titles_for_chapters]
  prepare_global_seed -> generate_cover ------------------------------┐
  [prepare_global_seed + lock_titles_for_chapters] -> assemble_chapter_tasks
     (内部依次完成 seed 确认、全文骨架、章节 brief 与任务冻结)
  -> generate_chapters
  -> enhance_chapters
  -> review_chapters
  -> document_consistency_review
  -> repair_or_route
  [repair_or_route + generate_cover] -> merge_review <----------------┘
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

动作：从用户确认方案和 `DocGenContext` 直接编译 `intent_core`；依据 confirmed chapters 与解析切片标题/预览做确定性资料路由。这里既不重复理解学习意图，也不再调用 LLM 做文件摘要。

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

动作：生成可选封面；在 `prepare_global_seed` 完成后即启动，与骨架、章节写作、增强和复核并行，只在 `merge_review` 前汇合；失败不阻断正文。

输出：`cover_artifact`, `cover_markdown`

## 4. `lock_titles_for_chapters`

输入：`chapter_assignments`, `confirmed_plan`, `intent_enhanced`

动作：直接采用用户确认方案中的标题并做格式清洗；不再逐章调用 LLM 改写标题。

输出：`locked_titles`

## 5. `confirm_backbone_seed`

以下第 5～8 节是 `assemble_chapter_tasks` 图节点内部的确定性子步骤，不再分别占用四个 LangGraph 节点。

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

动作：从已确认的章节 seed、全文 glossary、claim 和 confusion map 确定性编译 brief，说明每章讲什么、怎么讲、覆盖哪些点；本节点不调用 LLM，也不再对尚未成稿的 brief 启动 KG 抽取。

输出：`chapter_execution_briefs`, `kg_prefetch_status`, `kg_prefetch_ready`

## 8. `assemble_chapter_tasks`

输入：`chapter_execution_briefs`, `chapter_task_seeds`, `summary_enhanced`, `guideline`

动作：生成最终章节任务、资料分配表和写作期 KG 骨架。

输出：`chapter_generation_plan`, `chapter_tasks`, `chapters_enhanced`, `dispatch_table`, `preliminary_kg`

`dispatch_table.items[]`：`chapter_index`, `title`, `source_file_ids`, `source_slices`, `evidence_ids`, `retrieval_queries`, `claim_targets`, `confusion_targets`

`preliminary_kg`：`nodes[]`, `edges[]`。它只做写作参考，不是最终落库图谱。

## 9. `generate_chapters`

输入：`chapter_task`, `guideline`, `dispatch_table`, `summary_enhanced`, `user_profile`

动作：LangGraph `Send` 按章 fan-out；Planner 已预选本地资料切片时，按上下文总预算装入最多四个高相关片段并直接进入 Writer，不再重复查询规划和研究净化；没有可用预选切片时才启动研究 fallback。每章在同一次 Writer 调用中生成正文以及最终 `## 单元测试`。Writer 使用与 Review 相同的语义覆盖算法静默复核 confirmed plan 必需要素，标题层级问题只做确定性规范化和质量标记，不再触发第二次结构重写 LLM。

输出：`chapter_drafts`, `research_traces`, `claim_ledgers`, `claim_evidence_maps`, `evidence_ledgers`, `conflict_reports`

## 10. `enhance_chapters`

输入：`chapter_drafts`, `intent_profile`, `summary_enhanced`, `preliminary_kg`

动作：增强 Mermaid、静态图、交互 HTML、练习资产；Writer 未直接输出 Mermaid 时，使用章节标题与核心知识点构造确定性 mindmap，不再为每章单独调用图示 LLM。KG 抽取延后到章节复核完成，避免增强稿和最终复核稿重复抽取。

输出：`enhanced_chapter_drafts`, `asset_manifests`, `practice_manifests`

## 11. `review_chapters`

输入：`enhanced_chapter_draft`, `guideline`, `dispatch_table`, `chapters_enhanced`, `summary_enhanced`, `user_profile`

动作：按章做确定性覆盖、证据、长度、Markdown 和章末测试结构校验；不再使用常驻的第二次 LLM 语义重审。显式大纲覆盖低于 90% 时生成单章局部补漏动作；轻微逐字匹配提示只记录，不触发模型。每章校验完成后把最终增强稿增量追加到 KG prefetch，并同步产出章节级 KG refinement。

输出：`reviewed_chapter_overlay_items`, `chapter_review_report_items`, `review_action_items`, `kg_refinement_items`

## 12. `document_consistency_review`

输入：`reviewed_chapter_overlay_items`, `enhanced_chapter_drafts`, `guideline`, `dispatch_table`

动作：用规则检查章节数量、重复标题、骨架术语覆盖等跨章合同；不把整本正文再次交给 LLM，也不重启整本 KG prefetch。

输出：`reviewed_chapter_drafts`, `document_consistency_report`, `review_decision`, `review_actions`

## 13. `repair_or_route`

输入：`reviewed_chapter_drafts`, `review_actions`, `document_consistency_report`

动作：先执行确定性的 Markdown 展示修复；仅对 Review 明确判定为低于覆盖门槛的章节执行一次短局部补丁，禁止整章重写、跨章扩写和引入无证据事实。低 evidence binding 只保留证据分数和 warning，不调用模型追加无法改变绑定关系的免责声明；其余复杂语义动作同样只记录。正常章节不增加模型调用，只有正文实际变化的章节才重新增量抽取 KG。

输出：`reviewed_chapter_drafts`, `repair_trace`, `unresolved_warnings`, `kg_refinement_items`, `kg_prefetch_status`

## 14. `merge_review`

输入：`reviewed_chapter_drafts`, `cover_markdown`

动作：按章节顺序合并整本文档。

输出：`merged_markdown`, `enriched_markdown`, `chapter_metadatas`, `merge_review_report`

## 15. `sync_locked_titles`

输入：`merged_markdown`, `chapter_metadatas`, `locked_titles`

动作：确保最终标题和 `locked_titles` 一致。

输出：`final_chapter_titles`, `title_review_report`, `merged_markdown`, `enriched_markdown`

## 16. `prepare_knowledge_graph`

输入：`chapter_metadatas`, `title_review_report`, `reviewed_chapter_drafts`, `document_backbone`, `preliminary_kg`, `kg_refinement_items`, `build_session_id`

动作：在最终标题同步后启动最终 Markdown 的 KG prefetch，立即读取当前缓存快照并生成 `docgen_kg_draft`，不在发布前固定等待；文档发布与剩余抽取并行推进。质量门只决定当前草稿能否在文档发布后被 fast-finalize 复用，不在此节点写图谱表。

输出：`docgen_kg_draft`, `kg_prefetch_metrics`, `kg_prefetch_ready`, `kg_draft_early_persist_metrics`

质量门会检查章节覆盖、边端点唯一性、关系方向、可考核/画像节点、诊断型节点和结构关系。`kg_draft_early_persist_metrics` 为兼容既有状态结构保留，当前构建固定记录 `deferred_until_document_publish` 且发布前计数为 0。

`KnowledgeUnit`、`KnowledgeEdge`、`KnowledgeGraphSourceRef`、补抽和废弃收口统一由 KnowledgeDoc 发布后的 `sync_knowledge_graph` 完成。因此进程在发布前退出时不会留下本轮 query-visible KG 半成品；`rollback_knowledge_graph` 仅保留旧版 early-persist 状态的兼容清理。

## 17. `publish_document`

输入：`merged_markdown`, `chapter_metadatas`, `intent_enhanced`, `summary_enhanced`, `user_profile`, `chapters_enhanced`, `dispatch_table`, `preliminary_kg`, `docgen_kg_draft`, `kg_draft_early_persist_metrics`, `guideline`

动作：发布 markdown；写 `docgen_manifest`；写 `KnowledgeDoc`；更新课程文档摘要。

输出：`doc_ids`, `built_paths`, `build_group_id`, `merged_path`

## 18. `sync_knowledge_graph`

输入：`doc_ids`, `merged_markdown`, `chapter_metadatas`, `docgen_kg_draft`, `build_session_id`

动作：review 与 repair 阶段只沉淀 KG refinement，不再对尚未锁定的章节重复抽取。最终 Markdown 锁定后用准确的发布 payload 启动唯一一次 KG 预取；无拓扑依赖的 section 一次并发抽取。正式同步消费缓存时会等待最终预取的有界重试窗口；若仍需取消后台任务，会先确认请求已经退出，再做 catch-up，避免同一 section 被后台与正式同步重复调用。文档发布后，KG Doc Sync 与课程向量索引检查并行启动：前者复用最终预取并正式固化，后者在运行时允许写入但索引缺失时自动补建并复验；仍不可查询则明确失败，避免假成功后伴读长期降级。

输出：`graph_sync_status`, `graph_sync_metrics`, `vector_index_status`, `vector_index_chunk_count`

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
