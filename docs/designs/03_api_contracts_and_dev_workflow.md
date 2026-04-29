# API 契约与开发流程（当前实现）

本文档记录当前前后端实际对接的 API 形态。历史调试入口和课程结构表相关契约不再作为当前实现的一部分。

## Knowledge API

基础前缀：

`/api/v1/subjects/{subject}/knowledge`

### 构建方案

- `POST /build/plans`：创建 planner 会话。
- `POST /build/plans/latest`：读取当前学科最近的 planner 会话。
- `POST /build/plans/stream`：创建 planner 会话并通过 SSE 返回进度。
- `POST /build/plans/{session_id}/messages`：追加反馈并重新生成方案。
- `POST /build/plans/{session_id}/messages/stream`：追加反馈并通过 SSE 返回进度。
- `POST /build/plans/{session_id}/confirm`：确认方案，将冻结计划写入 Planner 会话元数据。

### 知识构建

- `POST /build`：启动知识文档构建。公开 `build_type` 只允许省略或 `"docs"`。
- `POST /build/graph`：基于当前已发布知识文档手动重建知识图谱。它不接收临时 Markdown，也不从上传原文件直接入图；输入统一来自 `KnowledgeDoc`、DocGen manifest 和章节来源映射，主要用于维护、补偿和排查。
- `POST /build/cancel`：取消当前构建。
- `POST /build/runtime`：读取聚合、DocGen、Graph 三个 lane 的运行态。
- `GET /build/stream`：SSE 推送构建快照、预览增量和构建事件。

`/build` 本身只承载知识文档构建，不再暴露单独的图谱调试构建模式。知识图谱同步由 `sync_after_docgen` 设置控制，并在知识文档发布后自动后台执行；开启 `prefetch_during_docgen` 时，DocGen 期间会先做内存预抽取，知识文档发布后再校验缓存并统一落库。`/build/graph` 只作为正式的“重建当前发布文档图谱”入口，供知识图谱面板、维护补偿和排障使用。

### 知识文档与概览

- `POST /docs`：读取已发布知识文档、草稿和构建状态。
- `POST /overview`：读取知识概览，可包含完整图谱。
- `POST /clear`：清空当前学科的知识文档、图谱和相关派生状态。

### 知识图谱查询

- `POST /graph/knowledge-units`
- `POST /graph/knowledge-units/detail`
- `POST /graph/knowledge-units/relations`
- `POST /graph/knowledge-units/path`
- `POST /graph/subgraph`
- `POST /graph/relations/explain`
- `POST /graph/full`
- `POST /chunks/context`

图谱查询对外统一使用 `KnowledgeUnit` 命名，对应数据库表 `knowledge_unit`。旧文档中的 `knowledge_node` 仅可作为历史术语理解。

## 构建状态契约

`KnowledgeBuildRuntimeResponse` 当前包含：

- `aggregate`：聚合状态。
- `docgen`：知识文档构建状态。
- `graph`：知识图谱构建状态。
- `docgen_preview`：文档生成中的章节、草稿和事件预览。
- `docgen_metrics`：DocGen LLM 调用统计。
- `graph_metrics`：稳定图谱指标。

`graph_metrics` 至少包含：

- `processed_chunks`
- `doc_sync_section_count`
- `doc_sync_unit_changes`
- `doc_sync_edge_changes`
- `elapsed_ms`
- `revision_no`
- `last_synced_doc_version_no`
- `source_ref_count`
- `backbone_unit_count`
- `backbone_edge_count`
- `stitched_edge_count`
- `section_local_stitch_edge_count`
- `mention_stitch_edge_count`
- `graph_isolated_unit_count`
- `graph_isolated_unit_pct`
- `graph_component_count`
- `graph_largest_component_unit_count`
- `graph_avg_degree`
- `stable_anchor_count`
- `deprecated_unit_count`
- `deprecated_edge_count`
- `prefetch_status`
- `prefetch_section_count`
- `prefetch_reused_section_count`
- `prefetch_catchup_section_count`
- `prefetch_stale_section_count`
- `prefetch_failed_section_count`

前端应优先读取 `graph_metrics` 展示图谱进度；`graph.metrics` 仅作为 lane 级诊断兜底。

节点详情接口会返回 `source_refs`，用于展示节点来自哪个知识文档章节、文档版本、源文件和同步批次；旧 `evidence` 字段继续保留兼容。

## 已删除的公开调试契约

以下入口已从公开 API 和 OpenAPI 中移除：

- `POST /debug/kg-file-ingest`
- `POST /debug/kg-doc-sync`
- `POST /debug/clear-graph`

前端不再提供知识调试 tab。排查图谱链路时，应通过 LangSmith、workflow 日志和 `/build/runtime` 判断状态。

## 前端客户端生成

- `frontend/src/api/generated` 由 Orval 生成，不手动修改。
- 后端 schema 或路由变化后，运行 `backend/scripts/export_api_docs.py` 导出 `frontend/openapi.json` 并触发 `npx orval`。
- 手写 API wrapper 只放在 `frontend/src/lib`、`frontend/src/hooks` 或页面组件中。

## 未来能力边界

`curriculum / teaching_unit / taxonomy_anchor / theme_tree_node / unit_dependency` 是未来课程结构能力，不属于当前公开 API。后续若恢复，应先完成数据库迁移、导入导出、OpenAPI 和 Examine/Profile 依赖设计。
