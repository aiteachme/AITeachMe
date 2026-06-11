# KG Doc Sync 链路说明

最后更新：2026-06-03

`kg_doc_sync/` 是“知识文档 -> 知识图谱”的正式同步链路。

它不从原始上传文件直接建图。正式落库只读取当前课程已经发布的 `KnowledgeDoc`、`docgen_manifest.json`、章节来源映射和 `Course.document_summary_json`。

```text
DocGen 负责写出可读 Markdown。
KG Doc Sync 负责把已发布 Markdown 抽成 KnowledgeUnit / KnowledgeEdge。
```

## 先看这几个文件

```text
kg_doc_sync/
  graph.py                          # LangGraph 主线和 run_graph_docs_sync_workflow
  state.py                          # DocsSyncState
  nodes/                            # 顶层图节点
  lib/builds.py                     # 自动/手动触发、graph lane runtime、后台任务
  lib/inputs.py                     # 从已发布 KnowledgeDoc 组装同步输入
  lib/incremental_sync.py           # 切章、抽取、合并、落库核心逻辑
  lib/extraction.py                 # 结构化 LLM 抽取
  lib/prefetch.py                   # DocGen 期间的非阻塞预抽取 sidecar
  lib/model_policy.py               # KG 抽取 LLM 策略
  lib/query.py / overview.py        # 图谱查询和总览用例
```

公开入口：

```python
from app.workflows.digest.kg_doc_sync import (
    trigger_graph_docs_sync_manual_build,
    run_graph_docs_sync_auto_build,
    run_graph_docs_sync_workflow,
    load_knowledge_doc_sync_input,
    get_full_graph,
    get_knowledge_overview,
)
```

## 短流程

KG 生成分两个阶段。

```text
阶段 A：DocGen 期间预抽取（可选）
  DocGen enhance_chapters 完成
  -> start_docgen_kg_prefetch
  -> 按正式 KG 切章规则切 section
  -> 结构化 LLM 抽取 SectionExtractionPayload
  -> 写进程内缓存 course_id + build_session_id
  -> 不写 knowledge_unit / knowledge_edge / source_ref

阶段 B：发布后正式同步
  当前发布 KnowledgeDoc
  -> load_knowledge_doc_sync_input
  -> prepare
  -> init_run
  -> persist_seed_units
  -> extract
  -> persist_units
  -> stitch_relations
  -> persist
  -> finalize
```

一句话理解：

```text
prefetch 只是加速缓存。
persist 才是正式落库。
```

正式同步主线：

```text
1. 触发
   自动：DocGen 发布后 run_graph_docs_sync_auto_build。
   手动：知识图谱面板 trigger_graph_docs_sync_manual_build。

2. 输入装配
   读取当前发布 KnowledgeDoc，合并 Markdown。
   读取 docgen_manifest.json 和 Course.document_summary_json。
   组装 structured_context.chapters[]。

3. 初始化同步批次
   校验 Markdown 和 anchors。
   创建 KnowledgeGraphSyncRun(status="running")。

4. 预抽取复用
   如果同 build_session_id 的 prefetch section hash 命中最终文档，
   先把这些 LLM 产生的 KnowledgeUnit 提前写入。

5. 正式抽取
   按最终 Markdown 重新切章节/子章节。
   命中 prefetch payload 就复用；缺失、失败、内容变更就 catch-up LLM 补抽。

6. 提前写点
   把本轮 LLM extraction payload 里的 KnowledgeUnit upsert 到 knowledge_unit。
   不写边、不写 source_ref、不废弃旧实体。

7. 缝合关系
   不调用 LLM，只在内存 payload 上补保守关系边和图健康指标。

8. 权威落库
   写 KnowledgeUnit、KnowledgeEdge、KnowledgeGraphSourceRef。
   完成 KnowledgeGraphSyncRun。
   本轮消失的旧同步实体按规则标记 deprecated。
```

## 长流程

### 0. 触发层：`lib/builds.py`

`trigger_graph_docs_sync_manual_build(...)`

- 由知识图谱面板手动触发。
- API 层只做鉴权，真正的同步接受逻辑在这里。
- 如果 DocGen 仍在构建，拒绝手动构建。
- 如果 graph lane 正在构建，拒绝重复构建。
- 读取当前发布 `KnowledgeDoc` 和 manifest。
- 写 graph lane runtime：`accepted / manual_graph_requested`。
- 捕获当前 LLM runtime snapshot。
- 注册后台任务 `run_graph_docs_sync_manual_build(...)`。
- 不读取 DocGen prefetch cache。

`run_graph_docs_sync_auto_build(...)`

- 由 `run_docgen_background` 在 DocGen 发布成功后派发。
- 不阻塞 DocGen 页面读取已发布文档。
- 可消费同一个 `build_session_id` 下的 prefetch cache。
- 如果提前写入 KnowledgeUnit，会触发默认考卷预热回调。

`run_graph_docs_sync_after_doc_build(...)`

- 自动和手动最终都走到这里。
- 优先从刚完成的 DocGen state 组装输入；不完整时兜底读数据库当前文档。
- 消费并停止 prefetch sidecar。
- 写 graph lane runtime：`running / graph_docs_sync`。
- 使用 `use_llm_runtime_snapshot(llm_snapshot)` 固定本轮模型配置。
- 调 `run_graph_docs_sync_workflow(...)`。
- 把 `KnowledgeSyncReport` 转成 graph lane metrics。

### 1. 输入装配：`lib/inputs.py`

`load_knowledge_doc_sync_input(course_id, ...)` 输出：

```text
KnowledgeDocSyncInput
  markdown                 # 当前发布章节合并后的 Markdown
  source                   # database / docgen_state / none
  structured_context
    doc_version_no
    docgen_manifest
    document_summary_json
    chapters[]
      knowledge_document_id
      chapter_index
      title
      summary
      source_file_ids
      source_scope
      manifest
```

输入来源：

- `KnowledgeDoc(is_current=True, status="published")`
- `KnowledgeDocsManifest`
- `knowledge_markdowns/docgen_manifest.json`
- `Course.document_summary_json`

如果没有已发布 Markdown，手动构建会被拒绝。

### 2. 图运行入口：`run_graph_docs_sync_workflow`

- 创建 `WorkflowContext(workflow_name="digest.kg_doc_sync")`。
- metadata 带 `build_session_id / build_revision_no / doc_version_no / knowledge_doc_source` 等信息。
- 初始 state 带：
  - `course_id`
  - `markdown`
  - `structured_context`
  - `build_revision_no`
  - `prefetched_sections`
  - `early_units_callback`
- 成功返回 `KnowledgeSyncReport`。
- 如果 state 有 `error` 或缺 `report`，返回失败结果。

### 3. LangGraph 节点

| 顺序 | 节点 | 输入 | 输出 | 是否写库 |
| --- | --- | --- | --- | --- |
| 1 | `prepare` | `course_id`、Markdown、structured context | 校验后的 state、`node_metrics.prepare` | 否 |
| 2 | `init_run` | Markdown、doc version、build session | `sync_run_context`、graph revision | 写 `KnowledgeGraphSyncRun(status="running")` |
| 3 | `persist_seed_units` | Markdown、structured context、prefetched sections | early units metrics | 只提前写命中最终 hash 的预抽取 KnowledgeUnit |
| 4 | `extract` | Markdown、course context、structured context、prefetch records | `KnowledgeSyncExtractionPayload`、extract metrics | 否 |
| 5 | `persist_units` | extraction payload、sync run | persist_units metrics | 提前 upsert KnowledgeUnit；不写边/source_ref |
| 6 | `stitch_relations` | extraction payload | 更新后的 payload、图健康指标 | 否 |
| 7 | `persist` | payload、sync run | `KnowledgeSyncReport` | 权威写 unit、edge、source_ref、deprecated、sync run completed |
| 8 | `finalize` | report | 成功 state | 否 |
| 失败 | `fail` | error、sync run context | failed metrics | best-effort 标记 sync run failed |

失败路径：

```text
prepare / init_run / extract / stitch_relations / persist / finalize
  -- error --> fail --> END
```

### 4. `extract` 内部怎么抽

`extract` 节点本身不写库。它把最终 Markdown 变成内存 payload。

步骤：

```text
extract_markdown_chapter_chunks
  -> _build_extraction_tasks
  -> _collect_section_payloads_async
       -> 命中 prefetch：复用 SectionExtractionPayload
       -> 未命中：_extract_chapter_with_retries
            -> _extract_chapter_graph_items
            -> extract_candidates_with_diagnostics
            -> 空结果时 _repair_docs_extraction_after_empty
  -> _combine_section_payloads
       -> anchor 去重
       -> candidate id 加分片命名空间
       -> endpoint 解析
       -> backbone / structural / cross-section edges
```

切章规则：

- 多个 H1：按 H1 切章。
- 一个 H1 + 多个 H2：把 H1 当文档标题，按 H2 切章。
- 没有 H1：按 heading-scoped section 兜底。
- 完全没有 heading 但有正文：生成 `Knowledge Document` 兜底 chunk。

任务拆分规则：

- 章节正文长度达到 `_DOCS_SYNC_SPLIT_MIN_CHAPTER_CHARS = 2400` 且至少有 2 个可抽取子章节时，按子章节拆。
- 即使章节未达到 2400 字，只要有 4 个以上可抽取子章节，也按小节拆。
- 总任务规划上限来自 `settings.knowledge_graph.max_parallel_extractions`，默认 16。
- 批量执行通过 `run_llm_tasks(..., max_concurrent=extraction_limit)`，并继续受全局 LLM limiter 限制。

抽取失败策略：

- 单个 section 失败不会让整条链路失败。
- 失败分片返回空 payload，并计入 `failed_section_count / llm_error_count`。
- 其它成功分片继续合并和落库。
- 如果有失败分片，最终 `persist` 会跳过 deprecated，避免误删旧图谱实体。

### 5. 节点来源边界

可以创建 KnowledgeUnit 的来源只有三类：

1. 正式结构化 LLM 主抽取。
2. 主抽取为空后的结构化 LLM 修复。
3. 命中最终文档 hash 的 DocGen LLM 预抽取 payload。

不会本地造 KnowledgeUnit 的来源：

- Markdown 标题。
- 题干或关键词。
- DocGen backbone。
- structural heading edge。
- relation stitching。

这些只能补关系或辅助来源解释。

### 6. `stitch_relations` 做什么

这是本地保守关系缝合，不调用 LLM，不访问数据库。

它做：

- 同一小节内，把定义、公式、例题、方法、易错点连接到主概念。
- 对仍然孤立、且正文中明确引用其它唯一知识点的节点补少量引用边。
- 计算：
  - isolated unit count / pct
  - component count
  - largest component size
  - average degree

它不做：

- 不创建新节点。
- 不猜测跨章强依赖。
- 不覆盖 LLM 关系，只补保守边。

### 7. `persist` 权威落库

`persist` 是正式写图谱的节点。

写入规则：

- `KnowledgeUnit`
  - 按 `course + type + normalized_name` 复用稳定节点。
  - 写 `canonical_name / summary / body_markdown / status / build_revision_no`。
  - 写 anchor alias。
- `KnowledgeEdge`
  - endpoint 必须能解析到本轮 unit。
  - 写入前通过 `validate_relation_direction`。
  - 按 source / target / type upsert。
- `KnowledgeGraphSourceRef`
  - unit 和 edge 都写 source ref。
  - 保存 `sync_run_id / knowledge_document_id / chapter_index / anchor / quote_text / confidence / source_file_ids`。
- deprecated
  - 本轮没有失败 section 时，才标记消失的旧 sync unit / edge 为 deprecated。
  - 有失败 section 时跳过 deprecated。
- `KnowledgeGraphSyncRun`
  - 成功写 `completed / metrics_json / finished_at`。
  - 写入异常写 `failed / error`。

## 关键数据流

```text
KnowledgeDoc Markdown
  -> structured_context
  -> SectionExtractionPayload[]
  -> KnowledgeSyncExtractionPayload
  -> early KnowledgeUnit upsert
  -> stitched extraction payload
  -> KnowledgeUnit / KnowledgeEdge / KnowledgeGraphSourceRef
  -> KnowledgeSyncReport
  -> graph lane runtime metrics
```

预抽取缓存复用：

```text
DocGen enhanced Markdown
  -> prefetch section_key + content_hash + payload
  -> publish final Markdown
  -> formal sync recomputes section_key + content_hash
  -> hit: reuse payload
  -> miss/stale/error: catch-up LLM extraction
```

## 模型和并发

策略集中在 `lib/model_policy.py`。

| 步骤 | 调用 | 槽位 | 关键预算 |
| --- | --- | --- | --- |
| `KGDocSyncModelStep.SECTION_GRAPH` | structured | `light` | `max_tokens=7000`、`timeout_s=300`、正文最多 12000 chars |
| `KGDocSyncModelStep.EMPTY_REPAIR` | structured | `light` | `max_tokens=3600`、`timeout_s=300` |

并发：

- 全局 LLM 并发：`settings.llm.concurrency_limit`，默认 4。
- DocGen prefetch sidecar：`settings.knowledge_graph.prefetch_concurrency`，默认 2。
- 正式同步任务规划和本批调度：`settings.knowledge_graph.max_parallel_extractions`，默认 16。
- 实际模型请求仍进入统一 LLM limiter。

## 输出指标

`KnowledgeSyncReport` 的关键指标：

- `created_unit_ids / updated_unit_ids / deprecated_unit_ids`
- `created_edge_ids / updated_edge_ids / deprecated_edge_ids`
- `section_count / successful_section_count / failed_section_count`
- `llm_section_count / llm_error_count`
- `empty_repair_attempt_count / empty_repair_success_count`
- `source_ref_count`
- `backbone_edge_count`
- `stitched_edge_count`
- `graph_isolated_unit_pct`
- `graph_component_count`
- `stable_anchor_count`
- `prefetch_reused_section_count / prefetch_catchup_section_count`

`lib/builds.py` 会把这些写回 graph lane runtime，供前端轮询和调试展示。

## 修改这条链路时检查

- 正式输入是否仍只来自已发布 `KnowledgeDoc` 和 manifest。
- 新节点是否写进 `graph.py` 的主线和本文节点表。
- 新 LLM 调用是否进了 `lib/model_policy.py`。
- 批量抽取是否继续走 `run_llm_tasks(...)`。
- 是否误用标题、题干或关键词本地造 KnowledgeUnit。
- 新关系类型是否同步检查 workflow ontology 和模型层枚举。
- `persist` 是否仍写 source ref。
- 有失败 section 时是否避免 deprecated 误删旧实体。

建议提交类型：改本文档用 `docs`，改链路行为用 `refactor` 或 `fix`。
