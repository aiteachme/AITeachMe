# 05. Digest 织网引擎

最后更新：2026-05-02

Digest 负责把 Ingest 产出的材料组织成可教学、可追踪、可复用的知识资产。

当前主线：

```text
Planner 生成 confirmed plan
  -> DocGen 按 confirmed plan 生成知识文档
  -> KG lanes 维护知识图谱
```

## 1. 当前目录

```text
backend/app/workflows/digest/
  __init__.py
  README.md
  planner/
  docgen/
  kg_doc_sync/
  common/
```

说明：

- `planner/`：确认式学习方案生成。
- `docgen/`：知识文档生成。
- `kg_doc_sync/`：知识文档和知识图谱同步的正式链路。
- `common/`：跨 lane 共享能力。

## 2. Planner 当前定位

Planner 只做确认前规划：

- 读取资料边界。
- 理解用户目标。
- 生成可确认章节方案。
- 保存 planner session。

Planner 不做：

- 本地 RAG 检索。
- 外部 Web research。
- 固定 DocGen 必须使用的证据来源。

当前流程：

```text
load_planner_materials
  -> stream_brief_and_extract_intent
  -> stream_and_parse_plan_draft + generate_course_name
  -> normalize_and_persist_plan
```

权威文档：`backend/app/workflows/digest/planner/README.md`

## 3. confirmed plan

用户确认后，Planner 的 plan 冻结为 `confirmed_plan`。
同一课程后续调整或重建时，新的确认方案会递增 `version_no`，并在
`chat_session.meta_json.confirmed_plan_history` 中保留轻量历史；DocGen
仍通过本次请求传入的 `confirmed_plan_id` 读取对应版本。

DocGen 消费的关键字段：

- `course`
- `user_prompt`
- `digest_mode`
- `chapter_plan`
- `build_constraints`
- `plan_summary`
- `selected_file_ids`
- `planner_session_id`
- `confirmed_plan_id`
- `mode_reason`
- `planner_context`
- `docgen_history_brief`

原则：

- Planner 决定学什么、按什么章节学。
- DocGen 决定每章怎么写、查哪些资料、怎么增强。
- DocGen 不默认新增、删除、重排用户确认的章节语义。

## 4. DocGen 当前定位

DocGen 消费 confirmed plan，生成可发布的知识文档和 manifest。

当前流程：

```text
load_context
  -> prepare_global_seed
  -> generate_cover
  -> lock_titles_for_chapters
  -> confirm_and_seed_backbone
  -> build_document_backbone
     -> first chapters_enhanced / dispatch_table / preliminary_kg
  -> build_chapter_execution_briefs
     -> early kg_prefetch sidecar from briefs
  -> assemble_chapter_tasks
     -> refined chapters_enhanced / dispatch_table / preliminary_kg
  -> generate_chapters (Send x N)
  -> enhance_chapters
  -> review_chapter (Send x N)
  -> document_consistency_review
  -> repair_or_route
  -> merge_review
  -> sync_locked_titles
  -> prepare_knowledge_graph
  -> publish_document
  -> sync_knowledge_graph
```

`generate_cover` 写入 `assets/docgen/cover.<build-fingerprint>.<ext>` 构建隔离不可变资产；
只有数据库当前发布记录所指向的 versioned manifest 中的 `cover_artifact` 才决定当前封面。

KG 候选不是等 `publish_document` 之后才开始生成。`build_document_backbone`
会先基于章节 seed、资料分配和 guideline 产出第一版规则型 `preliminary_kg`，
`build_chapter_execution_briefs` fan-in 后会把 brief、证据和分配表压成紧凑 Markdown，
立即启动 section 级 LLM 预抽取 sidecar；`assemble_chapter_tasks` 再用更完整的章节任务重算增强版。
`enhance_chapters` 完成后会用完整章节刷新 sidecar，并保留早期候选记录；`document_consistency_review`
会在 reviewed chapters fan-in 后刷新 sidecar，让整本复核和 KG 深抽取并行；
`repair_or_route` 无论是否实际改写章节，都会用最新 review/repair 上下文再次刷新该 sidecar。
章节 `review_chapters` fan-out 和修补后的 `repair_or_route` 都会同步产出 `kg_refinement_items`。
`prepare_knowledge_graph`
会在整本合并和锁定标题同步后、`publish_document` 前等待候选尽量完成，如果缓存缺失或最终标题改变导致章节 hash 变化，则用最终章节兜底启动或刷新一次；
并产出带 `quality_audit`、`quality_status`、`chapter_coverage_ratio` 和
`fast_visible_ready` 的 `docgen_kg_draft`。质量门会检查章节覆盖、边端点唯一性、关系方向、可考核/画像节点、
诊断型节点和结构关系；它只决定草稿能否供发布后的 fast-finalize 复用。
发布前不会写入可查询的 KnowledgeUnit、KnowledgeEdge 或 source_ref；
`sync_knowledge_graph` 位于发布之后，
负责在同一条 DocGen trace 下运行 `kg_doc_sync`，校验最终文档 hash、复用命中的预抽取结果、
补抽缺失或变更 section，并统一把节点、边和 source_ref 固化到正式图谱表。关闭
`knowledge_graph.sync_after_docgen` 时只记录跳过状态，仍可在知识图谱面板手动重建。

权威文档：`backend/app/workflows/digest/docgen/README.md`

主链路文档：

- Planner：`backend/app/workflows/digest/planner/README.md`
- DocGen：`backend/app/workflows/digest/docgen/README.md`
- KG Doc Sync：`backend/app/workflows/digest/kg_doc_sync/README.md`

## 5. DocGen 产物

DocGen 会写：

```text
knowledge_markdowns/_build/
knowledge_markdowns/
knowledge_markdowns/versions/vXXXX/<publish-token-hash>/
```

同时写：

- `KnowledgeDoc` rows
- `docgen_manifest.json`
- chapter metadata
- evidence / claim / review / asset / practice 等结构化字段

发布时，当前 `KnowledgeDoc` 数据库行是权威发布指针；同一版本的不可变
Markdown 与 DocGen artifact 按 publish token 隔离归档，根目录下的当前
别名和 manifest 是提交后的派生投影。读取端会在投影缺失或版本落后时从
当前数据库行恢复版本、来源与归档 manifest，避免数据库已发布但页面或
图谱仍误判为未就绪。发布事务、发布后投影以及发布后的 KG 固化都受
build owner fence 约束。

## 6. Search 与资料读取

DocGen 可使用：

- `local_rag`
- 多外部 retriever
- reader 深读 URL
- source curation
- context compression

Search 层只负责找来源和读来源，不直接生成最终答案。

## 7. KG lane

当前图谱构建主线只有 `kg_doc_sync/`；API-facing 的查询、总览、来源解释和手动重建用例也通过 `kg_doc_sync/` 的稳定入口暴露。

- `kg_doc_sync/`

知识图谱不再直接从上传文件独立入图。DocGen 写作期间可以先预抽取图谱候选，
发布知识文档后再通过 `sync_knowledge_graph` 节点自动运行 `kg_doc_sync` 做最终固化；
知识图谱面板也可以调用
`POST /api/v1/courses/{course}/knowledge/build/graph` 手动重建当前发布文档对应的图谱。
API-facing 的图谱查询、总览、来源解释和手动重建入口都通过
`app.workflows.digest.kg_doc_sync` 暴露稳定用例，不再另建 support 影子模块。

自动同步支持 DocGen sidecar 预抽取：章节 brief fan-in 后先生成早期 section 级候选缓存，章节增强完成后用完整正文刷新，review fan-in 后用 reviewed 正文刷新，repair 后用最新 review/repair 上下文再次刷新，review/repair 同步写出 `kg_refinement_items`；`prepare_knowledge_graph` 会在 merge/title 后、publish 前显式等待缓存尽量就绪并写出带覆盖率和质量审计指标的 `docgen_kg_draft`。如果最终标题改变导致章节 hash 变化，会用最终章节 metadata 刷新一次预抽取。该阶段无论质量门结果如何都不写 query-visible 图谱实体；发布成功后 `kg_doc_sync` 优先用 quality-ready 且覆盖最终章节的 `docgen_kg_draft` 直接构造最终 payload，再补上已发布章节来源、正式 source_ref 和废弃收口并一次性固化；不满足质量/覆盖条件时再用最终 Markdown 的 hash 复用命中的缓存，对变更章节补抽。手动图谱重建仍只读取已发布 KnowledgeDoc，不依赖预抽取缓存。

`kg_doc_sync` 在抽取和写库之间会执行低成本关系缝合：不额外调用 LLM，只基于同小节节点和正文显式引用补少量保守边，并输出孤立率、连通分量和平均度等健康指标。

旧的 `kg_file_ingest` 文件级图谱入口已退出产品主线。后续新增图谱构建逻辑优先进入 `kg_doc_sync/` 或明确的 common 包；API-facing 查询、总览、来源解释和手动重建入口也收口在 `kg_doc_sync`。

## 8. common 使用规则

`digest/common/` 只放真实跨 lane 复用能力，例如：

- contracts / models / prepare
- material profile
- metrics
- runtime config
- pedagogy
- events / exports
- cleanup

单条 lane 私有逻辑放回对应 lane 的 `lib/`。

## 9. 当前风险

1. `repair_or_route` 还不是完整双轮闭环。
2. `evidence_patch` / `regenerate_chapter` 仍待接成真实动作。
3. 文生图已有后端占位处理，但前端展示和重试策略仍可增强。
4. 发布前整本 patch 仍主要依赖 `merge_review` / `sync_locked_titles` 间接收口。

## 10. 一句话

Digest 当前不是一个全能 Agent，而是一条合同驱动链路：

```text
confirmed plan
  -> 章节执行合同
  -> 证据和知识骨架
  -> 单章生成
  -> 内容复核
  -> 发布 manifest
```
