# kg_doc_sync Flow Design

最后更新：2026-04-28

`kg_doc_sync` 是知识文档到知识图谱的正式同步链路。它不再直接解析用户上传的原始文件；正式落库输入仍然只有当前课程已经发布的 `KnowledgeDoc`、DocGen 结构化产物、章节来源映射和 `Course.document_summary_json`。自动同步可以复用 DocGen 期间产生的内存预抽取缓存，但发布前不会写 `knowledge_unit / knowledge_edge`。除 DocGen 发布后的自动同步外，前端知识图谱面板可以调用 `/api/v1/courses/{course}/knowledge/build/graph` 手动重建图谱；该入口仍然只从已入库的知识文档和 manifest 读取输入，不依赖预抽取缓存，也不接收前端临时 Markdown。

当前写入的核心表：

- `knowledge_unit`
- `knowledge_edge`
- `knowledge_graph_sync_run`
- `knowledge_graph_source_ref`

本链路不会创建 `curriculum / teaching_unit / taxonomy_anchor / theme_tree_node / unit_dependency` 等未来大表。节点和关系的可解释来源先由轻量溯源表承接。

KG-doc-sync 抽取 ontology 位于 `backend/app/workflows/digest/kg_doc_sync/lib/ontology.py`，集中维护抽取 prompt 展示的 KnowledgeUnit 类型、关系类型、关系端点偏好和跨章节默认边推断。持久化层允许的类型集合、归一化和最终关系方向守卫仍位于 `backend/app/models/knowledge_taxonomy.py`，避免模型层反向依赖 workflow；抽取 prompt 与 extractor 的候选解析规则都从 workflow ontology 读取，测试负责确保两者与枚举保持一致。

LangGraph 节点的 `node_description`、输入输出字段和 metadata 统一通过
`digest.common.node_tracing` 生成；自动同步和手动重建都进入同一个 `digest.kg_doc_sync`
LangGraph 链路，避免 Trace 列表被 anchor 校验、候选抽取和图谱写入刷屏。
每个节点都会写入 `node_metrics.<node>`，用于在 trace 和最终 state 中查看本阶段输入规模、
并发配置、sync_run id、抽取统计、写库变更数和失败标记结果。

目录入口约定：

- `graph.py`：LangGraph 定义、initial state、路由、`run_graph_docs_sync_workflow` 单次运行入口和 LangGraph dev 导出。
- `builds.py`：DocGen 发布后的自动同步、手动重建、graph lane runtime 与后台任务编排。
- `inputs.py`：从已发布 `KnowledgeDoc`、manifest 和结构化上下文组装同步输入。
- `lib/prefetch.py`：DocGen sidecar 预抽取协调器，按 `course + build_session_id` 管理内存 section payload 缓存。
- `nodes/`：只放 LangGraph 顶层节点。
- `lib/`：节点内部复用逻辑、抽取合同、候选过滤、增量写库、查询、总览和清理。
- `prompts/`：只放 prompt builder。当前抽取提示词、ontology 展示文案和结构化 schema 描述统一使用中文；枚举值仍保留英文稳定值，便于落库和关系方向校验。

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
- Prompt 文件按真实调用拆分：章节图谱抽取在 `prompts/section_graph.py`，导出聚合在 `prompts/registry.py`；提示词正文必须以中文教学语境为主。
- 核心 lib 按职责拆分：`models.py` 放 state/report 数据合同，`sync_runs.py` 放同步批次状态写入，`question_blocks.py` 只用于题目块识别和抽取辅助判断，不再生成兜底知识点。

按当前代码，KG docs-sync 各阶段的大模型使用如下：

| 阶段 / 子步骤 | 当前代码位置 | 调用类型 | call_purpose | 逻辑模型槽位 | 当前默认模型 | 这一步做什么 |
| --- | --- | --- | --- | --- | --- | --- |
| `trigger_graph_docs_sync_manual_build` | `kg_doc_sync/builds.py` | 无 LLM | 无 | 无 | 无 | 手动图谱重建入口；由 API 完成鉴权后调用，校验已有发布文档，写 graph lane accepted runtime，并注册可取消的后台任务 |
| `docgen kg_prefetch sidecar` | `kg_doc_sync/lib/prefetch.py` | 间接 LLM | `EXTRACT` | `light` | `qwen-flash` | DocGen 增强章节完成后后台预抽取 section payload，只进内存缓存，不落库 |
| `run_graph_docs_sync_auto_build` | `kg_doc_sync/builds.py` | 无 LLM | 无 | 无 | 无 | DocGen 发布完成后独立注册的自动图谱后台任务，消费并停止同 build 的预抽取 sidecar |
| `run_graph_docs_sync_after_doc_build` | `kg_doc_sync/builds.py` | 无 LLM | 无 | 无 | 无 | 读取发布文档、写 graph lane runtime，并把可复用预抽取 payload 传入 `digest.kg_doc_sync` |
| `load_knowledge_doc_sync_input` | `kg_doc_sync/inputs.py` | 无 LLM | 无 | 无 | 无 | 读取 `KnowledgeDoc` rows、DocGen manifest、文档摘要和章节来源映射 |
| `prepare` | `kg_doc_sync/nodes/prepare_node.py` | 无 LLM | 无 | 无 | 无 | 校验 `course` 和合并 Markdown |
| `init_run` | `kg_doc_sync/nodes/init_run_node.py` | 无 LLM | 无 | 无 | 无 | 校验 Markdown anchors，创建 `knowledge_graph_sync_run`，确定 revision/doc_version |
| `extract` | `kg_doc_sync/nodes/extract_node.py` | 间接 LLM | 由内部 extractor 决定 | 由 policy 决定 | 见下方 | 加载课程上下文，按章节并发抽取图谱候选并合并 backbone/结构边 |
| `stitch_relations` | `kg_doc_sync/nodes/stitch_node.py` | 无 LLM | 无 | 无 | 无 | 在写库前用同小节关系和显式正文引用补少量保守边，并计算孤立率、连通分量等健康指标 |
| `persist` | `kg_doc_sync/nodes/persist_node.py` | 无 LLM | 无 | 无 | 无 | 写入节点、关系、source_ref，标记旧同步实体 deprecated，并完成 sync run |
| `_extract_chapter_graph_items` 主抽取 | `kg_doc_sync/lib/incremental_sync.py` -> `kg_doc_sync/lib/extraction.py` | 结构化 | `EXTRACT` | `light` | `qwen-flash` | 从单章 Markdown 抽取候选 KnowledgeUnit 和关系 |
| `_repair_docs_extraction_after_empty` | `kg_doc_sync/lib/extraction.py` | 结构化 | `EXTRACT` | `light` | `qwen-flash` | 当 docs-sync 主抽取为空时做一次极短修复抽取 |
| `_build_backbone_graph_items` | `kg_doc_sync/lib/incremental_sync.py` | 无 LLM | 无 | 无 | 无 | 只用 DocGen `document_backbone` 给已抽取节点补关系，不创建保底节点 |
| `_build_structural_heading_edges` | `kg_doc_sync/lib/incremental_sync.py` | 无 LLM | 无 | 无 | 无 | 用标题层级补结构边 |
| `_build_cross_section_semantic_edges` | `kg_doc_sync/lib/incremental_sync.py` | 无 LLM | 无 | 无 | 无 | 基于节点上下文补跨章节语义边 |
| upsert / source ref / deprecate | `kg_doc_sync/lib/incremental_sync.py` | 无 LLM | 无 | 无 | 无 | 写入节点、关系、同步批次、来源引用和过期标记 |

当前自动同步主线：

```text
DocGen enhance_chapters
  如果 sync_after_docgen + prefetch_during_docgen 开启，启动 kg_prefetch sidecar。
  sidecar 读取增强章节 Markdown、document_backbone、intent_profile、chapter_task_seeds、chapter_execution_briefs 和 chapter_generation_plan。
  sidecar 只缓存 section_key + content_hash + SectionExtractionPayload，不写图谱表。
  默认 prefetch_concurrency = 2，仍受全局 LLM semaphore 限制，并先让后续 DocGen review 调度。
  |
  v
DocGen review / repair / merge / publish
  DocGen 主路径不等待 sidecar；发布失败或取消时丢弃预抽取缓存。
  |
  v
run_docgen_background
  DocGen 发布完成后，docgen lane 立即 completed，页面可直接读取正式 KnowledgeDoc。
  如果 sync_after_docgen 打开，再注册独立 graph 后台任务进入 graph lane。
  |
  v
run_graph_docs_sync_after_doc_build
  读取当前发布知识文档和结构化上下文。
  消费并停止同 build_session_id 的预抽取 sidecar。
  写入 graph lane running runtime。
  |
  v
load_knowledge_doc_sync_input
  从 DB 读取当前 KnowledgeDoc rows。
  合并章节 Markdown。
  读取 docgen_manifest / document_backbone / Course.document_summary_json。
  组装 structured_context。
  |
  v
run_graph_docs_sync_workflow
  创建 WorkflowContext(workflow_name="digest.kg_doc_sync")。
  调用 run_state_graph，LangSmith 中能看到 kg_doc_sync 主链路。
  |
  v
prepare
  校验 course 和 Markdown。
  |
  v
init_run
  校验 Markdown anchors。
  创建 KnowledgeGraphSyncRun(status="running")。
  生成 sync_run_context。
  |
  v
extract
  如果 course_context 为空，则从课程 LLM context 读取。
  按真实章节切分 Markdown；大章会按子章节继续拆成多个抽取任务。
  对每个最终 section 计算 section_key + content_hash：
    - 命中预抽取缓存：补齐最终 knowledge_document_id / source_file_ids 后复用。
    - 未命中或缓存失败：按正常路径补抽。
  LLM 子调用挂在 extract 节点下。
  |
  v
_extract_chapter_with_retries x N
  单节点内部 async fan-out：
    ├─ chapter 1 extraction
    ├─ chapter 2 / subsection 2.1 extraction
    └─ chapter N / subsection N.x extraction
  正式同步默认最多 16 路抽取并发，并会保留全局 LLM 并发余量；每个抽取任务最多 2 次尝试；单任务 LLM 输入会保留开头和结尾并压到固定字符预算内。
  通过 contextvars 继承外层运行上下文，让 LLM 子调用挂在同一条 trace 下。
  |
  v
fan-in extraction payloads
  合并所有章节候选。
  做全局 anchor 去重。
  合并 LLM 候选和 DocGen backbone 候选。
  补结构边和跨章节语义边。
  |
  v
stitch_relations
  不调用 LLM、不访问数据库。
  同一小节内把定义、公式、例题、方法、易错点连接到主概念。
  对仍然孤立且正文明确引用其它唯一知识点的节点补少量引用边。
  计算孤立节点数、连通分量、最大连通分量和平均度。
  |
  v
upsert graph
persist
  按 course + type + normalized_name 复用稳定 KnowledgeUnit。
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

手动重建主线：

```text
trigger_graph_docs_sync_manual_build
  用户在知识图谱面板点击“构建图谱”。
  API 路由只负责 course 鉴权和响应包装。
  从当前已发布 KnowledgeDoc 和 manifest 读取输入。
  不读取、不等待、不复用 DocGen 预抽取缓存。
  后续仍走 prepare -> init_run -> extract -> stitch_relations -> persist -> finalize。
```

失败路径：

```text
prepare --error--> fail --> END
init_run--error--> fail --> END
extract --error--> fail --> END
stitch_relations --error--> fail --> END
persist --error--> fail --> END
finalize--error--> fail --> END
```

并行与 fan-in/fan-out 关系摘要：

```text
LangGraph 层
  prepare -> init_run -> extract -> stitch_relations -> persist -> finalize
  当前没有 LangGraph Send fan-out。
  每个节点负责本阶段输入合同、数据库会话边界、错误归一化和 `node_metrics`。

extract 节点内部
  extract_markdown_chapter_chunks
    chapter 1 ┐
    chapter 2 ├─ async gather + semaphore -> payload fan-in
    chapter N ┘

payload fan-in 后
  LLM units
  + DocGen backbone units
  + structural edges
  + cross-section semantic edges
  + relation stitching edges
  -> DB upsert / source refs / deprecate
```

### 1.2 长流程执行合同

这一节是 KG docs-sync 的详细执行合同。字段以当前 state/model 为准，重点写清每一步输入、输出和失败边界。

```text
trigger_graph_docs_sync_manual_build
  输入：
    - course_id：课程主键，形如 course_xxx。
  前置校验：
    - 当前课程必须存在。
    - docgen lane 不能处于 accepted/running/publishing。
    - graph lane 不能处于 accepted/running/publishing。
    - 必须已经有发布版 KnowledgeDoc Markdown。
  作用：
    - 只读取数据库中的 `KnowledgeDoc`、`KnowledgeDocsManifest` 和 structured_context。
    - 写入 graph lane `manual_graph_requested` runtime，记录 source_file_ids、prompt、doc_version 和输入来源。
    - 通过后台任务注册 `knowledge.build.graph`，因此 `/knowledge/build/cancel` 可以停止本轮手动图谱构建。
    - 后台任务最终进入 `run_graph_docs_sync_after_doc_build`，LangSmith 中看到的仍是同一条 `digest.kg_doc_sync` 链路。

run_graph_docs_sync_auto_build
  输入：
    - DocGen 刚发布完成的 course、build_group_id、build_session_id、source file ids、prompt、llm_snapshot 和 final docgen_state。
  作用：
    - 由 `run_docgen_background` 在 docgen lane 已经 completed 后独立注册，不阻塞知识文档展示和 docgen 构建锁释放。
    - 最终仍进入 `run_graph_docs_sync_after_doc_build`，与手动重建共用同一条 kg_doc_sync 主链路。

run_graph_docs_sync_after_doc_build
  输入：
    - course_id：课程主键，所有图谱读写都按 course_id 隔离。
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
    - 读取知识文档同步输入。
    - 写 running runtime。
    - 在 use_llm_runtime_snapshot 下调用 kg_doc_sync workflow。
  失败：
    - workflow failed 时抛 RuntimeError，由自动同步或手动重建的后台任务写入 graph lane failed runtime。

load_knowledge_doc_sync_input
  输入：
    - course
  输出：
    - KnowledgeDocSyncInput.markdown
    - KnowledgeDocSyncInput.source
    - KnowledgeDocSyncInput.structured_context
  structured_context 包含：
    - doc_version_no：当前发布知识文档版本。
    - docgen_manifest：当前 DocGen manifest。
    - document_summary_json：Course.document_summary_json。
    - chapters[]：
        knowledge_document_id
        chapter_index
        title
        summary
        digest_mode
        source_file_ids
        source_scope
        manifest
    - ChapterSourceContext 会额外从 docgen_manifest / document_summary_json 合并章级辅助信号：
        intent_profile
        chapter_task_seeds
        chapter_execution_briefs
        chapter_generation_plan / chapter_generation_plan_seed
        Course.learning_intent_text 渲染后的 llm_context_text
  作用：
    - 把数据库里的发布文档和 DocGen 结构化产物变成同步输入。
    - graph runtime 章节预览复用 extract_markdown_chapter_chunks，避免和真实同步切章规则不一致。
  当前模型方案：
    - 无 LLM。

run_graph_docs_sync_workflow
  输入：
    - course / markdown / build_revision_no / build_session_id / course_context / structured_context
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
    - DocsSyncState.course
    - DocsSyncState.markdown
  输出：
    - course.strip()
    - error
  作用：
    - 校验 course 非空。
    - 校验 markdown 非空。
  失败：
    - course 为空 -> error。
    - markdown 为空 -> error。
  当前模型方案：
    - 无 LLM。

init_run
  输入：
    - course
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
    - course
    - markdown
    - course_context
    - sync_run_context
  输出：
    - extraction_payload
    - course_context
    - error
  作用：
    - 如果 course_context 为空，从课程上下文读取。
    - 按真实章节切分 Markdown。
    - 将 DocGen 章级中间产物放在每个 section prompt 的上下文开头，避免被截断；这些信号只用于消歧和抽取重点，不作为节点证据。
    - 并发抽取图谱候选。
    - 合并 LLM units、DocGen backbone 关系、结构边和跨章节语义边。
  失败：
    - 抽取异常写入 error，fail 节点会标记 sync run failed。
  当前模型方案：
    - 节点本身无直接 LLM；内部 extractor 可能调用 LLM。

stitch_relations
  输入：
    - extraction_payload
  输出：
    - extraction_payload
    - error
  作用：
    - 用纯本地规则补充 conservative edges，减少“有节点但无关系”的散点。
    - 同一小节中存在主概念时，把 definition / formula / theorem / example / exercise / method / remark 连接到主概念。
    - 对仍然孤立的节点，如果其正文明确提到其它唯一节点名，补少量 mention_stitch 边。
    - 计算 graph_isolated_unit_count / graph_component_count / graph_largest_component_unit_count / graph_avg_degree / graph_isolated_unit_pct。
  失败：
    - 缝合异常写入 error，fail 节点会标记 sync run failed。
  当前模型方案：
    - 无 LLM。

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
    - course
    - markdown
    - build_revision_no
    - enable_rag_dedup
    - course_context
    - structured_context
    - build_session_id
  输出：
    - KnowledgeSyncReport
  作用：
    - 单函数同步入口，内部顺序调用 init_run / extract / stitch / persist 阶段 API。
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
    - MarkdownSectionChunk[]
    - ChapterSourceContext 映射
  输出：
    - 章节/子章节抽取任务
  规则：
    - 章节正文长度达到 `_DOCS_SYNC_SPLIT_MIN_CHAPTER_CHARS = 2400` 且至少有 2 个可抽取子章节时，按子章节拆分。
    - 即使章节未达到 2400 字，只要存在 4 个以上可抽取子章节，也按小节拆分，避免大章只触发一次超大块 LLM 抽取。
    - 不满足拆分条件时，保持整章作为一个 LLM 抽取任务。
    - 总任务规划上限来自 `settings.knowledge_graph.max_parallel_extractions`，默认 16；旧 `KG_DOC_SYNC_MAX_PARALLEL_EXTRACTIONS` 只作为低层兜底。
    - 任务规划会先以章节为基线；章节少而大章很长时，再按子章节和字符预算自适应拆分，最多扩展到配置上限。
  设计目的：
    - 章节少但单章较长或结构清晰时，仍然可以并行抽取，减少大块结构化输出失败和长章卡住整条链路的情况。
    - 所有语义候选仍由结构化 LLM 抽取或 LLM 空结果修复产生，不引入本地关键词造点。

_extract_chapter_with_retries
  输入：
    - chapter_index
    - MarkdownSectionChunk
    - course_context
    - ChapterSourceContext
  输出：
    - SectionExtractionPayload
  并发：
    - 正式同步并发上限默认 16，来自 `settings.knowledge_graph.max_parallel_extractions`，并会为出题等交互任务预留一小段全局 LLM 并发余量。
    - DocGen sidecar 预抽取并发默认 2，来自 `settings.knowledge_graph.prefetch_concurrency`。
    - `_DOCS_SYNC_SPLIT_MIN_CHILD_SECTIONS = 2`
    - `_DOCS_SYNC_SPLIT_MIN_CHAPTER_CHARS = 2400`
    - `_DOCS_SYNC_SPLIT_TARGET_TASK_CHARS = 1800`
    - `_DOCS_SYNC_CHAPTER_MAX_RETRIES = 2`
    - `_DOCS_SYNC_CHAPTER_RETRY_DELAY_S = 0.4`
    - `_DOCS_SYNC_SECTION_LLM_TIMEOUT_S = 90`，与共享 EXTRACT LLM profile 对齐，避免外层短超时把结构化调用取消成 `CancelledError` 噪声。
    - `_DOCS_SYNC_SECTION_LLM_MAX_CONTENT_CHARS = 9000`，主抽取仍走 LLM，但会限制单章输入窗口。
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
    - 主抽取走 `KGDocSyncModelStep.SECTION_GRAPH`，即 `call_purpose=EXTRACT + model="light"`，`max_tokens=2200`，并限制单片段最多 8 个节点、10 条关系。
    - docs 空结果修复走 `KGDocSyncModelStep.EMPTY_REPAIR`，即 `call_purpose=EXTRACT + model="light"`，`max_tokens=900`。
    - 结构化抽取失败会按任务重试；重试耗尽后让图谱同步失败，不再用标题或题目关键词本地生成 KnowledgeUnit。

_extract_chapter_graph_items
  输入：
    - chapter markdown body
    - course_context
    - sibling_topics
    - digest_mode
    - chapter_topic_hints
    - ChapterSourceContext
      - title / summary
      - digest_mode
      - docgen_hints：由 chapter_task_seeds、chapter_execution_briefs、chapter_generation_plan 和 document_summary_json 汇总的章级目标、候选概念、定义/公式、例题/易错线索
  输出：
    - SectionExtractionPayload
  候选来源：
    - LLM structured extraction：主路径。
    - LLM empty repair：主抽取为空且章节有明显知识信号时，再走一次结构化 LLM 修复。
    - DocGen backbone：只作为保底结构信号。它是 DocGen 的 rule-first 结构化产物，不等价于 section 级 LLM 抽取；同步入图时不再创建 KnowledgeUnit，只能给已经存在的正文抽取节点补关系。
  后处理：
    - 不做语义词表过滤；LLM 返回的候选会保留，方便暴露和追踪抽取质量问题。
    - 只做结构性收口：schema 枚举、名称/摘要长度、关系类型归一化、关系方向校验、endpoint 解析和去重。
  重要边界：
    - LLM 负责语义候选。
    - LLM 调用失败会按任务重试；重试耗尽后让同步失败，不再用标题、题干或关键词本地生成 KnowledgeUnit。

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
       - `document_summary_json.document_backbone`
    4. `canonical_glossary` 只记录和已存在节点的章节映射，不创建缺失 term；纯 confirmed plan / required_elements 词条不会直接入图。
    5. `concept_dependency_graph` 只在 source/target 两端都已经由正文抽取存在时生成关系：
       - `chapter_order` -> `prerequisite`
       - 其它 relation 走 normalize_relation_type。
       - 单个章节/子章节 LLM 抽取失败不会让整条图谱链路失败；失败分片会记录为 `failed_section_count` / `llm_error_count`，其它成功分片继续合并并落库。
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
       - 按 `course + knowledge_unit_type + normalized_name` 优先复用旧节点。
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
| `section_count / chapter_count` | 实际抽取任务数 / 原始章节数 |
| `chapter_split_count / chapter_task_count / subsection_task_count` | 被拆分的大章数量、整章任务数、子章节任务数 |
| `llm_section_count` | 调用过 LLM 的抽取任务数 |
| `successful_section_count / failed_section_count` | 成功/失败的章节或子章节抽取任务数；单分片失败会保留成功分片继续写图谱 |
| `llm_error_count` | LLM 主抽取或空结果修复异常次数 |
| `empty_llm_result_count` | LLM 返回空候选的任务数 |
| `empty_repair_attempt_count / empty_repair_success_count` | 空结果 LLM 修复尝试数 / 成功数 |
| `total_extracted_node_count / total_extracted_edge_count` | 原始抽取候选计数 |
| `source_ref_count` | source ref 写入数 |
| `backbone_unit_count / backbone_edge_count` | DocGen backbone 补入数量；unit 当前应为 0，edge 只连接已抽取节点 |
| `stitched_edge_count` | 本地关系缝合补入的边数，不包含 LLM 直接抽取边 |
| `section_local_stitch_edge_count / mention_stitch_edge_count` | 同小节缝合边数 / 正文显式引用缝合边数 |
| `graph_isolated_unit_count / graph_isolated_unit_pct` | 缝合后仍为 0 度的抽取节点数量 / 占比 |
| `graph_component_count / graph_largest_component_unit_count` | 缝合后的无向连通分量数量 / 最大连通分量规模 |
| `graph_avg_degree` | 缝合后的平均无向度 |
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
| `doc_sync_chapter_split_count / doc_sync_chapter_task_count / doc_sync_subsection_task_count` | `report.chapter_split_count / chapter_task_count / subsection_task_count` |
| `doc_sync_successful_section_count / doc_sync_failed_section_count` | `report.successful_section_count / failed_section_count` |
| `doc_sync_llm_section_count` | `report.llm_section_count` |
| `doc_sync_llm_error_count` | `report.llm_error_count` |
| `doc_sync_empty_llm_result_count` | `report.empty_llm_result_count` |
| `doc_sync_empty_repair_attempt_count / doc_sync_empty_repair_success_count` | `report.empty_repair_attempt_count / empty_repair_success_count` |
| `source_ref_count` | `report.source_ref_count` |
| `backbone_unit_count / backbone_edge_count` | `report.backbone_*`；unit 兼容保留，edge 表示 backbone 给已抽取节点补的关系 |
| `stitched_edge_count` | `report.stitched_edge_count` |
| `section_local_stitch_edge_count / mention_stitch_edge_count` | `report.section_local_stitch_edge_count / mention_stitch_edge_count` |
| `graph_isolated_unit_count / graph_isolated_unit_pct` | `report.graph_isolated_unit_count / graph_isolated_unit_pct` |
| `graph_component_count / graph_largest_component_unit_count / graph_avg_degree` | `report.graph_component_count / graph_largest_component_unit_count / graph_avg_degree` |
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
4. 在节点详情里看 `source_refs`，确认节点来自正文抽取还是 `docgen_backbone`。

常见现象：

| 现象 | 高概率原因 | 优先检查 |
| --- | --- | --- |
| “题型例练 / 速判口诀 / 学习目标”入图 | LLM 抽取太宽、上下文误导，或 chunk 本身是教学包装段 | extractor prompt、DocGen 辅助上下文、节点 `source_kind` |
| 节点来自 `docgen_backbone` 且像规划句 | 不应再发生；backbone 不创建节点，只补已抽取节点之间的关系 | `_build_backbone_graph_items`、`document_backbone_snapshot.concept_dependency_graph` |
| 节点标题像整本文档标题 | 切章规则没有按 H2 下沉 | `extract_markdown_chapter_chunks`、DocGen 发布 Markdown 标题层级 |
| 图上边很少 | LLM 边被过滤、endpoint 未解析、方向不合法 | `knowledge_graph_edge_skipped_unresolved_endpoint` 日志、`validate_relation_direction` |
| source refs 为空 | 写入阶段异常或旧数据来自兼容字段 | `knowledge_graph_source_ref`、`KnowledgeGraphSyncRun.metrics_json` |
| LangSmith 看不到子调用 | 没有进入 `run_state_graph`、async context 没传递，或 LLM 调用没有继承 node scope | `run_graph_docs_sync_after_doc_build`、`run_state_graph`、`_run_async(contextvars.copy_context())` |

## 4. 当前仍需关注的问题

1. 旧 `kg_file_ingest` workflow 已删除；`kg_doc_sync/lib/extraction.py` 是 docs-sync 的正式抽取实现入口。
2. docs-sync 的 LLM 主抽取默认走 `call_purpose=EXTRACT + model="light"`，速度可控，但复杂课程的概念归并仍可能偏保守。后续如果要提高质量，应增加一个“章级候选审稿/归并”步骤，而不是放开所有候选直接入图。
3. 当前不再用语义词表过滤候选节点；如果持续出现某类坏节点，优先修 extractor prompt、DocGen 辅助上下文或增加 LLM 审稿/归并步骤。
4. `aliases_json/evidence_refs_json` 仍是兼容字段。新查询应优先使用 `knowledge_graph_source_ref`，等图谱查询稳定后再考虑数据规模化优化。
