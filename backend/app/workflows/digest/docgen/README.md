# DocGen 链路

最后更新：2026-10-22

职责：根据 `confirmed_plan` 生成正式知识文档。

用户明确的数量合同与模式默认密度分开保存：`quantity_constraints` 和互不重叠的 `chapter_end_practice_plan.question_count` 是生成、复核、修补和发布的统一依据。明确题数不受默认覆盖计划长度限制，不能因题量较大而填空或回退默认题数。章末测试按每批最多 12 题生成并独立复核，题数同时进入输出 JSON Schema 的 `minItems`/`maxItems`，少题响应使用共享结构化校验反馈修复。当前批次的数量与全章背景合同分开传递，保持所有题组的数量、题型和用途，携带已验收题目避免跨批重复；合并后统一编号、核验总量与题型配额，只发布一个单元测试模块。按章 fan-out 必须传递真实 `total_chapters`，多章时不得把全课程文本中抽取到的单个题量套到当前章。

进入 DocGen 表示用户已确认方案并开始正式构建。历史对话中的“先规划、暂不构建”是之前的操作阶段要求，不能变成永久禁止生成正文的内容合同；主题、章数、数量、资料和联网限制继续有效。

超过单批规模的有效章末测试采用结构化逐题修补：模型只返回已有题号及该题内容，程序渲染被修改题并逐字保留其它题，不让模型为修几题重写整份题组。修补上下文保留完整题目，修复器负责自行复算并直接返回最终内容；修补后不再启动第二个模型复审。程序继续保证替换位置、完整题数、题型配额、分组顺序与题答协议。

```text
输入: confirmed_plan + shared_inputs + profile + diagnose
输出: KnowledgeDoc + markdown + manifest + graph_sync_status
```

## 主流程

```text
load_context
  -> [prepare_global_seed || lock_titles_for_chapters]
  prepare_global_seed -> generate_cover ------------------------------┐
  [prepare_global_seed + lock_titles_for_chapters] -> confirm_and_seed_backbone
  -> build_document_backbone
  -> [build_chapter_execution_brief × N]
  -> assemble_chapter_tasks
  -> [generate_chapters × N]
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

动作：从用户确认方案和 `DocGenContext` 直接编译 `intent_core`；复用 Ingest 已解析的 section、摘要和 Planner 的章节合同做资料路由。这里既不重复理解学习意图，也不再调用 LLM 做整份文件摘要；资料的教学解释发生在每章 Writer 中。

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

输入：`locked_titles`, `chapter_assignments`, `file_summaries`, `source_affinity_by_chapter`, `high_confidence_evidence_units`

动作：不调 LLM；把 confirmed plan 收成骨架种子。

输出：`chapter_generation_plan_seed`, `chapter_task_seeds`, `chapters_enhanced`, `backbone_research_agenda`

`chapters_enhanced[]`：`chapter_index`, `title`, `objective`, `required_elements`, `retrieval_queries`, `source_slices`, `evidence_ids`

## 6. `build_document_backbone`

输入：`chapter_task_seeds`, `summary_enhanced`, `backbone_research_agenda`

动作：用一次整本结构化 LLM 调用只生成 `DocumentBackbone`，统一跨章术语、符号、关键主张、真实前置关系与易混点。它不再携带全部章节 brief，避免一个长输出把各章准备串成整本瓶颈；模型失败时明确降级为空语义骨架，不用关键词或 required elements 拼造教学语义。

输出：`document_backbone`, `guideline`, `backbone_conflict_warnings`

`guideline`：`writing_rules`, `canonical_glossary`, `dependency_edges`, `notation_rules`, `confusion_checks`, `claim_count`

## 7. `build_chapter_execution_briefs`

输入：`chapter_task_seeds`, `document_backbone`, `summary_enhanced`, `learner_profile_text`

动作：LangGraph `Send` 为每章启动一个独立分支，并行生成该章专属 brief，说明怎样讲、怎样举例、怎样练习、怎样使用资料和检索证据；各分支共享整本骨架但只读取本章 seed 和本章资料，任何一章模型失败都只降级为该章 seed 级 brief，不阻断其它章节。

输出：各分支写入 reducer 字段 `chapter_execution_brief_items`；fan-in 后由 `assemble_chapter_tasks` 排序并冻结为 `chapter_execution_briefs`

## 8. `assemble_chapter_tasks`

输入：`chapter_execution_briefs`, `chapter_task_seeds`, `summary_enhanced`, `guideline`

动作：生成最终章节任务、资料分配表和写作期 KG 骨架。

输出：`chapter_generation_plan`, `chapter_tasks`, `chapters_enhanced`, `dispatch_table`, `preliminary_kg`

`dispatch_table.items[]`：`chapter_index`, `title`, `source_file_ids`, `source_slices`, `evidence_ids`, `retrieval_queries`, `claim_targets`, `confusion_targets`

`preliminary_kg`：`nodes[]`, `edges[]`。它只含 confirmed chapter 对应的结构 `topic`，不根据 required elements、教学活动、brief 或关键词生成概念/技能/误区节点，也不是最终落库图谱。

## 9. `generate_chapters`

输入：`chapter_task`, `guideline`, `dispatch_table`, `summary_enhanced`, `user_profile`

动作：LangGraph `Send` 按章 fan-out；各章 brief 已生成至多 `docgen.max_retrieval_queries_per_chapter` 条检索词，章节节点不再重复调用 LLM 改写查询。本地资料检索与有限在线校准并行执行，不因 Planner 已预选资料切片或本地命中充足而跳过在线尝试；随后把预选切片、本地结果和在线结果统一筛选、读取、压缩后交给 Writer。Writer 只生成完整知识正文；同一章节分支随后读取全文，由轻量模型生成题目初稿，再由主模型逐题独立复算答案与解析并返回完整题组；初稿结构不合格时也由该复核调用补全一次。唯一渲染器只发布复核后的 `## 单元测试` 和 QUESTION/ANSWER 配对。各章之间仍然并行，不依赖字符匹配推断教学语义。仅当 `docgen.allow_external_search=false`、没有可用在线 retriever 或外部服务失败时不产生在线结果。

输出：`chapter_drafts`, `research_traces`, `claim_ledgers`, `claim_evidence_maps`, `evidence_ledgers`, `conflict_reports`

## 10. `enhance_chapters`

输入：`chapter_drafts`, `intent_profile`, `summary_enhanced`, `preliminary_kg`

动作：增强 Writer 已请求的 Mermaid、静态图、交互 HTML 和练习资产；确定性逻辑只解析/校验资产协议与渲染格式，不用章节标题或关键词补造教学图示。全部增强稿就绪后先应用与发布相同的 Markdown 规范化，再用整本内容启动一次 KG LLM prefetch；该后台批次遵守 `knowledge_graph.prefetch_concurrency` 局部上限，与后续按章复核、跨章检查和必要格式修补并行运行，避免占满全局 LLM 槽。

输出：`enhanced_chapter_drafts`, `asset_manifests`, `practice_manifests`, `kg_prefetch_status`

## 11. `review_chapters`

输入：`enhanced_chapter_draft`, `guideline`, `dispatch_table`, `chapters_enhanced`, `summary_enhanced`, `user_profile`

动作：按章做确定性的证据、长度、Markdown 和章末测试协议校验；题答区必须是唯一且最终的 `## 单元测试`，QUESTION/ANSWER 严格交替，选择题必须有 A-D，非选择题不得有选项，答案和解析不得游离或重复。不再使用常驻的第二次 LLM 语义重审，也不以关键词、n-gram 或正则命中率判断语义覆盖并触发补写。复核只同步产出章节结构 topic refinement，不重复启动 KG 抽取。

输出：`reviewed_chapter_overlay_items`, `chapter_review_report_items`, `review_action_items`, `kg_refinement_items`

## 12. `document_consistency_review`

输入：`reviewed_chapter_overlay_items`, `enhanced_chapter_drafts`, `guideline`, `dispatch_table`

动作：先用规则检查章节数量、重复标题、骨架术语覆盖等跨章合同，再用一个局部 LLM 槽做一次整本结构化复核，只输出确有影响的问题和可立即执行的局部修复动作，不改写正文。跨章问题按受影响的小节拆开；观察项不能作为无法执行的 error 动作阻断发布。审核服务不可用时记录调用异常并保留规则结果，不将服务异常虚构为正文错误；已经发现的真实结构错误仍须修复。增强阶段启动的 KG prefetch 同时继续按 section 并行运行，不在此重启。

输出：`reviewed_chapter_drafts`, `document_consistency_report`, `review_decision`, `review_actions`

## 13. `repair_or_route`

输入：`reviewed_chapter_drafts`, `review_actions`, `document_consistency_report`

动作：执行确定性的 Markdown 展示修复，对缺少/损坏的章末测试、正文显著低于字数合同，以及结构化复核明确标记的 `error` 执行局部修复，紧凑模式也不跳过正确性错误。有明确目标章的错误无论动作标签如何都进入实际修复，不能仅记录后留到发布节点失败。正文纠错支持原位 `replace_text` 和现有小节 `replace_section`，避免旧错解和新答案并存。测试修补依据显式目标标题或规则动作 ID 路由；有效大题组按题号替换，其余情况替换完整测试模块。修复器直接输出完成纠错的内容，程序只负责定位、结构、数量与渲染检查，不再调用模型复审或引入新的语义否决。无效输出或临时调用失败按具体反馈在同一目标内最多尝试三次，不丢弃其它目标已完成的修改。其它语义内容不因关键词覆盖率触发补写。低 evidence binding 只保留证据分数和 warning。正文实际变化的 section 由最终 KG 同步按内容哈希补抽。

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

动作：在最终标题同步后读取增强阶段已经启动的整本 KG prefetch；只有缓存缺失才用最终 Markdown 兜底启动一次。该节点立即用当前缓存快照生成 `docgen_kg_draft`，不在发布前固定等待；文档发布与剩余抽取继续并行。质量门只决定当前草稿能否在文档发布后被 fast-finalize 复用，不在此节点写图谱表。

输出：`docgen_kg_draft`, `kg_prefetch_metrics`, `kg_prefetch_ready`, `kg_draft_early_persist_metrics`

质量门会检查章节覆盖、边端点唯一性、关系方向、可考核/画像节点、诊断型节点和结构关系。`kg_draft_early_persist_metrics` 为兼容既有状态结构保留，当前构建固定记录 `deferred_until_document_publish` 且发布前计数为 0。

`KnowledgeUnit`、`KnowledgeEdge`、`KnowledgeGraphSourceRef`、补抽和废弃收口统一由 KnowledgeDoc 发布后的 `sync_knowledge_graph` 完成。因此进程在发布前退出时不会留下本轮 query-visible KG 半成品；`rollback_knowledge_graph` 仅保留旧版 early-persist 状态的兼容清理。

## 17. `publish_document`

输入：`merged_markdown`, `chapter_metadatas`, `intent_enhanced`, `summary_enhanced`, `user_profile`, `chapters_enhanced`, `dispatch_table`, `preliminary_kg`, `docgen_kg_draft`, `kg_draft_early_persist_metrics`, `guideline`

动作：发布 markdown；写 `docgen_manifest`；写 `KnowledgeDoc`；更新课程文档摘要。

输出：`doc_ids`, `built_paths`, `build_group_id`, `merged_path`

## 18. `sync_knowledge_graph`

文档发布后，知识图谱收口与向量索引收口并行执行。向量侧会同时处理用户上传资料和本轮已发布知识文档；即使课程没有上传文件，也会把正式知识文档切成稳定的内部检索源并写入 embedding。课程重建时，正文变化的 chunk 会删除旧向量并重新嵌入，不能因为旧索引表已存在就误判新文档可检索。

资料分块与向量写入在工作线程中分阶段完成，等待 embedding 网络请求时不持有数据库会话或课程索引写锁。写入前会重新校验分块所属任务、正文和 embedding 配置；较旧任务不能覆盖新任务的向量，上传资料的旧快照也不能回写较新的解析正文。课程索引写入在本地按课程串行，云端另用 PostgreSQL 事务 advisory lock 协调进程；向量存储使用独立连接，因此不能在持有 SQLite 写事务时调用向量写入。只有实际向量齐全的资料才标记为 `embedded`；失败、取消或停用时保留可重试的 `chunked` 状态。未变化的分块按批读取并复用向量，避免逐块刷新数据库。

输入：`doc_ids`, `merged_markdown`, `chapter_metadatas`, `docgen_kg_draft`, `build_session_id`

动作：全部章节增强完成后用整本增强稿启动唯一一次 KG 预取，与 review、repair 和文档收口交织运行；无拓扑依赖的 section 并发抽取。正式同步按 section key 与 content hash 复用未变化结果，只对修复或改名后未命中的 section 做 catch-up；消费缓存时会等待有界重试窗口，若仍需取消后台任务，会先确认请求已经退出，避免同一 section 被后台与正式同步重复调用。文档发布后，KG Doc Sync 与课程向量索引检查并行启动：前者正式固化图谱，后者在运行时允许写入但索引缺失时自动补建并复验；仍不可查询则明确失败，避免假成功后伴读长期降级。

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
