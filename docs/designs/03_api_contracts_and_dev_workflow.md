# 03. 接口规范与联调流程

## 1. 文档目标

本文档定义当前阶段的接口设计规范，重点覆盖：

- 路由分组与命名约定。
- 为什么当前仍统一使用 `POST`。
- 长流程接口的设计边界。
- OpenAPI、前端调用、MSW 的同步方式。

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

## 3. 路由规范

### 3.1 顶层路径

当前统一采用：

`/api/v1/subjects/{subject}/{resource}/...`

理由：

- `subject` 是顶层工作空间边界。
- `resource` 表示明确的资源分组。
- 便于前后端按学科隔离调试和排错。

### 3.2 当前资源分组

当前应继续保持这些资源组：

- `files`
- `knowledge`
- `chats`
- `exams`
- `profile`

---

## 4. 方法规范

### 4.1 当前阶段统一用 POST

除健康检查等简单读取外，业务接口仍统一使用 `POST`。

理由：

- 复杂查询和过滤更容易演进。
- 请求体结构更稳定。
- 前后端联调成本更低。
- OpenAPI、生成代码和 mock 更容易保持一致。

### 4.2 不要为了“像 REST”而牺牲协作效率

当前阶段的目标不是方法语义教科书式优雅，而是：

- 真实业务协议稳定。
- 联调路径简单。
- 生成链路可维护。

---

## 5. Knowledge Docs 新协议

Knowledge Docs 已彻底切到无 job 协议。

### 5.1 触发构建

`POST /api/v1/subjects/{subject}/knowledge/build`

请求体：

```json
{
  "file_uids": ["file_a", "file_b"],
  "prompt": "请整理成适合期末复习的知识文档"
}
```

响应体：

```json
{
  "accepted_file_uids": ["file_a", "file_b"],
  "ready_file_count": 2,
  "prompt": "请整理成适合期末复习的知识文档",
  "requested_at": "2026-03-23T16:40:00Z"
}
```

行为约束：

- 若同一 subject 已在构建中，返回 `409 BUILD_IN_PROGRESS`。
- 成功受理后只返回本次请求的基本信息。
- 不返回 `job_id`。
- 不返回 `status`、`progress`、`current_step`。

### 5.2 查询已发布知识文档

`POST /api/v1/subjects/{subject}/knowledge/docs`

请求体：

- 空 body 即可。

响应体：

```json
{
  "exists": true,
  "markdown": "# 知识文档总览\n...",
  "updated_at": "2026-03-23T16:41:10Z",
  "source_file_ids": [1, 2],
  "prompt": "请整理成适合期末复习的知识文档"
}
```

行为约束：

- 这是纯查询接口。
- 不会自动触发构建。
- 只读取已发布的 merged 文档和 manifest。

### 5.3 已废弃并删除的旧接口

以下接口已经删除，不保留兼容层：

- `/api/v1/subjects/{subject}/knowledge/docgen/build`
- `/api/v1/subjects/{subject}/knowledge/docgen/get`

---

## 6. Knowledge Docs 的前后端协作规则

### 6.1 前端本地进度条

知识文档页的进度条完全由前端本地控制：

1. 调用 `knowledge/build`
2. 拿到 `requested_at`
3. 前端本地平滑推进进度到 90%
4. 每 2-3 秒轮询 `knowledge/docs`
5. 当 `exists=true` 且 `updated_at >= requested_at` 时补到 100%

### 6.2 后端不负责 Docs 进度协议

后端不再承担以下职责：

- 返回构建进度
- 返回当前阶段
- 返回失败状态对象
- 暴露 Docs 构建中的 job 状态

后端只负责：

- 接受构建请求
- 进行 subject 级互斥
- 统一构建 docs / graph / curriculum
- 在统一构建成功后发布新的知识文档
- 提供已发布结果查询

### 6.3 有旧文档时的体验约定

如果已有旧版 `merged_knowledge_base.md`：

- 前端继续显示旧文档。
- 页面顶部显示“正在更新”的本地进度条。

如果当前没有任何已发布文档：

- 显示空态。
- 同时显示本地进度条。

---

## 7. 长流程协议边界

### 7.1 仍保留状态查询的链路

以下链路当前仍可使用 job 状态协议：

- Digest Graph
- Curriculum Derive
- Assessment 相关后台任务

### 7.2 已改成无状态查询协议的链路

Knowledge Docs 是明确的特例：

- 构建过程是后台异步执行的。
- 但对外协议不是“任务状态查询”，而是“已发布结果查询”。

这一区分必须在接口设计中长期保留，避免再次把 Docs 拉回 job 化。

---

## 8. OpenAPI / Orval / MSW 同步规则

每次修改接口时，顺序必须保持：

1. 改后端路由与 schema
2. 更新 OpenAPI 导出
3. 更新生成代码
4. 更新手写调用
5. 更新 MSW mock

Knowledge Docs 本次同步要求：

- OpenAPI 里只保留 `/knowledge/build` 和 `/knowledge/docs`
- 前端手写页只调这两个新接口
- MSW mock 只模拟这两个新接口
- 不再保留旧 `knowledge/docgen/*` 路径

---

## 9. 当前结论

当前 API 设计的关键约束非常明确：

- 所有业务接口继续统一用 `POST`
- Knowledge Docs 对外彻底无 `job_id`
- 前端等待协议完全本地化
- 后端只暴露“已发布结果”，不暴露 Docs 运行中状态
