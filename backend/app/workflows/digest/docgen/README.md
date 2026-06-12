# DocGen 链路说明

最后更新：2026-06-03

`docgen/` 是 Digest 的第二条链路。它消费 Planner 已确认的 `confirmed_plan`，生成正式知识文档。

```text
Planner 冻结“学什么”。
DocGen 执行“怎么写成可发布、可追踪、可复用的知识文档”。
KG Doc Sync 再把发布后的文档同步成知识图谱。
```

DocGen 不重新推翻用户确认过的章节语义，不直接写 `knowledge_unit / knowledge_edge`。

## 先看这几个文件

```text
docgen/
  graph.py                         # LangGraph 主线、Send fan-out、run_docgen_workflow
  state.py                         # DocGenState，包括 fan-out reducer 字段
  lib/build_lifecycle.py           # API 接受、构建锁、后台任务、自动 KG 派发
  nodes/load_context.py            # 读取 confirmed plan 和资料上下文
  nodes/generate_chapters.py       # 按章生成草稿
  nodes/review_content.py          # 按章复核 + 整本一致性复核
  nodes/publish_document.py        # 发布 Markdown / manifest / KnowledgeDoc
  lib/mode_profiles.py             # sprint/systematic 写作模式、预算和质量阈值
  lib/model_policy.py              # DocGen LLM 策略
  lib/publish.py                   # staging、live、version archive、数据库写入
```

公开入口：

```python
from app.workflows.digest import run_docgen_workflow
from app.workflows.digest.docgen import (
    trigger_docgen_build,
    run_docgen_background,
    get_docgen_result,
    get_knowledge_build_runtime_result,
)
```

## 短流程

```text
0. trigger_docgen_build
   API 同步接受请求：校验 confirmed_plan，锁构建，写 docgen lane accepted runtime。

1. run_docgen_background
   后台加载 ConfirmedBuildPlan，标记 building，运行 DocGen LangGraph。

2. load_context
   冻结 confirmed plan，读取 shared_inputs，生成 chapter_assignments。

3. prepare_global_seed
   并行准备文档级 intent 和文件摘要，产出章节亲和度和高置信证据候选。

4. generate_cover
   可选封面 sidecar，失败不阻断正文。

5. lock_titles_for_chapters
   节点内部按章并行锁定最终章节标题。

6. confirm_backbone_seed -> build_document_backbone
   用 confirmed plan、标题、文件摘要和证据候选构建整本文档知识骨架。

7. build_chapter_execution_briefs -> assemble_chapter_tasks
   按章生成最小执行 brief，再组装最终章节任务。

8. generate_chapters
   LangGraph Send 按章 fan-out：每章独立检索、压缩上下文、写草稿、产出证据/主张/冲突账本。

9. enhance_chapters
   并行做表现层增强：Mermaid、交互 HTML、公式和 Markdown 结构。
   如果 KG 预抽取开启，此处启动非阻塞 kg_prefetch sidecar。

10. review_chapters -> document_consistency_review
    LangGraph Send 按章复核，再做整本文档一致性检查。

11. repair_or_route
    对安全问题做局部 patch；重动作记录为 unresolved warning。

12. merge_review -> sync_locked_titles -> publish_document
    合并整本 Markdown，同步锁定标题，发布文档、manifest 和 KnowledgeDoc rows。

13. run_docgen_background
    DocGen 完成后，如果 sync_after_docgen=true，独立派发 kg_doc_sync 自动同步。
```

并行关系只看这张图：

```text
prepare_global_seed
  ├─ infer_intent_core
  └─ summarize_files

lock_titles_for_chapters
  └─ run_llm_tasks(chapter x N)

build_chapter_execution_briefs
  └─ run_llm_tasks(chapter x N)

assemble_chapter_tasks
  -> Send(generate_chapters, chapter x N)
       -> reducer fan-in: chapter_drafts / traces / ledgers
  -> enhance_chapters
       -> run_llm_tasks(chapter x N)
       -> start_docgen_kg_prefetch(...)  # 可选 sidecar
  -> Send(review_chapters, chapter x N)
       -> reducer fan-in: review overlays / actions / reports
  -> document_consistency_review
```

## 长流程

### 0. 构建生命周期：`lib/build_lifecycle.py`

DocGen 不是 API 一进来就直接跑图。外面先有一层构建生命周期。

`trigger_docgen_build(...)`

- 必须传 `confirmed_plan_id`。
- 读取 `ConfirmedBuildPlan`，以其中的 `selected_file_ids / user_prompt / digest_mode / model_override` 为准。
- 只接受已解析完成的文件；没有 ready file 时进入 search-only mode。
- 检查课程向量状态和构建冲突。
- 写 `KnowledgeBuildLock`。
- 清理 DocGen staging。
- 写 docgen lane runtime：`accepted / build_accepted`。
- 不运行 LangGraph，不写 `KnowledgeDoc`。

`run_docgen_background(...)`

- 生成本次 `build_session_id`。
- 加载 confirmed plan payload。
- 标记 `ConfirmedBuildPlan.status="building"`。
- 写 docgen lane runtime：`running / prepare_shared`。
- 如果 `settings.knowledge_graph.sync_after_docgen=true`：
  - graph lane 先写 `accepted / queued_after_docgen`。
  - 捕获 LLM runtime snapshot，保证自动 KG 同步模型配置不漂移。
- 调 `run_docgen_workflow(...)`。
- 成功：
  - docgen lane 写 `completed`。
  - confirmed plan 写 `completed`。
  - 可选派发 `run_graph_docs_sync_auto_build(...)`。
- 失败或取消：
  - 取消 KG prefetch sidecar。
  - 清理 staging。
  - docgen lane 写 `failed / cancelled`。
  - graph lane 写 `blocked_by_docgen_failure / cancelled`。
  - 释放构建锁。

### 1. 图运行入口：`run_docgen_workflow`

- 创建 `WorkflowContext(workflow_name="digest.docgen")`。
- metadata 带：
  - `build_session_id`
  - `planner_session_id`
  - `confirmed_plan_id`
  - `digest_mode`
  - `model_override`
  - `max_concurrency`
- 使用 `use_runtime_model_override(model_override)` 包住整条图。
- 发布 `DocGenRequestedEvent / DocGenCompletedEvent / DocGenFailedEvent`。
- 图本身成功后会补 `token_summary / timing_summary`。

### 2. 逐节点长流程

读这一节时按 `DocGenState` 的产物推进：前面节点把 state 补成什么，后面节点就拿这些字段继续跑。DocGen 的主线是：

```text
confirmed_plan
  -> DocGenContext / chapter_assignments
  -> intent_core / file_summaries / evidence candidates
  -> locked_titles
  -> document_backbone
  -> chapter_tasks
  -> chapter_drafts
  -> enhanced_chapter_drafts
  -> reviewed_chapter_drafts
  -> merged_markdown
  -> KnowledgeDoc / docgen_manifest
```

#### 2.1 `load_context`：把确认方案装成可运行 state

进来时，graph state 只有构建入口参数：`course_id`、`user_id`、`confirmed_plan_id`、`selected_file_ids`、`requested_at`、`build_session_id`、`digest_mode`、`model_override`。

本节点做四件事：

- 读取并校验 `ConfirmedBuildPlan`，把用户确认过的章节合同作为冻结快照写入 state。
- 读取 `shared_inputs`、资料画像、Planner 上下文和构建历史摘要。
- 把 confirmed plan 的章节转成 `chapter_assignments`，后续每章都从这里派生。
- 生成 `docgen_context`、`document_context`、`retrieval_profile`、`retrieval_policy`，并初始化章节进度。

本节点结束后，DocGen 从“收到一个构建请求”变成“知道要为哪些章节写文档、资料从哪里来、发布上下文是什么”。

边界：

- 不调用 LLM。
- 不改 confirmed plan 的章节语义。
- 不生成正文、标题、骨架或 KG 数据。

#### 2.2 `prepare_global_seed`：做全局轻准备

本节点接收 `chapter_assignments`、用户 prompt、plan summary、历史摘要、文件包和 section 包。

它并行跑两类准备任务：

```text
infer_intent_core
  生成文档级写作意图：学习目标、受众、内容策略、例题/练习策略、证据严格度。

summarize_files
  按文件生成摘要、核心概念、公式、例题、高价值 section 和章节亲和度。
```

写入 state 的关键字段：

- `intent_core` / `intent_profile`：整本文档怎么写，而不是每章详细大纲。
- `file_summaries`：每个文件的结构化材料摘要。
- `source_affinity_by_chapter`：每章优先使用哪些文件和切片。
- `high_confidence_evidence_units`：后续构建主张和证据绑定时优先使用的证据候选。

边界：

- 不在这里生成整本 outline。
- 不锁标题。
- 不组装最终 `ChapterGenerationTask`。

#### 2.3 `generate_cover`：生成可选封面 sidecar

本节点接收 course、confirmed plan、`file_summaries` 和 `intent_profile`，尝试生成封面素材和封面 Markdown sidecar。

这一步是可选增强：

- 成功时写入封面相关 artifact。
- 失败时记录 warning，正文链路继续。
- 封面不参与章节写作、review、repair 和 KG 同步判断。

#### 2.4 `lock_titles_for_chapters`：锁定最终章节标题

本节点接收 `chapter_assignments`、confirmed plan、课程信息、用户 prompt 和历史摘要。

它在单个节点内部按章并行调用 `lock_title_for_chapter`：

```text
chapter_assignment 1 -> LockedChapterTitle
chapter_assignment 2 -> LockedChapterTitle
chapter_assignment N -> LockedChapterTitle
```

写入 state：

- `locked_titles`：按 `chapter_index` 排序的稳定标题记录。

这一步的意义是把标题从后续正文生成里提前冻结。后面的 `build_backbone`、`assemble_chapter_tasks`、`sync_locked_titles` 都只使用这里锁定的标题。

边界：

- 只锁标题，不改章节目标、范围和 required elements。
- 不生成 teaching outline。
- 不生成 retrieval queries。
- 本地代码只做空标题、编号标题、过长标题等发布形态校验，不用关键词拼标题。

#### 2.5 `confirm_backbone_seed`：把确认方案收成骨架种子

代码文件是 `nodes/confirm_and_seed_backbone.py`，graph 里的节点名是 `confirm_backbone_seed`。

本节点接收：

- confirmed plan payload
- `locked_titles`
- `file_summaries`
- `source_affinity_by_chapter`
- `high_confidence_evidence_units`

它不调用 LLM，只做规则收口，产出：

- `chapter_generation_plan_seed`：整本文档的执行种子。
- `chapter_task_seeds`：每章的最小 seed，包含标题、目标、required elements、source seed 和 retrieval seed。
- `backbone_research_agenda`：构建全局知识骨架时优先看的主题、切片和证据方向。

本节点结束后，state 里已经有“按确认方案写文档”的骨架输入，但还没有正式 `document_backbone`，也还没有最终章节任务。

#### 2.6 `build_document_backbone`：构建整本文档知识骨架

本节点接收 `chapter_task_seeds`、`shared_inputs`、高置信证据候选和 `backbone_research_agenda`。

它产出 `document_backbone`，包括：

- `CanonicalGlossary`：全局术语、别名和定义口径。
- `ConceptDependencyGraph`：概念前置关系。
- `NotationRegistry`：符号和记号规范。
- `CanonicalClaimPool`：整本文档必须讲清的核心主张池。
- `ConfusionMap`：易混点、误区和边界。
- `backbone_conflict_warnings`：资料之间的术语、定义、符号或来源冲突。

这不是正式知识图谱。它只是 DocGen 写作期使用的内部骨架，用来约束后续每章不要乱用术语、倒置前置关系或重复讲同一件事。

边界：

- 不调用 LLM。
- 不写 `knowledge_unit / knowledge_edge`。
- 不直接生成学生可见 Markdown。

#### 2.7 `build_chapter_execution_briefs`：为每章生成最小执行 brief

本节点接收每章 `ChapterGenerationTaskSeed`、`document_backbone` 和 `intent_core`。

它在单节点内部按章并行调用模型，产出 `chapter_execution_briefs`。每个 brief 只回答“这一章具体应该怎么讲”，重点字段是：

- `content_role_targets`：本章覆盖哪些内容角色，例如核心知识、方法示范、原理解释、练习评估。
- `example_coverage_plan`：哪些知识点、方法或任务必须用例题、案例、操作示例或练习覆盖。
- `chapter_end_practice_plan`：章末练习要回收哪些关键任务、边界或迁移点。
- 少量 `retrieval_queries`：最多用于补充本章资料缺口。

边界：

- 不改标题。
- 不生成完整执行大纲。
- 不生成正文。
- 不生成媒体请求。

#### 2.8 `assemble_chapter_tasks`：冻结最终章节执行合同

本节点把前面所有准备产物合并成正式任务：

```text
locked_titles
  + intent_core
  + chapter_task_seeds
  + chapter_execution_briefs
  + document_backbone
  + file_summaries / source affinity
  -> ChapterGenerationPlan
  -> ChapterGenerationTask[]
```

写入 state：

- `chapter_generation_plan`
- `chapter_tasks`
- 排序后的 `chapter_execution_briefs`

`ChapterGenerationTask` 是后续单章生成的执行合同，至少包含：

- `chapter_index`
- `confirmed_title` / `enhanced_title`
- `objective`
- `required_elements`
- `forbidden_scope`
- `retrieval_queries`
- `priority_section_refs`
- `source_slices`
- `preferred_sources`
- `content_role_targets`
- `example_coverage_plan`
- `chapter_end_practice_plan`
- `dependency_refs`
- `claim_targets`
- `confusion_targets`

这一步之后，DocGen 不应该再临时发明章节目标。后面的 writer、review、repair 都应围绕这里冻结的任务工作。

#### 2.9 `generate_chapters`：按章 fan-out 生成草稿

`assemble_chapter_tasks` 之后，graph 通过 `Send` 把每个 `ChapterGenerationTask` 派到一个 `generate_chapters` 分支。每个分支只处理一章。

单章分支拿到：

- 单章 `chapter_task`
- `shared_inputs`
- `docgen_context`
- `document_context`
- `document_backbone`
- retrieval profile / policy

单章内部顺序：

```text
chapter_task
  -> hydrate_source_slices
  -> query_planning
  -> local retrieval + optional external reader
  -> context compression / research_purify
  -> build ClaimLedger
  -> align ClaimEvidenceMap / EvidenceLedger
  -> resolve ConflictReport
  -> writer 写章节 Markdown
  -> heading repair / bounded rewrite（必要时）
  -> ChapterDraft
```

几个关键点：

- `hydrate_source_slices` 会优先按 `source_slices` 精确读取原文行，先用 Planner/prepare 阶段已经选出的材料。
- `query_planning` 只为本章生成 research queries / gap queries。
- writer 使用 `chapter_task`、dense context、主张账本和证据绑定写正文。
- sprint/systematic 的差异主要在 writer 的节奏和模型槽位，不在本地硬编码标题模板。

fan-in 后 reducer 汇总：

- `chapter_drafts`
- `research_traces`
- `claim_ledgers`
- `claim_evidence_maps`
- `evidence_ledgers`
- `conflict_reports`
- `research_sources`

边界：

- 不发布文件。
- 不写数据库。
- 不写 KG。
- 不绕过 `chapter_task` 另起章节范围。

#### 2.10 `enhance_chapters`：增强展示层，并可启动 KG 预抽取 sidecar

所有 `chapter_drafts` fan-in 后进入本节点。本节点内部再用 `run_llm_tasks(...)` 按章并行增强。

每章增强做：

- Mermaid 占位生成或修复。
- 静态讲义图 sidecar 生成：按章节片段先规划跨学科 `FigureSpec` 图元，再由代码渲染为考试讲义式 HTML/SVG。
- 交互 HTML sidecar 生成。
- 公式、Markdown 结构和残留占位清理。
- 章节预览和章节进度更新。

写入 state：

- `enhanced_chapter_drafts`
- `asset_manifests`
- `practice_manifests`
- `enhance_ms`

边界非常重要：

- 不生成新核心结论。
- 不改 claim / evidence 绑定。
- 不根据本地关键词追加标题、例题或练习。
- 不把原始 HTML 直接塞进正文 Markdown。

静态讲义图的边界：

- 本质仍是 HTML sidecar，Markdown 中只插入预览链接，前端用 sandbox iframe 展示。
- 模型只输出 `FigureSpec` 结构，不直接生成 HTML/SVG；最终图形由 renderer 统一画出。
- 静态图只生成 `problem_diagram`：点、线、向量、坐标轴、曲线、圆、椭圆、三角形、多边形、角标、区域和短标签等受控图元。
- 不生成流程卡片、概念总结图、对照表或正文摘要；这些内容留在 Markdown 正文或 Mermaid/interactive sidecar。
- 默认风格接近考试讲义：白底、黑白细线、少量青色重点条、灰底提示框，不做卡片式 UI。
- `source_refs` 必须回指当前章节片段；校验失败时会替换为正文摘录，避免图和文脱节。
- 不按关键词生成学科模板；模型不给出可渲染图元时直接跳过，不用后端假图兜底。
- 每章最多自动插入一张，评分不足时不生成，避免文档被装饰图打散。

如果开启：

```text
knowledge_graph.sync_after_docgen=true
knowledge_graph.prefetch_during_docgen=true
```

本节点会调用 `start_docgen_kg_prefetch(...)`。这是 sidecar，不是 DocGen 主图节点：

- 输入是增强后的章节 Markdown 和 `document_backbone`。
- 只预抽取 section payload 并写进程内缓存。
- 不写 `knowledge_unit / knowledge_edge / source_ref`。
- 不阻塞后面的 review、repair、publish。
- 发布失败或构建取消时由生命周期清理。

#### 2.11 `review_chapters`：按章 fan-out 复核增强稿

`enhance_chapters` 完成后，graph 再次通过 `Send` 按章 fan-out。每个 review 分支只拿一章的精简输入：

- 单章 `enhanced_chapter_draft`
- 单章 `review_chapter_task`
- 单章 `review_claim_ledger`
- 单章 `review_claim_evidence_map`
- 单章 `review_conflict_report`

单章 review 检查：

- 合同覆盖：`required_elements` 是否覆盖，是否越界。
- 主张支撑：claim 是否有 evidence 支撑。
- 结构风格：长度、节奏、模式、Markdown 结构是否合理。
- 学习质量：例题、案例、练习、自测答案是否完整。
- 风险信号：定义模糊、低支撑断言、unresolved conflict。

每个 review 分支返回的是复核 overlay，而不是把整章完整 Markdown 再复制一遍：

- `reviewed_chapter_overlay_items`
- `chapter_review_report_items`
- `review_action_items`

这些字段通过 reducer fan-in，交给整本一致性复核。

#### 2.12 `document_consistency_review`：整本一致性复核

本节点在所有章节 review fan-in 后运行。

它先把 `enhanced_chapter_drafts` 和 `reviewed_chapter_overlay_items` materialize 成 `reviewed_chapter_drafts`，再做整本规则复核：

- 术语和符号是否跨章一致。
- 定义是否冲突。
- 前置关系是否倒挂。
- 某章是否重复讲太多，或吃掉下一章范围。
- 整本风格是否断裂。

写入 state：

- `reviewed_chapter_drafts`
- `document_consistency_report`
- `review_actions`
- `review_decision`

当前实现中，整本一致性复核不调用 LLM、不检索、不改正文。它只是判断是否 `good`、`needs_repair`、`publish_with_warnings` 或 `fail`。

#### 2.13 `repair_or_route`：执行有限局部修补

本节点接收 `review_actions`、`reviewed_chapter_drafts`、`enhanced_chapter_drafts`、`chapter_tasks` 和 `document_backbone`。

当前实现不是 graph 级多轮循环，而是一次节点内的有限修补：

| action | 当前处理 |
| --- | --- |
| `surface_patch` | 可做确定性展示修复，或走 LLM 局部 patch |
| `section_patch` | LLM 生成局部补丁，代码插入目标位置 |
| `evidence_patch` | 局部补证据说明、收窄断言或补不确定性提示；不做新检索 |
| `regenerate_chapter` | 降级为单章局部 section patch |
| `re_dispatch` | 记录 unresolved warning |
| `rebuild_backbone` | 记录 unresolved warning |

修补策略：

- 不同章节可以并行修。
- 同一章的多个 LLM patch 会尽量合并处理。
- 单章最多有限轮局部 patch；仍未覆盖的 action 写入 unresolved warning。
- LLM 只返回局部补丁片段，代码负责插入目标锚点或小结前。

写入 state：

- 修补后的 `reviewed_chapter_drafts`
- 更新后的 `review_actions`
- `unresolved_warnings`
- `repair_trace`
- `repair_ms`

未来如果要做真正 `review <-> repair` 图级闭环，必须先定义 reducer 语义：哪些字段按 `chapter_index` 替换最新版本，哪些 trace 只能追加历史。

#### 2.14 `merge_review`：合并整本文档

本节点接收修补后的章节稿、`chapter_generation_plan`、`document_backbone`、主张/证据/冲突账本、整本复核报告和 review actions。

它只做发布前规则收口：

- 按 `chapter_index` 去重、排序和合并章节。
- 生成 `merged_markdown`。
- 生成 `chapter_metadatas`。
- 生成 `merge_review_report`。
- 检查章节完整性、manifest 必要字段和来源覆盖。

边界：

- 不调用 LLM。
- 不重新检索。
- 不重写章节内容。

#### 2.15 `sync_locked_titles`：把锁定标题同步到最终 Markdown

本节点接收 `chapter_metadatas`、`locked_titles` 和 `merged_markdown`。

它只做标题收口：

- 读取 `lock_titles_for_chapters` 阶段已经锁定的标题。
- 同步每章 metadata 的最终标题。
- 修正每章 Markdown 一级标题。
- 重新构建整本 Markdown。

边界：

- 不调用 LLM。
- 不重新起标题。
- 不改变 confirmed plan 的章节语义。

#### 2.16 `publish_document`：发布 Markdown、manifest 和 KnowledgeDoc

本节点接收最终 `merged_markdown`、`chapter_metadatas`、`docgen_artifacts` 和 `document_context`。

写入文件位置：

```text
knowledge_markdowns/_build/                 # staging
knowledge_markdowns/                        # live current
knowledge_markdowns/versions/vXXXX/         # version archive
```

核心文件：

- `chapter_XX_*.md`
- `merged_knowledge_base.md`
- `docgen_manifest.json`
- `source_references.md`

数据库写入：

- 旧 `KnowledgeDoc(is_current=True)` 标记为 `superseded`。
- 每章新建 `KnowledgeDoc(status="published", is_current=True)`。
- 写章节 metadata、source scope、manifest、word count、version、build session。
- 更新 `Course.document_summary_json`。
- `llm_context_text` 只是从结构化摘要渲染出的 prompt 缓存，不是独立事实源。

写入 state：

- `doc_ids`
- `built_paths`
- 最终 `merged_markdown`
- `docgen_manifest`
- `finalize_ms`

DocGen 到这里结束。它发布的是知识文档，不发布知识图谱。

#### 2.17 发布后交给 `kg_doc_sync`

这一步不在 `graph.py` 主图里，而在 `run_docgen_background(...)` 的生命周期里。

如果：

```text
settings.knowledge_graph.sync_after_docgen=true
```

DocGen 成功发布后会独立派发 `kg_doc_sync`：

- `kg_doc_sync` 读取最终发布的 Markdown / manifest / KnowledgeDoc。
- 如果 prefetch sidecar 缓存命中，会复用 section payload。
- 如果缓存未命中或 section hash 不一致，会按正式链路重新抽取。
- `knowledge_unit / knowledge_edge / knowledge_graph_source_ref` 都由 `kg_doc_sync` 写入。

DocGen 失败、取消或发布未完成时，KG 自动同步不会继续落库。

## 关键数据流

```text
ConfirmedBuildPlan
  -> DocGenContext + chapter_assignments
  -> intent_core + file_summaries
  -> locked_titles
  -> document_backbone
  -> chapter_execution_briefs
  -> chapter_tasks
  -> chapter_drafts
  -> enhanced_chapter_drafts
  -> reviewed_chapter_drafts
  -> merged_markdown + chapter_metadatas
  -> KnowledgeDoc + docgen_manifest
  -> kg_doc_sync（可选自动触发）
```

## 模型调用

策略集中在 `lib/model_policy.py`。

常用槽位：

- `reason`：意图判断、标题锁定、章节 brief、query planning、系统课 writer。
- `primary`：速成课 writer、章节 rewrite、交互 HTML、repair patch。
- `light`：文件摘要、材料清洗、标题结构修正、章节 review、Mermaid。
- `image_generation`：封面图。

所有批量 LLM 调用应通过 `run_llm_tasks(...)`，最终还会受全局 `settings.llm.concurrency_limit` 限制。

## 修改这条链路时检查

- `graph.py` 节点顺序是否和本文短流程一致。
- 新 LLM 调用是否进了 `lib/model_policy.py`。
- 新批量模型任务是否走 `run_llm_tasks(...)`。
- 新发布产物是否进入 `docgen_manifest.json` 或 `Course.document_summary_json`。
- 是否误改了 confirmed plan 的章节语义。
- 是否把 KG 落库逻辑误塞进 DocGen。
- 改 `enhance_chapters` 时，确认没有引入新核心结论或本地关键词造内容。
- 改 `repair_or_route` 时，确认不会无限循环，也不会静默重写整章。

建议提交类型：改本文档用 `docs`，改链路行为用 `refactor` 或 `fix`。
