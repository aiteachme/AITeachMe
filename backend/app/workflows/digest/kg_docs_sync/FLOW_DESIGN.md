# kg_docs_sync Flow Design

`kg_docs_sync` 是知识文档发布后的图谱同步链路。它的职责不是重新理解原始文件，而是把已经发布的 `KnowledgeDocument`、DocGen 结构化产物和章节来源映射同步到当前学科的知识图谱中。

## 1. 边界和目标

当前链路写入的核心表：

- `knowledge_unit`
- `knowledge_edge`
- `knowledge_graph_sync_run`
- `knowledge_graph_source_ref`

它不创建 `curriculum / teaching_unit / taxonomy_anchor / theme_tree_node / unit_dependency` 这类未来表，也不暴露独立 debug API。前端看到的图谱进度来自统一 build runtime 的 `graph` lane metrics。

目标优先级：

1. 稳定节点身份：同一学科、同一类型、同一规范化名称优先复用同一个 `KnowledgeUnit`。
2. 质量优先：宁可少入图，也不要把章节标题、学习目标、解题提示、考试策略、计划要求句当成知识点。
3. 可解释：每个从文档同步来的节点和边尽量写 `KnowledgeGraphSourceRef`，能追到章节、文档版本、源文件和同步批次。
4. 可回滚感知：每次同步有 `KnowledgeGraphSyncRun`，并根据 revision deprecate 本轮消失的旧同步节点/边。

## 2. 入口

主入口从 DocGen build 后台调用：

```text
run_docgen_background
  -> run_graph_docs_sync_after_doc_build
  -> run_graph_docs_sync_workflow
  -> sync_markdown_knowledge_graph
```

关键文件：

- `backend/app/workflows/support/knowledge_graph/builds.py`
- `backend/app/workflows/digest/kg_docs_sync/workflow.py`
- `backend/app/workflows/digest/kg_docs_sync/graph.py`
- `backend/app/workflows/support/knowledge_graph/incremental_sync.py`

## 3. 外部输入

`run_graph_docs_sync_after_doc_build(...)` 输入：

| 字段 | 来源 | 用途 |
| --- | --- | --- |
| `subject` | DocGen build | 学科 scope，所有图谱写入都按 subject 隔离 |
| `requested_at` | DocGen build | 写 graph lane runtime |
| `build_group_id` | DocGen build | 关联 docgen/graph 两条 lane |
| `build_session_id` | DocGen build | LangSmith、source ref、sync run 关联 |
| `file_ids` | DocGen build | graph runtime 展示和来源兜底 |
| `prompt` | DocGen build | runtime 记录，不直接作为候选节点来源 |
| `llm_snapshot` | DocGen build | 保证后台异步 LLM 子调用挂到同一运行时配置 |

`load_knowledge_doc_sync_input(subject)` 会组装：

| 字段 | 说明 |
| --- | --- |
| `markdown` | 最新发布知识文档合并 Markdown |
| `source` | 文档来源标识，例如 `published_docs` |
| `structured_context.doc_version_no` | 当前知识文档版本 |
| `structured_context.chapters[]` | 每章 `knowledge_document_id / chapter_index / title / summary / source_file_ids` |
| `structured_context.docgen_manifest` | 当前 DocGen manifest |
| `structured_context.document_summary_json` | `Subject.document_summary_json`，作为 manifest 缺失时的兜底 |

## 4. LangGraph 节点

`kg_docs_sync/graph.py` 只有四个节点，真正的复杂逻辑在 `incremental_sync.py`。

| 节点 | 输入 | 输出 | 失败条件 |
| --- | --- | --- | --- |
| `prepare` | `subject / markdown` | 规范化后的 `subject` | subject 为空、markdown 为空 |
| `sync` | `subject / markdown / build_revision_no / build_session_id / subject_context / structured_context` | `KnowledgeSyncReport` | Markdown anchor 非法、数据库写入失败、抽取异常 |
| `finalize` | `report / error` | 原状态 | report 缺失 |
| `fail` | 任意失败状态 | 原状态 | 只收口，不做恢复 |

`DocsSyncState` 字段：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `subject` | `str` | 学科 scope |
| `markdown` | `str` | 合并后的知识文档 Markdown |
| `subject_context` | `str` | 学科上下文，空时从 DB 读取 |
| `structured_context` | `dict` | DocGen manifest、章节来源、文档版本等 |
| `build_revision_no` | `int | None` | 指定图谱 revision；空则自动递增 |
| `build_session_id` | `str` | 本次构建 session |
| `report` | `KnowledgeSyncReport | None` | 同步报告 |
| `error` | `str | None` | 节点失败信息 |

## 5. `sync_markdown_knowledge_graph` 内部流程

### 5.1 校验和 sync run

输入：

- `subject`
- `markdown`
- `build_revision_no`
- `enable_rag_dedup`
- `subject_context`
- `structured_context`
- `build_session_id`

处理：

1. `validate_knowledge_unit_anchors(markdown)` 校验显式 `ATM_KU` anchor。
2. 解析 `structured_context.doc_version_no`。
3. 创建 `KnowledgeGraphSyncRun(status="running")`。
4. 调用 `_extract_markdown_graph_items(...)` 产出待写入的 units/edges。

输出：

- 成功时 `KnowledgeSyncReport`
- 失败时更新 sync run 为 `failed` 并抛出异常

### 5.2 Markdown 切章

`extract_markdown_chapter_chunks(markdown)` 负责决定 docs-sync 的并行粒度。

规则：

1. 多个 H1：按 H1 切章。
2. 一个 H1 且包含多个 H2：把 H1 当文档标题，按 H2 切章。
3. 没有 H1：取第一个 heading-scoped section 作为兜底 chunk。
4. 完全没有 heading 但有正文：生成 `Knowledge Document` 兜底 chunk。

这个规则的核心目的是避免把“初中数学复习讲义”这类整份文档标题当成知识点。

### 5.3 章节并行抽取

每个 chapter 走 `_extract_chapter_with_retries(...)`：

输入：

- `chapter_index`
- `MarkdownSectionChunk`
- `subject_context`
- `ChapterSourceContext`

输出：

- `SectionExtractionPayload`

并发控制：

- 默认 `_DOCS_SYNC_CHAPTER_CONCURRENCY_LIMIT = 6`
- 每章最多 `_DOCS_SYNC_CHAPTER_MAX_RETRIES = 2`
- 每次抽取内部的 docs LLM 超时由 extractor 控制，当前 docs section timeout 为 25s

`SectionExtractionPayload` 主要字段：

| 字段 | 含义 |
| --- | --- |
| `units` | 本章候选 `MarkdownKnowledgeUnit` |
| `pending_edges` | 尚未解析 endpoint anchor 的边 |
| `candidate_id_to_anchor` | LLM candidate id 到本地 anchor |
| `anchors_by_name` | 名称到 anchor 列表 |
| `anchors_by_normalized_name` | 规范化名称到 anchor 列表 |
| `node_contexts_by_anchor` | 后续结构边/跨章边使用的节点上下文 |
| `section_context` | 本章主节点和来源上下文 |
| `diagnostics` | 本章抽取计数 |

### 5.4 单章候选来源

每章候选目前复用 legacy `kg_file_ingest/lib/extractor.py` 里的 extractor 实现。这里复用的是抽取器代码，不代表 `kg_file_ingest` 仍是正式图谱构建 lane；自动构建只走 docs-sync。

1. LLM structured extraction：主路径。
2. docs support result：当 LLM 空结果或节点过少时，用标题、正文、typed lines 生成保底节点。
3. topic fallback：LLM 报错或空结果时，用语义标题路径兜底。
4. question fallback：题目密集内容下从题目反推概念/方法。

docs-sync 在拿到结果后会再执行 `_filter_docs_candidate_result(...)`。这个过滤层只挡明显不是知识点的名字，例如：

- 学习目标、章节导读、本章自检、考前复盘
- 题型例练、速判口诀、解题入口、解题模板
- 带 `一、/二、/三、` 的章节标题
- 题干句、任务句、计划句
- 主干划分、权重排序、区分标准、错误路径归纳、综合题结构等 meta 规划词

### 5.5 全局 anchor 去重

每章抽取完成后会调用 `_make_payload_anchors_unique(...)`。

输入：

- 单章 payload
- 全局 `used_anchors`

输出：

- anchor 已全局去重的 payload

约束：

- DocGen 产物来的 anchor seed 不含 doc version，版本信息只进入 source ref。
- 同名同类型最终仍靠 `subject + knowledge_unit_type + normalized_name` 复用 DB 节点。

### 5.6 DocGen backbone 补漏

`_build_backbone_graph_items(...)` 读取：

- `structured_context.docgen_manifest.document_backbone_snapshot`
- 缺失时读取 `structured_context.document_summary_json.document_backbone`

处理：

1. `canonical_glossary` 只作为保底知识点来源。
2. 如果 LLM/正文已抽到同名 normalized name，则 backbone 不再额外建一个 concept 壳。
3. 如果 term 命中低质量过滤，则丢弃。
4. `concept_dependency_graph` 生成边：
   - `chapter_order` -> `prerequisite`
   - 其它 relation 走 `normalize_relation_type`

调试判断：

- 节点详情来源显示 `docgen_backbone`，说明它来自 backbone 保底。
- 如果坏节点也是 `docgen_backbone`，优先检查 `canonical_glossary` 的 term 是否是课程规划词。

### 5.7 结构边和跨章节边

同步候选合并后会补两类关系：

1. `_build_structural_heading_edges(...)`
   - 用 heading path 生成 `derivation`，表示子知识点属于父主题。
2. `_build_cross_section_semantic_edges(...)`
   - 基于 `section_context` 和 parent/taxonomy hint 推断跨 section 的 `derivation / application / similar / contrast`。

边在最终写库前必须能解析到 source/target anchor，且不能自环。

### 5.8 Upsert 和 provenance

写入阶段：

1. `_upsert_unit(...)`
   - 先按 `subject + type + normalized_name` 找现有节点。
   - 可选 RAG dedup 用于更宽松的语义合并。
   - 更新 aliases/evidence/revision 兼容字段。
2. `_create_source_ref_for_unit(...)`
   - 写 `entity_type="unit"` 的 source ref。
3. `_upsert_edge(...)`
   - 按 source/target/type upsert。
   - 方向必须通过 `validate_relation_direction(...)`。
4. `_create_source_ref_for_edge(...)`
   - 写 `entity_type="edge"` 的 source ref。
5. `_deprecate_removed_anchor_units(...)`
   - 本轮没出现的 markdown sync 节点标记 deprecated。
6. `_deprecate_removed_sync_edges(...)`
   - 本轮没出现的 sync edge 标记 deprecated。

## 6. 输出和 metrics

`KnowledgeSyncReport` 关键字段：

| 字段 | 含义 |
| --- | --- |
| `build_revision_no` | 本轮图谱 revision |
| `doc_version_no` | 同步的知识文档版本 |
| `created_unit_ids / updated_unit_ids / deprecated_unit_ids` | 节点变化 |
| `created_edge_ids / updated_edge_ids / deprecated_edge_ids` | 边变化 |
| `section_count / chapter_count` | 处理章节数 |
| `llm_section_count` | 调过 LLM 的章节数 |
| `fallback_section_count` | 使用 fallback 的章节数 |
| `question_fallback_section_count` | 题目 fallback 数 |
| `topic_fallback_section_count` | topic fallback 数 |
| `source_ref_count` | source ref 写入数 |
| `backbone_unit_count / backbone_edge_count` | backbone 补漏数量 |
| `stable_anchor_count` | 本轮稳定 anchor 数 |
| `elapsed_ms` | 同步耗时 |

`run_graph_docs_sync_after_doc_build(...)` 会把这些转成 runtime graph metrics：

- `doc_sync_unit_changes`
- `doc_sync_edge_changes`
- `doc_sync_elapsed_ms`
- `elapsed_ms`
- `revision_no`
- `last_synced_doc_version_no`
- `doc_sync_section_count`
- `doc_sync_llm_section_count`
- `doc_sync_fallback_section_count`
- `source_ref_count`
- `backbone_unit_count`
- `backbone_edge_count`
- `stable_anchor_count`
- `deprecated_unit_count`
- `deprecated_edge_count`

## 7. 常见坏味道和排查路径

| 现象 | 高概率原因 | 优先看哪里 |
| --- | --- | --- |
| 节点来源是 `docgen_backbone`，名字像课程规划 | `canonical_glossary` 把 plan required element 当 term | `_build_backbone_graph_items` 和 DocGen backbone 生成 |
| 节点带 `一、/二、` | LLM 把章节标题当节点 | `_is_low_quality_docs_unit_name` |
| 整份文档标题入图 | Markdown 切章粒度不对或只有一个总标题 | `extract_markdown_chapter_chunks` |
| 很多 `速判/题型/复盘` 节点 | sprint 文档教学包装没过滤干净 | `_DOCS_UNIT_WRAPPER_TERMS` |
| source ref 为空 | `structured_context.chapters` 缺 `knowledge_document_id/source_file_ids` | `load_knowledge_doc_sync_input` |
| 边明显方向反了 | relation 类型或 source/target 类型不匹配 | `validate_relation_direction` 和 `_resolve_edge_anchor` |

## 8. 当前已知债务

1. LLM 抽取和 fallback 仍在同一个 extractor 里，docs-sync 质量规则散在两个模块之间。
2. `canonical_glossary` 的上游生成还会混入课程规划词，当前在入图前做硬过滤。
3. source ref 是 append-only，节点详情读取会显示历史来源；未来需要按 sync run 或版本排序/折叠。
4. `aliases_json/evidence_refs_json` 仍是 MVP 兼容字段，规模化查询应优先读 source ref 表。
