# 05. Digest 织网引擎

最后更新：2026-04-28

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
  -> stream_and_parse_plan_draft
  -> normalize_and_persist_plan
```

权威文档：`backend/app/workflows/digest/planner/README.md`

## 3. confirmed plan

用户确认后，Planner 的 plan 冻结为 `confirmed_plan`。

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
  -> prepare_parallel_inputs
  -> confirm_and_dispatch
  -> build_document_backbone
  -> generate_chapters (Send x N)
  -> enhance_chapters
  -> review_chapter (Send x N)
  -> document_consistency_review
  -> repair_or_route
  -> merge_review
  -> finalize_titles
  -> publish_document
```

权威文档：`backend/app/workflows/digest/docgen/FLOW_DESIGN.md`

唯一文档文件：`backend/app/workflows/digest/docgen/FLOW_DESIGN.md`

## 5. DocGen 产物

DocGen 会写：

```text
knowledge_markdowns/_build/
knowledge_markdowns/
knowledge_markdowns/versions/vXXXX/
```

同时写：

- `KnowledgeDoc` rows
- `docgen_manifest.json`
- chapter metadata
- evidence / claim / review / asset / practice 等结构化字段

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

知识图谱不再直接从上传文件独立入图。DocGen 发布知识文档后可以自动触发
`kg_doc_sync`；知识图谱面板也可以调用
`POST /api/v1/courses/{course}/knowledge/build/graph` 手动重建当前发布文档对应的图谱。
API-facing 的图谱查询、总览、来源解释和手动重建入口都通过
`app.workflows.digest.kg_doc_sync` 暴露稳定用例，不再另建 support 影子模块。

自动同步支持 DocGen sidecar 预抽取：章节增强完成后可在后台生成 section 级候选缓存；发布成功后 `kg_doc_sync` 用最终 Markdown 的 hash 复用命中的缓存，对变更章节补抽，再统一写入正式图谱表。手动图谱重建仍只读取已发布 KnowledgeDoc，不依赖预抽取缓存。

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
4. 发布前整本 patch 仍主要依赖 `merge_review` / `finalize_titles` 间接收口。

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
