# KG Doc Sync 链路

最后更新：2026-06-15

职责：把已发布知识文档同步成知识图谱。

```text
输入: KnowledgeDoc / merged_markdown / docgen_manifest
输出: KnowledgeUnit / KnowledgeEdge / KnowledgeGraphSourceRef
```

## 主流程

```text
prepare
  -> init_run
  -> persist_seed_units
  -> extract
  -> persist_units
  -> stitch_relations
  -> audit_graph
  -> persist
  -> finalize
```

## 正式输入

```text
course_id
markdown
structured_context
build_revision_no
doc_version_no
build_session_id
prefetched_sections
early_units_callback
```

`structured_context`：`docgen_manifest`, `document_summary_json`, `chapters[]`

`chapters[]`：`knowledge_document_id`, `chapter_index`, `title`, `summary`, `digest_mode`, `source_file_ids`

注意：`source_file_ids` 只是元数据；正式抽取文本是已发布 Markdown。

## 0. 预抽取 sidecar

输入：DocGen enhanced markdown, `build_session_id`, `course_id`

动作：DocGen 增强后提前切 section，调用 LLM 抽 `SectionExtractionPayload`，写进程内缓存。

输出：`prefetched_sections`

边界：不写 `KnowledgeUnit`、`KnowledgeEdge`、`SourceRef`。

## 1. `prepare`

输入：`course_id`, `markdown`, `structured_context`

动作：校验 markdown 和上下文，初始化 metrics。

输出：validated state, `node_metrics.prepare`

## 2. `init_run`

输入：`course_id`, `build_revision_no`, `doc_version_no`, `build_session_id`

动作：创建 `KnowledgeGraphSyncRun(status=running)`。

输出：`sync_run_context`, `sync_run_id`

## 3. `persist_seed_units`

输入：`prefetched_sections`, `markdown`, `sync_run_context`

动作：复用 hash 命中的预抽取 section，提前 upsert 命中的 KnowledgeUnit，可触发默认试卷预热。

输出：`created_unit_ids`, `updated_unit_ids`, `unit_count`

边界：只提前写 unit，不写 edge/source ref。

## 4. `extract`

输入：`markdown`, `structured_context`, `prefetched_sections`

动作：按最终 Markdown 切章节/小节；命中 prefetch 则复用；未命中则 LLM catch-up 抽取；合并 payload。

输出：`extraction_payload`, extract metrics

`extraction_payload`：`units`, `extracted_edges`, `diagnostics_totals`

## 5. `persist_units`

输入：`extraction_payload`, `sync_run_context`

动作：先 upsert 本轮 units，为后续 edge endpoint 解析准备真实 ID。

输出：`created_unit_ids`, `updated_unit_ids`, `unit_count`

## 6. `stitch_relations`

输入：`extraction_payload`

动作：不调 LLM；在内存中补保守关系；计算图健康指标。

输出：`extraction_payload`, `stitched_edge_count`, graph metrics

## 7. `audit_graph`

输入：`extraction_payload`, `structured_context`

动作：检查节点类型、边类型、endpoint、关系方向、章节覆盖。

输出：audited payload, `graph_audit_*` metrics

## 8. `persist`

输入：audited payload, `sync_run_context`, `structured_context`

动作：权威 upsert unit/edge；写 source ref；标记 deprecated；完成 sync run。

输出：`KnowledgeSyncReport`

## 9. `finalize`

输入：`KnowledgeSyncReport`

动作：收口最终状态。

输出：final state

## 类型

节点类型：

```text
topic, concept, principle, formula_model, procedure, skill,
misconception, application_case, resource
```

边类型：

```text
part_of, prerequisite_for, derives_to, applies_to, uses_method,
assesses, explains, remediates, confuses_with, similar_to, extends_to
```

## 关键落库字段

`KnowledgeUnit`：

```text
course_id
knowledge_unit_type
canonical_name
normalized_name
summary
body_markdown
aliases_json
evidence_refs_json
status
confidence
type_confidence
type_source
build_revision_no
```

`KnowledgeSyncReport`：

```text
created_unit_ids
updated_unit_ids
deprecated_unit_ids
created_edge_ids
updated_edge_ids
deprecated_edge_ids
section_count
successful_section_count
failed_section_count
source_ref_count
stitched_edge_count
graph_component_count
prefetch_reused_section_count
prefetch_catchup_section_count
```

## 下游

```text
KnowledgeUnit
  -> Examine 生成题目
  -> QuestionKnowledgeUnitLink.knowledge_unit_id
  -> Profile UserKnowledgeState.knowledge_unit_id
```

## 修改检查

- 正式输入必须仍是已发布 `KnowledgeDoc`。
- 新 LLM 调用进 `lib/model_policy.py`。
- 不用标题/关键词本地造 KnowledgeUnit。
- 新类型要同步 ontology、prompt、audit、前端。
- section 部分失败时避免误 deprecated。
