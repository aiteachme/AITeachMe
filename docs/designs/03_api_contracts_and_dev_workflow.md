# 03. 接口规范与联调流程

## 1. 文档目标

本文档只定义当前代码已经落地的 API 契约与联调规则，重点回答：

- 现在到底有哪些路由、哪些 HTTP 方法；
- 哪些链路是同步请求，哪些是后台任务；
- 前后端如何保持 OpenAPI / 生成代码 / Mock 同步。

---

## 2. 真相源

接口真相源只有两处：

- `backend/app/api/*`
- `backend/app/schemas/*`

以下内容都是派生产物，必须以后端真相源为准：

- `frontend/openapi.json`
- `frontend/src/api/generated/*`
- `frontend/src/mocks/*`

---

## 3. 当前路由总览（按资源组）

### 3.1 全局与系统

- `GET /api/health`
- `POST /api/v1/system/init`
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `POST /api/v1/auth/user`

### 3.2 学科与文件

- `POST /api/v1/subjects/add`
- `POST /api/v1/subjects/list`
- `POST /api/v1/subjects/delete/preview`
- `POST /api/v1/subjects/delete`
- `POST /api/v1/subjects/{subject}/files/upload`
- `GET /api/v1/subjects/{subject}/files`
- `POST /api/v1/subjects/{subject}/files/delete`

### 3.3 知识与聊天

- `POST /api/v1/subjects/{subject}/knowledge/build`
- `POST /api/v1/subjects/{subject}/knowledge/docs`
- `POST /api/v1/subjects/{subject}/knowledge/overview`
- `POST /api/v1/subjects/{subject}/knowledge/graph/nodes/detail`
- `POST /api/v1/subjects/{subject}/knowledge/chunks/context`
- `POST /api/v1/subjects/{subject}/knowledge/units/detail`
- `POST /api/v1/subjects/{subject}/knowledge/taxonomy/anchors`
- `POST /api/v1/subjects/{subject}/knowledge/clear`
- `POST /api/v1/subjects/{subject}/chats/send`（SSE）
- `POST /api/v1/subjects/{subject}/chats/list`
- `POST /api/v1/subjects/{subject}/chats/clear`
- `POST /api/v1/subjects/{subject}/chats/sessions/list`
- `POST /api/v1/subjects/{subject}/chats/threads/list`
- `POST /api/v1/subjects/{subject}/chats/sessions/create`
- `POST /api/v1/subjects/{subject}/chats/sessions/delete`

### 3.4 考试与画像

- `POST /api/v1/subjects/{subject}/exams/generate`
- `POST /api/v1/subjects/{subject}/exams/history`
- `POST /api/v1/subjects/{subject}/exams/question-bank`
- `POST /api/v1/subjects/{subject}/exams/{exam_paper_id}`
- `POST /api/v1/subjects/{subject}/exams/{exam_paper_id}/delete`
- `POST /api/v1/subjects/{subject}/exams/{exam_paper_id}/submit`
- `POST /api/v1/subjects/{subject}/exams/{exam_paper_id}/grade`
- `GET /api/v1/subjects/{subject}/profile/mastery`
- `GET /api/v1/subjects/{subject}/profile/mastery/unit/{teaching_unit_id}`
- `GET /api/v1/subjects/{subject}/profile/mastery/node/{knowledge_node_id}`
- `GET /api/v1/subjects/{subject}/profile/review/tasks`
- `POST /api/v1/subjects/{subject}/profile/review/tasks/{task_id}/complete`

---

## 4. 方法规范（当前口径）

### 4.1 当前不是“全 POST”

当前实现是“以 POST 为主，GET 仅用于稳定读取”：

- POST：复杂查询、触发动作、SSE 入口、带 body 的聚合查询；
- GET：健康检查、文件列表、画像读取等纯读取接口。

这个混合策略是当前真实代码，不应再写成“全业务统一 POST”。

### 4.2 简单 API 优先

当前阶段的接口设计原则：

1. 在现有资源组内扩展字段，优先于新增 route。
2. 先保证学习闭环稳定，暂不追求形式化 REST 纯度。
3. 同一能力尽量通过现有读模型返回（例如 profile 摘要并入 `/profile/mastery`）。

---

## 5. Knowledge Docs 协议（当前实现）

### 5.1 触发构建

接口：`POST /api/v1/subjects/{subject}/knowledge/build`

关键点：

- 返回 `accepted_file_uids / ready_file_count / prompt / requested_at`；
- 不返回持久化 `job_id`；
- 同一 subject 构建互斥，冲突时返回 `409 BUILD_IN_PROGRESS`；
- 受理后由 `BackgroundTaskRegistry` 在进程内启动统一构建任务。

### 5.2 查询结果

接口：`POST /api/v1/subjects/{subject}/knowledge/docs`

响应包含三层信息：

- 已发布文档：`exists / markdown / updated_at / source_file_uids / prompt`
- 草稿预览：`draft_markdown / draft_updated_at`
- 运行时构建态：`build.status / build.requested_at / build.stage / build.error_message / build.draft_available`

说明：

- `draft_*` 只用于可视化预览，不能替代发布真相；
- 真正的“官方版本切换”仍以 live `exists + markdown` 为准；
- `build` 是运行时状态，不是业务主表。

### 5.3 构建阶段词汇（当前）

当前阶段语义由 `build_status.json` 驱动，主词汇为：

1. `accepted / build_accepted`
2. `running / prepare_shared`
3. `running / doc_lane_staged`
4. `running / graph_ready`
5. `running / curriculum_deriving`
6. `publishing`
7. `completed` 或 `failed` 或 `cancelled`

---

## 6. 长流程边界

### 6.1 当前后台任务化的链路

- 文件解析（upload 后 parse）
- 统一 digest 构建（knowledge build）

两者都通过 `app.state.background_task_registry.spawn(...)` 托管，并在应用关闭时统一取消与清理。

### 6.2 当前仍是同步请求的链路

- exam 生成
- exam 判卷
- profile 聚合读取

这些链路目前没有新增独立 job API，也没有引入持久化 job 表。

---

## 7. Examine / Profile 契约要点

### 7.1 Examine

- `exams/generate` 和 `exams/{id}/grade` 目前是同步触发；
- `exams/generate.exam_mode` 目标态收敛为两类：`web_practice`（测验）和 `paper_exam`（考试卷）；
- `exams/generate.difficulty` 是现有 generate 接口上的可选字段，支持 `easy / medium / hard / mixed`；不传则由 profile 自动决定；
- 历史模式值由后端兼容映射到两类目标态，不新增额外 generate route；
- `paper_exam` 会在后端落盘导出到 `backend/data/<subject>/exam/`（同步生成 `md/tex`，`pdf` 后台异步补编译）；
- 生成与判卷有 runtime timing summary 日志，但不暴露为公共 API 字段；
- `exam_paper.duration_seconds` 表示用户答题时长，不表示生成/判卷耗时。

### 7.2 Profile

- `/profile/mastery` 已返回：
  - 细粒度 `unit_states / node_states`
  - `subject_profile`
  - `user_profile`
- 当前不新增 `/profile/summary` 等额外接口，继续保持 API 面收敛。

---

## 8. OpenAPI / 生成代码 / Mock 同步流程

每次改接口都按以下顺序：

1. 修改 `backend/app/api/*` 与 `backend/app/schemas/*`
2. 导出 OpenAPI（仓库支持启动时自动导出）
3. 更新前端生成代码与手写调用
4. 更新 MSW mock
5. 前后端联调回归

如果只改内部实现、未改 API 契约，不需要触发生成链路。

---

## 9. 未来演进（不新增复杂接口前提）

在“接口保持简单”原则下，后续优先做：

1. 在现有响应里补可观测字段（必要时走专门 observability 资源，不污染业务响应）。
2. 将超长链路逐步后台化，但优先复用现有资源组，不拆散 API 面。
3. 保持 subject 作为顶层边界，避免跨学科混杂接口。

---

## 10. 一句话结论

当前 API 体系是“POST 主导 + 少量 GET 读取 + SSE 聊天主通道 + 后台任务注册器托管长流程”。  
后续改动继续遵循“能复用现有接口就不新增接口”的收敛原则。
## 0. 2026-04 Examine 可观察行为补充

- 本批没有新增、删除或改名任何公开 route，也没有改 `backend/app/schemas/*` 的请求响应结构。
- `ExamPaperDetailResponse.selection_context` 继续保持 `dict[str, Any]` 兼容，但 Examine 现在会额外写入 `scope_locked`、`template_context_signature`、`template_reuse_policy` 等调试字段。
- 当请求显式携带 `style_prompt / focus_prompt / sample_file_uids / teaching_unit_ids / theme_tree_node_id` 任一项时，后端会生成 `context_signature`，模板复用必须精确匹配该上下文。
- 当显式 `teaching_unit_ids` 或 `theme_tree_node_id` 锁定范围后，组卷不再跨范围 fallback；若范围内题目不足，会直接返回失败，而不是静默放宽到全学科。
