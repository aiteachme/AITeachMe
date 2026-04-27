# kg_doc_sync Flow Design

最后更新：2026-04-27

`kg_doc_sync` 是知识文档发布后的知识图谱同步链路。它不再直接解析用户上传的原始文件，也不再提供独立 debug 构建入口；正式输入只有当前学科已经发布的 `KnowledgeDoc`、DocGen 结构化产物、章节来源映射和 `Subject.document_summary_json`。

当前写入的核心表：

- `knowledge_unit`
- `knowledge_edge`
- `knowledge_graph_sync_run`
- `knowledge_graph_source_ref`

本链路不会创建 `curriculum / teaching_unit / taxonomy_anchor / theme_tree_node / unit_dependency` 等未来大表。节点和关系的可解释来源先由轻量溯源表承接。

LangGraph 节点的 `node_description`、输入输出字段和 metadata 统一通过
`digest.common.node_tracing` 生成；内部阶段不再额外创建顶层 LangSmith trace，
避免 Trace 列表被 anchor 校验、候选抽取和图谱写入刷屏。
每个节点都会写入 `node_metrics.<node>`，用于在 trace 和最终 state 中查看本阶段输入规模、
并发配置、sync_run id、抽取统计、写库变更数和失败标记结果。

## 1. 流程总览与执行合同

### 1.1 短流程总览

这一节面向快速阅读，写清所有节点、并行关系、fan-out/fan-in、流水线关系和节点作用。字段级输入输出放在 `1.2 长流程执行合同`。

#### 1.1.1 当前模型槽位总览

本节只描述 **当前代码真实使用的逻辑模型槽位**。最终 provider 模型名来自：

- `backend/app/shared/infra/settings/defaults.py`
- `backend/app/shared/infra/settings/settings.py`
- `backend/app/shared/infra/llm_support/common.py`

当前默认映射是：

```text
reason  -> qwen-max
primary -> qwen-flash
light   -> qwen-flash
image_generation -> settings.models.image_generation（默认未配置）
```

注意：

- 这里说的 `reason / primary / light` 是逻辑模型槽位，不是固定 provider 名。
- 如果运行时 settings 覆盖了 `settings.models.*`，实际模型名会随之变化。
- KG docs-sync 当前使用 `light` 槽位；抽取任务意图由 `call_purpose=EXTRACT` 表达。
- 路由层仍保留 `extract` 兼容别名，但新代码不应继续把它当模型槽位使用。
- `kg_doc_sync` 的 LangGraph 节点本身不直接写死模型，LLM 调用集中在复用的 extractor 内部；`call_purpose + model slot + max_tokens` 统一由 `kg_doc_sync/lib/model_policy.py` 维护。
- Prompt 文件按真实调用拆分：章节图谱抽取在 `prompts/section_graph.py`，题目 fallback 概念识别在 `prompts/question_concepts.py`，导出聚合在 `prompts/registry.py`。
- 核心 lib 按职责拆分：`models.py` 放 state/report 数据合同，`sync_runs.py` 放同步批次状态写入，`candidate_quality.py` 放候选过滤规则，`question_blocks.py` 只保留题目 fallback 需要的题块解析。

按当前代码，KG docs-sync 各阶段的大模型使用如下：

| 阶段 / 子步骤 | 当前代码位置 | 调用类型 | call_purpose | 逻辑模型槽位 | 当前默认模型 | 这一步做什么 |
| --- | --- | --- | --- | --- | --- | --- |
| `run_graph_docs_sync_after_doc_build` | `kg_doc_sync/builds.py` | 无 LLM | 无 | 无 | 无 | 读取发布文档、写 graph lane runtime、挂 LangSmith root trace |
| `load_knowledge_doc_sync_input` | `kg_doc_sync/inputs.py` | 无 LLM | 无 | 无 | 无 | 读取 `KnowledgeDoc` rows、DocGen manifest、文档摘要和章节来源映射 |
| `prepare` | `kg_doc_sync/nodes/prepare_node.py` | 无 LLM | 无 | 无 | 无 | 校验 `subject` 和合并 Markdown |
| `init_run` | `kg_doc_sync/nodes/init_run_node.py` | 无 LLM | 无 | 无 | 无 | 校验 Markdown anchors，创建 `knowledge_graph_sync_run`，确定 revision/doc_version |
| `extract` | `kg_doc_sync/nodes/extract_node.py` | 间接 LLM | 由内部 extractor 决定 | 由 policy 决定 | 见下方 | 加载学科上下文，按章节/大章内小节并发抽取图谱候选并合并 fallback/backbone/结构边 |
| `persist` | `kg_doc_sync/nodes/persist_node.py` | 无 LLM | 无 | 无 | 无 | 写入节点、关系、source_ref，标记旧同步实体 deprecated，并完成 sync run |
| `_extract_chapter_graph_items` 主抽取 | `kg_doc_sync/lib/incremental_sync.py` -> `kg_doc_sync/lib/extraction.py` | 结构化 | `EXTRACT` | `light` | `qwen-flash` | 从单个章节/小节 extraction task 抽取候选 KnowledgeUnit 和关系 |
| `_repair_docs_extraction_after_empty` | `kg_doc_sync/lib/extraction.py` | 结构化 | `EXTRACT` | `light` | `qwen-flash` | 当 docs-sync 主抽取为空时做一次极短修复抽取 |
| `_llm_extract_concepts_from_questions` | `kg_doc_sync/lib/extraction.py` | 结构化 | `DOCGEN_LIGHT` | `light` | `qwen-flash` | 题目密集内容下从题干反推少量概念/方法 |
| `filter_docs_candidate_result` | `kg_doc_sync/lib/candidate_quality.py` | 无 LLM | 无 | 无 | 无 | 丢弃学习目标、题型例练、速判口诀、计划句等非知识点 |
| `_build_backbone_graph_items` | `kg_doc_sync/lib/incremental_sync.py` | 无 LLM | 无 | 无 | 无 | 把 DocGen `document_backbone` 的 glossary/dependency 转成保底节点和边 |
| `_build_structural_heading_edges` | `kg_doc_sync/lib/incremental_sync.py` | 无 LLM | 无 | 无 | 无 | 用标题层级补结构边 |
| `_build_cross_section_semantic_edges` | `kg_doc_sync/lib/incremental_sync.py` | 无 LLM | 无 | 无 | 无 | 基于节点上下文补跨章节语义边 |
| upsert / source ref / deprecate | `kg_doc_sync/lib/incremental_sync.py` | 无 LLM | 无 | 无 | 无 | 写入节点、关系、同步批次、来源引用和过期标记 |

当前主线：

```text
run_docgen_background
  DocGen 发布完成后，如果 sync_after_docgen 打开，则进入 graph lane。
  |
  v
run_graph_docs_sync_after_doc_build
  建立 LangSmith root trace。
  读取当前发布知识文档和结构化上下文。
  写入 graph lane running runtime。
  |
  v
load_knowledge_doc_sync_input
  从 DB 读取当前 KnowledgeDoc rows。
  合并章节 Markdown。
  读取 docgen_manifest / document_backbone / Subject.document_summary_json。
  组装 structured_context。
  |
  v
run_graph_docs_sync_workflow
  创建 WorkflowContext(workflow_name="digest.kg_doc_sync")。
  调用 run_state_graph，LangSmith 中能看到 kg_doc_sync 主链路。
  |
  v
prepare
  校验 subject 和 Markdown。
  |
  v
init_run
  校验 Markdown anchors。
  创建 KnowledgeGraphSyncRun(status="running")。
  生成 sync_run_context。
  |
  v
extract
  如果 subject_context 为空，则从学科 LLM context 读取。
  按真实章节切分 Markdown。
  LLM 子调用挂在 extract 节点下。
  |
  v
_extract_chapter_with_retries x N
  单节点内部 async fan-out：
    ├─ chapter 1 extraction
    ├─ chapter 2 extraction
    └─ chapter N extraction
  默认并发 10，每章最多 2 次尝试；单章 LLM 输入会保留开头和结尾并压到固定字符预算内。
  通过 contextvars 继承外层运行上下文，让 LLM 子调用挂在同一条 trace 下。
  |
  v
fan-in extraction payloads
  合并所有章节候选。
  做全局 anchor 去重。
  合并 LLM 候选、fallback 候选、DocGen backbone 候选。
  补结构边和跨章节语义边。
  |
  v
upsert graph
persist
  按 subject + type + normalized_name 复用稳定 KnowledgeUnit。
  写 KnowledgeEdge。
  写 KnowledgeGraphSourceRef。
  标记本轮消失的旧同步节点/边为 deprecated。
  |
  v
finalize
  校验 report 存在。
  |
  v
run_graph_docs_sync_after_doc_build
  返回 graph metrics，由 build runtime / stream 展示进度。
```

失败路径：

```text
prepare --error--> fail --> END
init_run--error--> fail --> END
extract --error--> fail --> END
persist --error--> fail --> END
finalize--error--> fail --> END
```

并行与 fan-in/fan-out 关系摘要：

```text
LangGraph 层
  prepare -> init_run -> extract -> persist -> finalize
  当前没有 LangGraph Send fan-out。
  每个节点负责本阶段输入合同、数据库会话边界、错误归一化和 `node_metrics`。

extract 节点内部
  extract_markdown_chapter_chunks
  + 大章内部有效小节下钻
    extraction task 1 ┐
    extraction task 2 ├─ async gather + semaphore(max=20) -> payload fan-in
    extraction task N ┘

payload fan-in 后
  LLM/fallback units
  + DocGen backbone units
  + structural edges
  + cross-section semantic edges
  -> DB upsert / source refs / deprecate
```


### 1.2 长流程执行合同

这一节是 KG docs-sync 的详细执行合同。字段以当前 state/model 为准，重点写清每一步输入、输出和失败边界。

```text
run_graph_docs_sync_after_doc_build
  输入：
    - subject：学科 slug，所有图谱读写都按 subject 隔离。
    - requested_at：DocGen build 发起时间，用于写 build runtime。
    - build_group_id：同一次 docgen/graph 构建的分组 ID。
    - build_session_id：LangSmith、sync run、source ref 的关联 ID。
    - file_ids：本轮资料文件 ID，只作为来源和 runtime 展示，不再作为独立 file-ingest 入图入口。
    - prompt：用户构建提示，只记录在 runtime，不直接变成节点。
    - llm_snapshot：DocGen 后台任务捕获的 LLM 运行时配置快照。
  输出：
    - dict metrics：写回 graph lane runtime。
    - 如果没有知识文档 Markdown，返回 skipped 风格的零变更 metrics。
  作用：
    - 建立外层 LangSmith root trace。
    - 读取知识文档同步输入。
    - 写 running runtime。
    - 在 use_llm_runtime_snapshot 下调用 kg_doc_sync workflow。
  失败：
    - workflow failed 时结束 root trace 并抛 RuntimeError。

load_knowledge_doc_sync_input
  输入：
    - subject
  输出：
    - KnowledgeDocSyncInput.markdown
    - KnowledgeDocSyncInput.source
    - KnowledgeDocSyncInput.structured_context
  structured_context 包含：
    - doc_version_no：当前发布知识文档版本。
    - docgen_manifest：当前 DocGen manifest。
    - document_summary_json：Subject.document_summary_json。
    - chapters[]：
        knowledge_document_id
        chapter_index
        title
        summary
        source_file_ids
        source_scope
        manifest
  作用：
    - 把数据库里的发布文档和 DocGen 结构化产物变成同步输入。
    - graph runtime 章节预览复用 extract_markdown_chapter_chunks，避免和真实同步切章规则不一致。
  当前模型方案：
    - 无 LLM。

run_graph_docs_sync_workflow
  输入：
    - subject / markdown / build_revision_no / build_session_id / subject_context / structured_context
  输出：
    - WorkflowResult[KnowledgeSyncReport]
  作用：
    - 标准化输入。
    - 创建 WorkflowContext：
        workflow_name="digest.kg_doc_sync"
        metadata.build_session_id
        metadata.lane="graph"
        metadata.langsmith_run_name
        metadata.build_revision_no
    - 调用 run_state_graph。
  当前模型方案：
    - 无直接 LLM。

prepare
  输入：
    - DocsSyncState.subject
    - DocsSyncState.markdown
  输出：
    - subject.strip()
    - error
  作用：
    - 校验 subject 非空。
    - 校验 markdown 非空。
  失败：
    - subject 为空 -> error。
    - markdown 为空 -> error。
  当前模型方案：
    - 无 LLM。

init_run
  输入：
    - subject
    - markdown
    - build_revision_no
    - build_session_id
    - structured_context
  输出：
    - sync_run_context
    - build_revision_no
    - structured_context
    - error
  作用：
    - 打开 managed_session。
    - 校验 Markdown KnowledgeUnit anchors。
    - 创建 KnowledgeGraphSyncRun(status="running")。
    - 把 revision、doc_version、sync_run_id 收口为 sync_run_context。
  失败：
    - Markdown anchor 非法或 sync run 创建失败都会写入 error。
  当前模型方案：
    - 无 LLM。

extract
  输入：
    - subject
    - markdown
    - subject_context
    - sync_run_context
  输出：
    - extraction_payload
    - subject_context
    - error
  作用：
    - 如果 subject_context 为空，从学科上下文读取。
    - 先按真实章节切分 Markdown，再对过大的章节按有效小节下钻成 extraction task。
    - 并发抽取图谱候选，并发硬上限 20。
    - 合并 LLM/fallback units、DocGen backbone、结构边和跨章节语义边。
  失败：
    - 抽取异常写入 error，fail 节点会标记 sync run failed。
  当前模型方案：
    - 节点本身无直接 LLM；内部 extractor 可能调用 LLM。

persist
  输入：
    - sync_run_context
    - extraction_payload
  输出：
    - KnowledgeSyncReport
    - error
  作用：
    - 写入 KnowledgeUnit / KnowledgeEdge。
    - 写 KnowledgeGraphSourceRef。
    - 标记本轮消失的旧同步节点/边为 deprecated。
    - 结束 sync run 为 completed。
  失败：
    - DB 写入异常写入 error，persist 阶段或 fail 节点会标记 sync run failed。
  当前模型方案：
    - 无 LLM。

sync_markdown_knowledge_graph
  输入：
    - session
    - subject
    - markdown
    - build_revision_no
    - enable_rag_dedup
    - subject_context
    - structured_context
    - build_session_id
  输出：
    - KnowledgeSyncReport
  作用：
    - 兼容旧调用方的一口气 façade，内部顺序调用 init_run / extract / persist 阶段 API。
  当前模型方案：
    - 函数本身无 LLM；extract 阶段可能调用 extractor。

extract_markdown_chapter_chunks
  输入：
    - markdown
  输出：
    - MarkdownSectionChunk[]
  作用：
    - 决定 docs-sync 的并行粒度。
  规则：
    - 多个 H1：按 H1 切章。
    - 一个 H1 且包含多个 H2：把 H1 当文档标题，按 H2 切章。
    - 没有 H1：用 heading-scoped section 兜底。
    - 完全没有 heading 但有正文：生成 `Knowledge Document` 兜底 chunk。
  设计目的：
    - 避免把整本文档标题或学习总览当成知识点。

_build_extraction_tasks
  输入：
    - chapter chunks
    - structured_context.chapters
  输出：
    - extraction task[]
    - chapter_split_count / chapter_task_count / subsection_task_count
  规则：
    - 普通章节：一个 chapter chunk 对应一个 extraction task。
    - 大章：如果内部至少有 2 个有效小节，且正文较长或小节数不少于 3，则改为按子小节抽取。
    - 小节有效性：正文、摘要或图片至少有一个能支撑抽取，避免空标题占用 LLM。
    - 每个 task 仍保留原始 chapter_index/source_file_ids/knowledge_document_id，source ref 不会丢来源。
  设计目的：
    - 与 DocGen 的章节并行保持一致：能按章节并行，也能把过大的章节拆细。
    - 不把并发无限放开；实际 semaphore 上限固定为 20。

_extract_chapter_with_retries
  输入：
    - chapter_index
    - MarkdownSectionChunk
    - subject_context
    - ChapterSourceContext
  输出：
    - SectionExtractionPayload
  并发：
    - `_DOCS_SYNC_CHAPTER_CONCURRENCY_LIMIT = 20`
    - `_DOCS_SYNC_MAX_PARALLEL_EXTRACTIONS = 20`
    - `_DOCS_SYNC_CHAPTER_MAX_RETRIES = 2`
    - `_DOCS_SYNC_CHAPTER_RETRY_DELAY_S = 0.4`
    - `_DOCS_SYNC_SECTION_LLM_TIMEOUT_S = 25`，只作为单章断路保护，不作为提速手段。
    - `_DOCS_SYNC_SECTION_LLM_MAX_CONTENT_CHARS = 5200`，主抽取仍走 LLM，但会限制单章输入窗口。
  SectionExtractionPayload 包含：
    - units：本章候选 MarkdownKnowledgeUnit。
    - pending_edges：尚未解析 endpoint anchor 的边。
    - candidate_id_to_anchor：LLM candidate id 到本地 anchor。
    - anchors_by_name：名称到 anchor 列表。
    - anchors_by_normalized_name：规范化名称到 anchor 列表。
    - node_contexts_by_anchor：跨章节边推断用的节点上下文。
    - section_context：本章主节点和来源上下文。
    - diagnostics：本章抽取计数。
  当前模型方案：
    - 主抽取走 `KGDocSyncModelStep.SECTION_GRAPH`，即 `call_purpose=EXTRACT + model="light"`，`max_tokens=1600`。
    - docs 空结果修复走 `KGDocSyncModelStep.EMPTY_REPAIR`，即 `call_purpose=EXTRACT + model="light"`，`max_tokens=900`。
    - 题目 fallback 中的 LLM 概念抽取走 `KGDocSyncModelStep.QUESTION_CONCEPTS`，即 `call_purpose=DOCGEN_LIGHT + model="light"`。

_extract_chapter_graph_items
  输入：
    - chapter markdown body
    - subject_context
    - sibling_topics
    - digest_mode
    - chapter_topic_hints
    - ChapterSourceContext
  输出：
    - SectionExtractionPayload
  候选来源：
    - LLM structured extraction：主路径。
    - docs support result：LLM 空结果或节点过少时，用标题、正文和 typed lines 生成兜底。
    - topic fallback：LLM 报错或空结果时，用语义标题路径兜底。
    - question fallback：题目密集内容下从题干反推概念/方法。
  可恢复异常：
    - 单个 task 的 LLM 报错、空结果和 repair 情况会累计到 diagnostics。
    - 如果 fallback 成功，workflow 不会失败；LangSmith/Runtime 通过 `llm_error_count`、`empty_llm_result_count`、`empty_repair_*` 判断质量风险。
  过滤：
    - `candidate_quality.filter_docs_candidate_result` 会丢弃明显不是知识点的候选。
    - 典型拒绝项：学习目标、章节导读、本章自检、考前复盘、题型例练、速判口诀、解题入口、解题模板、题干句、任务句、规划句、模块权重排序、知识组合策略等。
  重要边界：
    - LLM 负责语义候选。
    - 规则过滤只硬挡肉眼确定的坏节点，不替代语义抽取。

payload fan-in
  输入：
    - SectionExtractionPayload[]
  输出：
    - units
    - resolved edges
    - diagnostics_totals
  步骤：
    1. `_make_payload_anchors_unique` 做全局 anchor 去重。
    2. 合并 anchors_by_name / anchors_by_normalized_name。
    3. `_build_backbone_graph_items` 消费 DocGen backbone：
       - `docgen_manifest.document_backbone_snapshot`
       - fallback: `document_summary_json.document_backbone`
    4. `canonical_glossary` 只补缺失 term，不覆盖已经由正文抽到的同名概念。
    5. `concept_dependency_graph` 生成关系：
       - `chapter_order` -> `prerequisite`
       - 其它 relation 走 normalize_relation_type。
    6. `_build_structural_heading_edges` 补标题结构边。
    7. `_build_cross_section_semantic_edges` 补保守跨章节语义边。
    8. 解析 pending edge endpoints，不能解析或自环则跳过。
  当前模型方案：
    - 无 LLM。

upsert graph
  输入：
    - units
    - resolved edges
    - sync_run
    - revision_no
  输出：
    - KnowledgeUnit / KnowledgeEdge / KnowledgeGraphSourceRef
    - deprecated ids
  步骤：
    1. `_upsert_unit`
       - 按 `subject + knowledge_unit_type + normalized_name` 优先复用旧节点。
       - 可选 RAG dedup 用于更宽松的语义合并。
       - 更新 aliases/evidence/revision 等兼容字段。
    2. `_create_source_ref_for_unit`
       - 写 `entity_type="unit"` 的 source ref。
       - 保存 sync_run_id、knowledge_document_id、chapter_index、anchor、source_kind、source_file_ids、quote_text、confidence。
    3. `_upsert_edge`
       - 按 source/target/type upsert。
       - 写入前必须通过 validate_relation_direction。
    4. `_create_source_ref_for_edge`
       - 写 `entity_type="edge"` 的 source ref。
    5. `_deprecate_removed_anchor_units`
       - 本轮没有出现的 markdown sync 节点标记 deprecated。
    6. `_deprecate_removed_sync_edges`
       - 本轮没有出现的 sync edge 标记 deprecated。
  当前模型方案：
    - 无 LLM。

finalize
  输入：
    - report
    - error
  输出：
    - 原 state
  作用：
    - 确保 persist 阶段已经产生 report。
  失败：
    - report 缺失 -> error。
  当前模型方案：
    - 无 LLM。

fail
  输入：
    - 任意带 error 的 state
  输出：
    - 原 state
  作用：
    - LangGraph 失败收口节点。
    - 如果 state 中已经有 sync_run_context，会尽量把对应 sync run 标记为 failed。
  当前模型方案：
    - 无 LLM。
```

## 2. 输出与 Runtime Metrics

`KnowledgeSyncReport` 关键字段：

| 字段 | 含义 |
| --- | --- |
| `build_revision_no` | 本轮图谱 revision |
| `doc_version_no` | 同步的知识文档版本 |
| `synced_unit_keys` | 本轮 active anchor 列表 |
| `created_unit_ids / updated_unit_ids / deprecated_unit_ids` | 节点变化 |
| `created_edge_ids / updated_edge_ids / deprecated_edge_ids` | 边变化 |
| `section_count / chapter_count` | 实际抽取 task 数 / 顶层章节数 |
| `chapter_split_count / chapter_task_count / subsection_task_count` | 大章下钻数量、按整章抽取数量、按小节抽取数量 |
| `llm_section_count` | 调用过 LLM 的章节数 |
| `fallback_section_count` | 使用 fallback 的章节数 |
| `question_fallback_section_count` | 题目 fallback 数 |
| `topic_fallback_section_count` | topic fallback 数 |
| `llm_error_count` | 可恢复 LLM 报错次数 |
| `empty_llm_result_count` | LLM 返回空候选次数 |
| `empty_repair_attempt_count / empty_repair_success_count` | 空结果修复尝试/成功次数 |
| `total_extracted_node_count / total_extracted_edge_count` | 原始抽取候选计数 |
| `source_ref_count` | source ref 写入数 |
| `backbone_unit_count / backbone_edge_count` | DocGen backbone 补入数量 |
| `stable_anchor_count` | 本轮稳定 anchor 数 |
| `elapsed_ms` | 同步耗时 |

`run_graph_docs_sync_after_doc_build` 会把这些转换成 graph lane metrics：

| runtime metric | 来源 |
| --- | --- |
| `knowledge_doc_source` | `KnowledgeDocSyncInput.source` |
| `knowledge_doc_chapter_count` | `extract_doc_chapter_metadatas` |
| `doc_sync_unit_changes` | `report.unit_change_count` |
| `doc_sync_edge_changes` | `report.edge_change_count` |
| `doc_sync_elapsed_ms / elapsed_ms` | `report.elapsed_ms` |
| `revision_no` | `report.build_revision_no` |
| `last_synced_doc_version_no` | 当前文档版本 |
| `doc_sync_section_count` | `report.section_count` |
| `doc_sync_chapter_split_count` | `report.chapter_split_count` |
| `doc_sync_chapter_task_count` | `report.chapter_task_count` |
| `doc_sync_subsection_task_count` | `report.subsection_task_count` |
| `doc_sync_llm_section_count` | `report.llm_section_count` |
| `doc_sync_fallback_section_count` | `report.fallback_section_count` |
| `doc_sync_question_fallback_section_count` | `report.question_fallback_section_count` |
| `doc_sync_topic_fallback_section_count` | `report.topic_fallback_section_count` |
| `doc_sync_llm_error_count` | `report.llm_error_count` |
| `doc_sync_empty_llm_result_count` | `report.empty_llm_result_count` |
| `doc_sync_empty_repair_attempt_count / doc_sync_empty_repair_success_count` | `report.empty_repair_*` |
| `source_ref_count` | `report.source_ref_count` |
| `backbone_unit_count / backbone_edge_count` | `report.backbone_*` |
| `stable_anchor_count` | `report.stable_anchor_count` |
| `deprecated_unit_count / deprecated_edge_count` | `report.deprecated_*` |

`graph_input_paths` 当前表达：

```text
knowledge_doc  -> 本轮读取了发布知识文档 Markdown
source_files   -> 本轮携带源文件 ID，用于来源展示和 source ref
none           -> 没有可同步输入
```

它不再使用旧的 `chunks` 表达，因为解析文件直接入图已经不是公开构建路径。

## 3. 调试入口和常见坏味道

当前没有独立图谱 debug tab，也没有公开的文件上传入图按钮。调试方式应该是：

1. 重新生成或导入知识文档。
2. 触发知识文档页上的构建。
3. 查看 graph lane runtime / LangSmith trace。
4. 在节点详情里看 `source_refs`，确认节点来自正文抽取、fallback 还是 `docgen_backbone`。

常见现象：

| 现象 | 高概率原因 | 优先检查 |
| --- | --- | --- |
| “题型例练 / 速判口诀 / 学习目标”入图 | LLM 抽取太宽或过滤词表没覆盖 | `candidate_quality.filter_docs_candidate_result`、extractor prompt、节点 `source_kind` |
| 节点来自 `docgen_backbone` 且像规划句 | DocGen `canonical_glossary` 把章节计划词当 term | `document_backbone_snapshot.canonical_glossary` |
| 节点标题像整本文档标题 | 切章规则没有按 H2 下沉 | `extract_markdown_chapter_chunks`、DocGen 发布 Markdown 标题层级 |
| LLM output 为空但最终仍有节点 | LLM 返回空候选后触发了 empty repair、docs support、topic fallback 或 DocGen backbone | `doc_sync_empty_llm_result_count`、`doc_sync_empty_repair_*`、`doc_sync_topic_fallback_section_count`、`backbone_unit_count` |
| trace 里看到 LLM error 但 workflow 成功 | 单个 task 的 LLM 异常被可恢复 fallback 接住，最终写图成功 | `doc_sync_llm_error_count`、`fallback_section_count`、`KnowledgeGraphSyncRun.metrics_json` |
| 图上边很少 | LLM 边被过滤、endpoint 未解析、方向不合法 | `knowledge_graph_edge_skipped_unresolved_endpoint` 日志、`validate_relation_direction` |
| source refs 为空 | 写入阶段异常或旧数据来自兼容字段 | `knowledge_graph_source_ref`、`KnowledgeGraphSyncRun.metrics_json` |
| LangSmith 看不到子调用 | 外层没有 root trace、async context 没传递，或 LLM 调用没有继承 node scope | `run_graph_docs_sync_after_doc_build`、`run_state_graph`、`_run_async(contextvars.copy_context())` |

## 4. 当前仍需关注的问题

1. 旧 `kg_file_ingest` workflow 已删除；`kg_doc_sync/lib/extraction.py` 是 docs-sync 的正式抽取实现入口。
2. docs-sync 的 LLM 主抽取默认走 `call_purpose=EXTRACT + model="light"`，速度可控，但复杂学科的概念归并仍可能偏保守。后续如果要提高质量，应增加一个“章级候选审稿/归并”步骤，而不是放开所有候选直接入图。
3. 规则过滤只能挡明显坏节点，不能替代 LLM 的语义判断。过滤词表应该短、强、可解释；如果持续出现某类坏节点，优先修 extractor prompt 和候选审稿。
4. `aliases_json/evidence_refs_json` 仍是兼容字段。新查询应优先使用 `knowledge_graph_source_ref`，等图谱查询稳定后再考虑数据规模化优化。
