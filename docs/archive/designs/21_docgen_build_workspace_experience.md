# 21. DocGen Build Workspace 的 SSE 协议与落地计划

最后更新：2026-04-21

状态：规划中，面向当前实现收敛

---

## 1. 目标

这份文档只回答三个问题：

1. DocGen 的 SSE 应该怎么接到当前后端实现上。
2. SSE 应该流哪些事件，字段最少要长什么样。
3. 前端如何用 `SSE + polling fallback` 保证“实时”和“可恢复”同时成立。

本文件不再重复讲工作台长什么样，产品形态以 `20_docgen_live_build_experience.md` 为准。

---

## 2. 当前代码事实

当前实现已经具备 3 个关键前提：

### 2.1 Planner 已经有成熟的 SSE 外壳

参考：

- `backend/app/api/knowledge_docs.py::_planner_stream_response`
- `backend/app/workflows/interact/chat/lib/streaming.py`

这意味着：

- `StreamingResponse(text/event-stream)` 的接法已经被验证
- 进度事件和完成事件的基本模式已经存在

### 2.2 DocGen 节点已经在发布结构化进度事件

参考：

- `backend/app/workflows/digest/docgen/nodes/common.py::publish_docgen_progress`

当前它是往 `WorkflowContext.event_bus` 发 `LoggedWorkflowEvent`，说明 DocGen 本来就预留了“结构化过程事件”的出口。

### 2.3 DocGen 已经有持久化 snapshot

参考：

- `backend/app/utils/docgen_store.py`
- `backend/app/workflows/digest/docgen/lib/build_lifecycle.py`
- `backend/app/schemas/knowledge.py`

当前已经可通过 `/knowledge/docs` 拿到：

- `build`
- `build_preview`
- `build_metrics`
- `draft_markdown`
- `markdown`

所以 SSE 不应该重造一套“完整真相”，而应该只做增量实时层。

---

## 3. 总体方案

### 3.1 保持后台任务模型不变

仍然保留：

- `POST /api/v1/courses/{course}/knowledge/build`

这个接口继续只负责：

- 受理请求
- 写入 build lock / build status
- 启动后台 DocGen 任务

不把 DocGen 改成一个请求内长连接同步任务。

### 3.2 保持 polling snapshot 作为恢复真相

仍然保留：

- `POST /api/v1/courses/{course}/knowledge/docs`

这个接口继续提供：

- 当前 build 状态
- 当前 preview 快照
- 当前 draft / published 文档

它是页面恢复和 SSE 断线后的真相来源。

### 3.3 新增 DocGen SSE 订阅接口

建议接口：

```text
GET /api/v1/courses/{course}/knowledge/build/stream?build_session_id=...&last_event_id=...
```

接口职责只有一个：

> 把“本轮 build 的增量事件”推给前端。

不是替代 `/knowledge/docs`，也不是直接传整本文档。

---

## 4. 数据归属

为了避免前后端都乱，必须明确三层数据归属。

| 层级 | 责任 | 当前数据源 |
| --- | --- | --- |
| Snapshot Truth | 页面刷新、断线恢复、最终一致性 | `KnowledgeBuildStatusResponse`、`KnowledgeBuildPreviewResponse`、文档内容 |
| Live Delta | 实时增量变化、动效驱动 | 新增 DocGen SSE event stream |
| Artifact Snapshot | 适合工作台展示的中间产物 | `build_preview` 扩展字段，如 `outline_snapshot`、`chapter_previews`、`merge_preview` |

统一规则：

- polling 初始化状态
- SSE 覆盖最新增量
- 如果 polling 读到更完整的 snapshot，snapshot 优先

---

## 5. 事件 envelope

每条事件都应包含统一包裹字段：

```json
{
  "event_id": "evt_000123",
  "build_session_id": "bld_xxx",
  "course": "math",
  "timestamp": "2026-04-21T12:00:00Z"
}
```

字段要求：

- `event_id`：可排序、可恢复
- `build_session_id`：前端用于校验是否属于当前构建
- `course`：当前课程
- `timestamp`：事件产生时间

如果后续要支持 `last_event_id`，`event_id` 就不能省略。

---

## 6. 第一阶段最小事件集

为了控制复杂度，第一阶段只建议做下面 11 类事件。

### 6.1 `build.accepted`

何时发：

- 请求刚被受理

最小字段：

- `requested_at`
- `digest_mode`
- `plan_summary`
- `chapter_count`
- `accepted_files`
- `search_only_mode`

用途：

- 初始化工作台，不让用户首屏空白

### 6.2 `build.stage_changed`

何时发：

- 用户态大阶段切换

最小字段：

- `stage`
- `status`
- `title`
- `description`
- `progress_pct`

用途：

- 更新 Header
- 更新左侧阶段轨道

### 6.3 `build.outline_snapshot`

何时发：

- `prepare_parallel_inputs` 完成后
- 或后续大纲有稳定更新时

最小字段：

- `plan_summary`
- `source_strategy`
- `chapters[]`
  - `chapter_index`
  - `title`
  - `objective`

用途：

- 让用户尽早看到“这份文档怎么组织”

### 6.4 `build.chapter_status`

何时发：

- 某章进入 `generating / enhancing / reviewing / completed`

最小字段：

- `chapter_index`
- `title`
- `status`
- `word_count`
- `source_count`
- `local_hits`
- `web_hits`
- `query_count`
- `fallback_used`

用途：

- 驱动章节板
- 驱动每章状态徽标

说明：

- 不再拆成 `chapter_started`、`chapter_completed` 多个事件。
- 用一个统一事件覆盖章节状态迁移，前端 reducer 更稳定。

### 6.5 `build.chapter_preview`

何时发：

- 某章第一次有“可展示草稿”
- 某章预览发生显著更新

最小字段：

- `chapter_index`
- `title`
- `status`
- `excerpt`
- `latest_headings`
- `word_count`
- `source_count`

用途：

- 更新中央画布的章节草稿卡

### 6.6 `build.merge_preview`

何时发：

- 合并预览可读时

最小字段：

- `latest_chapter_titles`
- `draft_excerpt`

用途：

- 更新整本预览
- 支撑“快写完了”的用户感知

### 6.7 `build.event`

何时发：

- 所有值得进入 `Live Feed` 的通用进展

最小字段：

- `stage`
- `summary`
- `chapter_index`
- `title`
- `domains`
- `source_titles`
- `source_urls`

用途：

- 驱动右侧实时动态区

说明：

- 这是对当前 `recent_events` 的直接升级
- 不是所有事件都必须映射成专门类型，通用进展走这里

### 6.8 `build.heartbeat`

何时发：

- 10-15 秒内没有新的用户可见事件时

最小字段：

- `stage`
- `summary`
- `active_chapter`
- `next_expected_artifact`

用途：

- 避免用户误以为卡死

### 6.9 `build.published`

何时发：

- 文档正式发布成功

最小字段：

- `status`
- `updated_at`
- `chapter_count`
- `doc_exists`

用途：

- 通知前端切换到正式阅读态

### 6.10 `build.error`

何时发：

- 构建失败

最小字段：

- `status`
- `stage`
- `error_code`
- `detail`

用途：

- 停止实时态
- 展示错误提示

### 6.11 `build.done`

何时发：

- SSE 可正常关闭时

最小字段：

- `status`

用途：

- 让前端安全关闭连接

---

## 7. “始终有内容可看”的协议约束

仅有事件类型还不够，服务端还要遵守发事件时机。

### 7.1 首屏保证

建立 SSE 后，第一批事件顺序应该是：

1. `build.accepted`
2. `build.stage_changed`
3. 如果当前 snapshot 已有内容，立即补一条 `build.outline_snapshot` 或 `build.merge_preview`

要求：

- 连接建立后 1-2 秒内，前端必须能渲染出一个非空工作台

### 7.2 中间保证

在任何长阶段内：

- 每 10-15 秒至少发一条用户可见事件
- 如果没有新 artifact，就发 `build.heartbeat`

### 7.3 搜索优先模式保证

如果是 `search_only_mode`：

- `build.accepted` 必须明确说明“当前没有本地资料，将优先执行联网研究”
- 不能让用户误以为系统漏读了文件

### 7.4 断线保证

如果 SSE 中断：

- 前端继续 polling
- 保留最后一个稳定 artifact
- 重连时可选携带 `last_event_id`

---

## 8. 后端落地建议

### 8.1 Phase 1：先接通非持久化 SSE

目标：

- 尽快让 DocGen 也有实时流

做法：

- 参考 Planner SSE 的 `SSEEventEmitter`
- 在 DocGen build session 上挂一条进程内事件队列
- 把 `publish_docgen_progress(...)` 和关键 `update_knowledge_build_status(...)` / `append_knowledge_build_recent_event(...)` 同步桥接到这条队列

特点：

- 改动小
- 能快速验证工作台体验
- 页面刷新后仍主要依赖 polling 恢复

限制：

- 断线补发能力有限
- 多进程场景不够稳

### 8.2 Phase 2：补持久化 event log

目标：

- 支持 `last_event_id`
- 支持更可靠的刷新恢复

做法：

- 为每个 `build_session_id` 写 append-only 事件日志
- 可落在 runtime store，也可落数据库
- SSE 从 event log 顺序读取

要求：

- 不能只依赖当前 capped 的 `recent_events`
- `recent_events` 是 UI 摘要，不足以充当完整事件流

### 8.3 Phase 3：补齐 artifact snapshot

建议优先新增到 `build_preview` 的字段：

- `outline_snapshot`
- `chapter_previews`
- `merge_preview`

原因：

- SSE 适合通知“变了”
- polling / 首屏恢复仍需要能直接拿到“当前长什么样”

---

## 9. 前端状态归并规则

前端 reducer 必须遵守下面的合并原则。

### 9.1 初始化

页面进入时先读 `/knowledge/docs`：

- 拿 `build`
- 拿 `build_preview`
- 拿 `draft_markdown / markdown`

然后再决定是否打开 SSE。

### 9.2 打开 SSE 的条件

当满足以下条件时打开：

- `build.status in {"accepted", "running", "publishing"}`
- 存在 `build_session_id`

### 9.3 SSE 更新只做增量覆盖

前端状态建议拆成：

- `stageState`
- `chapterState`
- `artifactState`
- `liveFeedState`

归并原则：

- 章节列表永远按 `chapter_index` 排序，不按事件到达顺序
- `chapter_status` 更新章节元数据
- `chapter_preview` 更新章节预览
- `merge_preview` 更新整本预览
- `build.event` 只更新 feed

### 9.4 Snapshot 比增量更完整时，snapshot 优先

例如：

- polling 拿到了更完整的 `outline_snapshot`
- SSE 只来了一条简短 `stage_changed`

那么：

- 用 polling 的 snapshot 填工作台
- 用 SSE 维持“正在变”的感觉

### 9.5 结束条件

收到以下任一事件可关闭流：

- `build.published`
- `build.error`
- `build.done`

然后回到 polling 的最终一致性检查。

---

## 10. 与当前代码最相关的几个实现切口

优先建议从下面几个点下手：

1. 在 `knowledge_docs.py` 新增 DocGen SSE endpoint，直接复用 Planner SSE 的模式。
2. 为 DocGen build session 增加 event sink，把 `publish_docgen_progress(...)` 接到 SSE 输出。
3. 在 `build_preview` 中补 `outline_snapshot / chapter_previews / merge_preview`。
4. 前端把 `BuildResearchSources` 拆成 `BuildLiveFeed` 与 `BuildSourcePanel`。
5. 前端统一章节状态枚举，和后端当前真实写入对齐。

---

## 11. 验收标准

满足以下条件，说明这一轮协议真正可用：

1. 用户进入工作台 2 秒内能看到非空内容。
2. 用户在 10 秒内能看到一份真实中间产物，而不只是进度条。
3. 长阶段内每 10-15 秒至少有一次可见变化或心跳解释。
4. SSE 断开时，页面仍能靠 polling 保持可用。
5. 页面刷新后，能用 snapshot 恢复到接近断开前的状态。
6. 章节板、动态 feed、来源面板三者语义清晰，不再混为一体。

---

## 12. 一句话结论

DocGen 的 SSE 不是为了“看起来很实时”，而是为了把当前已经存在的构建真相，稳定地变成用户看得懂、断了也能接上的实时工作台。
