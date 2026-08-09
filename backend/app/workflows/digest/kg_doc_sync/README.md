# KG Doc Sync 链路

最后更新：2026-08-09

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
docgen_kg_draft
early_units_callback
```

`structured_context`：`docgen_manifest`, `document_summary_json`, `chapters[]`

`chapters[]`：`knowledge_document_id`, `chapter_index`, `title`, `summary`, `digest_mode`, `source_file_ids`

注意：`source_file_ids` 只是元数据；正式抽取文本是已发布 Markdown。

## 0. 预抽取 sidecar

输入：DocGen enhanced whole-document markdown, `build_session_id`, `course_id`

动作：全部章节增强完成后，立即用整本增强稿启动一次预抽取，和按章 review、跨章检查及必要修补交织运行。各 section 没有拓扑依赖，统一受 LLM 全局并发上限调度。最终 Markdown 固化时继续使用现有 sidecar；只有缓存缺失才启动整本文档兜底预抽取。正式同步按 section key 与 content hash 复用结果，标题或正文变化的 section 才补抽，因此 repair 不会让未改章节重复占用模型并发。

输出：`prefetched_sections`

边界：不写 `KnowledgeUnit`、`KnowledgeEdge`、`SourceRef`。

## 0.5 DocGen 发布前草稿

DocGen 的 `prepare_knowledge_graph` 会在 `merge_review / sync_locked_titles` 之后、`publish_document` 之前收口 `docgen_kg_draft`。

质量门通过时只标记该草稿可供发布后的 fast-finalize 复用。发布前不写可查询的 `KnowledgeUnit`、`KnowledgeEdge` 或 `KnowledgeGraphSourceRef`，避免进程崩溃留下没有对应已发布文档的图谱半成品。

边界：

- `docgen_kg_draft` 保留在 DocGen 状态，并随发布产物传给最终同步。
- `KnowledgeUnit`、`KnowledgeEdge`、source_ref、补抽、废弃收口和 sync_run 完成状态只由发布后的 `persist` 权威落库。
- `kg_draft_early_persist_metrics` 仅作为旧状态兼容字段保留，当前值为 deferred 且所有发布前写入计数为 0。

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

动作：复用 hash 命中的 section LLM 预抽取结果，并提前写入课程/章节结构锚点，可触发默认试卷预热。

输出：`created_unit_ids`, `updated_unit_ids`, `unit_count`

边界：只提前写可验证的 unit/edge，不写 source ref；DocGen preliminary_kg/backbone 只作为上下文，不再以规则方式生成语义知识点。

## 4. `extract`

输入：`markdown`, `structured_context`, `prefetched_sections`

动作：只有 quality-ready、覆盖最终章节且已经包含全部最终 Markdown prefetch payload 的 `docgen_kg_draft` 才允许 fast-finalize；结构预览草稿不能覆盖更丰富的 section 抽取结果。否则按最终 Markdown 切章节/小节，仅复用 section key 与 content hash 同时命中的 prefetch，未命中才执行 LLM catch-up 抽取，并合并 payload。

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

## 图谱类型

KG 不是“关键词图”，而是学习单元图。节点统一落到 `KnowledgeUnit.knowledge_unit_type`，边统一落到 `KnowledgeEdge.edge_type`。

## 节点类型

| 类型 | 中文名 | 什么时候建这个节点 | 例子 |
| --- | --- | --- | --- |
| `topic` | 主题模块 | 章节、单元、专题、知识簇，用来承载下级知识点 | 函数基础、几何证明 |
| `concept` | 概念术语 | 需要被定义、辨析、复习或出题的概念 | 导数、同位角、现金流 |
| `principle` | 原理性质 | 定理、性质、规律、判定准则、因果解释 | 切线判定定理、供需规律 |
| `formula_model` | 公式模型 | 公式、模型、计算框架、符号化关系 | 平均数公式、折现模型 |
| `procedure` | 方法步骤 | 可按步骤执行的方法、流程、操作规范 | 解一元二次方程步骤 |
| `skill` | 解题技能 | 可训练和考察的能力动作、题型策略 | 识别函数关系、审题找条件 |
| `misconception` | 易错辨析 | 常见误解、混淆点、错误边界 | 把切线判定和切线性质混用 |
| `application_case` | 应用案例 | 例题、案例、场景化应用、迁移任务 | 用导数判断单调性的例题 |

抽取原则：

```text
1. 能被学习、复习、检索、出题或画像追踪，才建节点。
2. 不把孤立句子、纯关键词、一次性答案当节点。
3. 练习/自测通常抽成 skill 或 application_case。
4. 注意事项/提醒如果服务于纠错，优先抽成 misconception。
5. 来源材料、阅读链接、普通说明作为 source_ref/evidence 保存，不再单独建 resource 节点。
```

## 边类型

边是有方向的：`source_node_id -[edge_type]-> target_node_id`。

| 类型 | 中文名 | 方向含义 | 常见连接 |
| --- | --- | --- | --- |
| `part_of` | 归属 | source 是 target 的组成部分 | concept -> topic，procedure -> topic |
| `prerequisite_for` | 前置 | source 是 target 的前置基础 | concept -> skill，procedure -> application_case |
| `derives_to` | 推导 | source 可推导出 target | concept/principle/formula_model -> principle/formula_model/procedure |
| `applies_to` | 应用 | source 被应用到 target | concept/principle/formula_model/procedure -> procedure/skill/application_case |
| `uses_method` | 用方法 | source 需要使用 target 这个方法/技能 | application_case/skill -> procedure/skill |
| `assesses` | 考察 | source 用来考察 target | skill/application_case/procedure -> concept/principle/formula_model |
| `explains` | 解释 | source 解释 target | application_case/procedure/principle -> concept/principle/skill |
| `remediates` | 补救 | source 用来纠正或补救 target | misconception/skill -> concept/principle/procedure/skill |
| `confuses_with` | 易混 | source 和 target 容易混淆 | misconception/concept <-> concept/principle |
| `similar_to` | 相似 | source 和 target 相似，可对照学习 | concept/skill/application_case <-> concept/skill/application_case |
| `extends_to` | 拓展 | source 可拓展到 target | concept/procedure/skill -> application_case/skill/concept |

方向例子：

```text
“平均数公式” -[applies_to]-> “计算一组数据的平均水平”
“识别切点和半径” -[prerequisite_for]-> “切线判定”
“把切线性质当判定条件” -[remediates]-> “切线判定”
“章末小测题” -[assesses]-> “切线判定”
“导数概念” -[part_of]-> “导数基础”
```

## 类型校验

```text
1. LLM 只能输出上面的节点类型和边类型。
2. `audit_graph` 会检查非标准类型、endpoint 是否存在、关系方向是否合理。
3. `normalize_relation_type` 只负责把少量旧类型映射到标准类型，不鼓励新增兼容别名。
4. `knowledge_relation_repo` 写库前会再次校验方向。
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
