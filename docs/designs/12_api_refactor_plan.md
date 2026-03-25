# 12. API 重构计划（接口收敛与全量返回）

## 1. 背景与问题

当前知识域 API 在页面层存在“接口分散、前端拼装、状态复杂”的问题：

- 知识图谱页（主题树 / 先修图 / 知识图谱）依赖多接口并行请求。
- 页面切换 Tab 会引发重复请求或复杂缓存管理。
- Profile 页存在前端分页循环拉全量数据的情况。
- Job 状态暴露过细（阶段进度、当前步骤）导致前后端耦合过深。

本次重构目标是：

- API 数量尽可能少。
- 默认返回全量页面数据。
- Job 仅暴露粗粒度终态，不暴露阶段过程。

---

## 2. 重构目标

### 2.1 业务目标

- 知识图谱页三个 Tab 改为一个聚合接口供数。
- 前端切 Tab 不再发新的主数据请求。
- 构建任务不再展示进度条，只展示或处理最终状态。

### 2.2 工程目标

- 从“页面多接口拼装”改为“聚合读接口 + 少量交互细节接口”。
- 降低 query key、失效规则和页面状态复杂度。
- 统一 OpenAPI -> Orval -> 前端调用链路。

### 2.3 规范目标

- `digest/status` 不再返回 `progress`、`current_step` 等阶段字段。
- Job 对外状态统一为：`pending` / `processing` / `completed` / `failed`。
- 前端不再使用构建进度条组件作为信息承载。

---

## 3. 范围

### 3.1 本期范围（P1）

- `knowledge` 读接口收敛。
- 知识总结页三 Tab 数据源统一。
- `digest/status` 出参收敛为终态语义。
- 前端移除进度条，改为静默轮询终态。

### 3.2 下期范围（P2）

- Profile 页“前端分页拼全量”迁移为后端聚合返回。
- 对列表查询接口补充 `full`/`paged` 一致语义。

### 3.3 不在本次范围

- `chats` / `exams` / `profile` 业务改造。
- digest 算法与 workflow 编排策略变更。

---

## 4. 接口收敛设计

## 4.1 新增聚合接口（核心）

- `POST /api/v1/subjects/{subject}/knowledge/overview`

职责：一次返回知识图谱页所需主数据。

建议返回结构：

- `snapshot`
- `theme_tree`
- `prereq_dag`
- `graph`（nodes + edges）
- `units`
- `stats`

约束：

- 默认返回全量。
- 某块缺失返回 `null` 或空数组，不因单块缺失使整个请求失败。

## 4.2 保留的交互型细节接口

- `/knowledge/graph/nodes/detail`
- `/knowledge/graph/evidence/context`
- `/knowledge/chunks/context`

用途：点击节点、查看证据、引用原文时按需懒加载。

## 4.3 逐步废弃的页面直连接口

- `/knowledge/theme-tree/current`
- `/knowledge/prereq-dag/current`
- `/knowledge/graph/full`
- 页面层不再直接依赖 `/knowledge/units/query`

策略：先保留兼容，标注 deprecated，确认无调用后下线。

---

## 5. Job 状态规范（本次重点）

## 5.1 状态模型

- 仅保留粗粒度状态：`pending` / `processing` / `completed` / `failed`
- 不再对外提供阶段细分信息。

## 5.2 `digest/status` 出参规范

保留：

- `status`
- `error_message`
- 必要结果统计（如新增/更新计数）
- 关联快照标识（如 `current_curriculum_snapshot_id`）

移除：

- `progress`
- `current_step`
- 任何阶段时间轴语义字段

## 5.3 前端呈现规范

- 不展示进度条。
- 可选展示：按钮禁用态（构建中）、失败提示（终态失败）。
- 成功后刷新聚合数据缓存。

---

## 6. 前后端改造方案

## 6.1 后端改造

- `schemas/knowledge.py`
  - 新增 `KnowledgeOverviewRequest/Response`
  - 收敛 `DigestStatusResponse` 子结构，移除阶段字段
- `services/knowledge`
  - 新增 `get_knowledge_overview()` 聚合服务
  - `get_digest_status()` 返回终态语义
- `api/knowledge.py`
  - 新增 `/knowledge/overview`
  - 保留旧接口（兼容期）
- OpenAPI
  - 导出并更新前端生成产物

## 6.2 前端改造

- Summary 页
  - 主数据改为单 query：`["knowledge-overview", subject]`
- 三个 Tab
  - 改为从同一数据源读取，不再各自拉主数据
- 构建面板
  - 去掉进度条展示
  - 保留静默轮询终态与失败提示
- 缓存失效
  - 构建成功后优先失效 `knowledge-overview`

---

## 7. 迁移步骤

### 阶段 A：后端增量发布

- 上线 `overview`。
- 收敛 `digest/status` 出参。
- 保持旧接口可用。

### 阶段 B：前端切流

- Summary 全面切到 `overview`。
- 去进度条，改为终态逻辑。

### 阶段 C：兼容观察

- 观察 1~2 个迭代，统计旧接口调用量。
- 验证是否仍有旧前端版本依赖。

### 阶段 D：下线清理

- 标记并下线废弃接口。
- 清理前端冗余 query key 与无效逻辑。

---

## 8. 验收标准

- 知识总结页主数据请求数降到 1。
- 三 Tab 切换不触发新的主数据请求。
- 构建流程无进度条展示。
- `digest/status` 不再包含 `progress/current_step`。
- 构建完成后页面数据可自动刷新。
- 失败场景可见明确错误反馈。

---

## 9. 风险与应对

- 聚合响应体变大：
  - 通过 `include` 参数、压缩、缓存策略控制。
- 旧客户端兼容问题：
  - 设置兼容期并监控调用，再做下线。
- OpenAPI 生成物漂移：
  - 将导出与生成纳入 PR 检查清单。

---

## 10. 执行清单

- [x] 定义接口收敛目标与原则
- [x] 明确 Job 终态规范（无阶段字段）
- [x] 输出重构分阶段方案
- [ ] 后端新增 `knowledge/overview`
- [ ] 后端收敛 `digest/status` schema 与实现
- [ ] 前端 Summary 三 Tab 统一数据源
- [ ] 前端彻底移除进度条依赖
- [ ] OpenAPI/Orval 同步并回归验证
- [ ] 旧接口 deprecated 与下线计划执行
