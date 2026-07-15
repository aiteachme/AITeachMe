# Digest 工作流

最后更新：2026-06-15

`digest/` 把用户资料变成知识资产。主线很简单：

```text
planner: 用户 prompt + 上传文件 -> confirmed_plan
docgen: confirmed_plan + 资料 + profile + diagnose -> KnowledgeDoc
kg_doc_sync: KnowledgeDoc -> KnowledgeUnit / KnowledgeEdge
```

## 目录

```text
digest/
  common/       # 资料准备、检索策略、事件、指标、共享模型
  planner/      # 构建前规划
  docgen/       # 知识文档生成
  kg_doc_sync/  # 知识文档同步为知识图谱
```

对应文档：

- [planner/README.md](planner/README.md)
- [docgen/README.md](docgen/README.md)
- [kg_doc_sync/README.md](kg_doc_sync/README.md)

## 总链路

```text
1. 上传资料
   输入: file_ids, user_prompt
   输出: 解析后的 source_documents / material_sections / material_digest

2. Planner
   输入: user_prompt, file_ids, material_context, latest_plan, diagnose_answers
   输出: latest_plan, diagnose, chapters

3. Confirm
   输入: latest_plan
   输出: confirmed_plan

4. DocGen
   输入: confirmed_plan, shared_inputs, profile_text, diagnose
   输出: KnowledgeDoc, merged_markdown, docgen_manifest

5. KG Doc Sync
   输入: 已发布 KnowledgeDoc / merged_markdown / docgen_kg_draft / prefetched_sections
   输出: KnowledgeUnit, KnowledgeEdge, KnowledgeGraphSourceRef

6. Examine/Profile
   输入: KnowledgeUnit, QuestionKnowledgeUnitLink, ExamPaperItem
   输出: UserKnowledgeState, course.profile_json, user.profile_json
```

## 关键字段流向

| 字段 | 生成位置 | 用在哪里 |
| --- | --- | --- |
| `material_context` | Planner `collect_planner_context` | Planner 理解资料和用户目标 |
| `diagnose` | Planner `compose_planner_draft` | 前端问卷，DocGen 个性化上下文 |
| `confirmed_plan` | Planner confirm | DocGen 唯一正式输入方案 |
| `learner_profile_text` | DocGen `load_context` | 章节 brief、正文生成、review |
| `intent_enhanced` | DocGen `prepare_global_seed` | 全文目标和写作方向 |
| `summary_enhanced` | DocGen `prepare_global_seed` | 资料摘要、证据、章节资料映射 |
| `chapters_enhanced` | DocGen seed/task 阶段 | 最终章节合同 |
| `dispatch_table` | DocGen `assemble_chapter_tasks` | 每章使用哪些资料和证据 |
| `preliminary_kg` | DocGen `assemble_chapter_tasks` | 写作期参考，不落库 |
| `docgen_kg_draft` | DocGen `prepare_knowledge_graph` | 发布后 KG fast-finalize 输入；发布前不可查询 |
| `KnowledgeDoc` | DocGen `publish_document` | KG 正式抽取输入 |
| `KnowledgeUnit` | KG `persist` | Examine 出题、Profile 掌握度 |

## DocGen / KG 交织

KG 候选不是等 `publish_document` 之后才开始生成。当前链路会在 DocGen 写作期持续准备图谱：

```text
build_chapter_execution_briefs
  -> 启动基于 brief / 证据 / dispatch_table 的早期 kg_prefetch sidecar
enhance_chapters
  -> 用完整章节刷新 sidecar，保留早期候选
review_chapters
  -> 产出章节级 kg_refinement_items
document_consistency_review / repair_or_route
  -> 用 reviewed / repaired 章节再次刷新 sidecar
merge_review -> sync_locked_titles
  -> 确定最终章节 metadata 和 H1
prepare_knowledge_graph
  -> 等待或刷新预抽取，生成 docgen_kg_draft
  -> 质量门只标记草稿是否可供发布后 fast-finalize
publish_document
  -> 写 KnowledgeDoc 和 manifest
sync_knowledge_graph
  -> 文档发布后复用 quality-ready docgen_kg_draft 或 hash 命中的 sidecar，统一写入图谱表并补齐 source_ref / 废弃收口
```

`docgen_kg_draft` 的质量门会检查章节覆盖、边端点唯一性、关系方向、可考核/画像节点、诊断型节点和结构关系。草稿在发布前只保留在工作流状态和 manifest 输入中，不写 `KnowledgeUnit`、`KnowledgeEdge` 或 `KnowledgeGraphSourceRef`；这些统一由发布后的 `kg_doc_sync` 权威固化。

## `diagnose` 的定位

`diagnose` 是 Planner 前置诊断，不是考试诊断，也不是 Profile 表字段。

```text
Planner 生成 diagnose
  -> 前端展示问题
  -> 用户 answered/skipped
  -> confirm 写进 confirmed_plan
  -> DocGen load_context 生成 diagnose_brief
  -> 拼入 learner_profile_text
```

影响：

- DocGen 的解释深度
- 例题和练习密度
- 前置知识补充
- review 判断口径

不直接影响：

- `mastery_score`
- `review_priority`
- `KnowledgeUnit`
- Examine 出题权重

## 边界

- Planner 不写正文、不写 KG、不写 Profile。
- DocGen 写知识文档并准备 KG 草稿，但不在 KnowledgeDoc 发布前写 query-visible 图谱实体。
- KG Doc Sync 只在知识文档发布后，从已发布文档和已审计草稿正式固化图谱。
- Profile 来自考试后的真实表现，`diagnose` 只是生成前的轻量问卷。

## 修改检查

- 新增跨节点字段要同步 `state.py` 和对应 README。
- 新增 LLM 调用要进各链路 `lib/model_policy.py`。
- 批量 LLM 任务优先走 `run_llm_tasks(...)`。
- 不手动改 `/frontend/src/api/generated/`。
