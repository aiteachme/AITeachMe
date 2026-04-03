# 05A. Digest 知识文档设计

## 1. 目标

知识文档页不是“把材料拼成一篇长 Markdown”，而是要产出一份能引导学习的课程化文档包。当前设计目标有四个：

- 文档结构要与知识图谱和 curriculum views 对齐
- 等待态可用，但不新增专门进度接口
- 学习计划要直接进入知识文档页主场景
- 对前端只暴露最少接口

---

## 2. 文档产物

文档 lane 最终对外呈现的是：

- 已发布正式版文档
- 构建中的 draft 文档预览
- 最小 build 生命周期信息

这些内容统一通过一个接口暴露：

- `POST /api/v1/subjects/{subject}/knowledge/docs`

响应中的关键字段包括：

- `exists`
- `markdown`
- `updated_at`
- `draft_markdown`
- `draft_updated_at`
- `build`

其中 `build` 只保留最小状态信息：

- `status`
- `requested_at`
- `stage`
- `error_message`
- `draft_available`

文档页不依赖额外 `build-status` 接口，也不依赖额外 SSE。

---

## 3. 等待态设计

### 3.1 触发与轮询

- 前端先调用 `POST /knowledge/build`
- 再轮询 `POST /knowledge/docs`
- 只要 `build.status` 是 `accepted / running / publishing`，前端继续轮询

### 3.2 进度来源

进度条由前端本地生成，不要求后端返回真实进度百分比、ETA、chunk 数量。

前端允许基于以下信号推断阶段：

- `build.stage`
- `build.status`
- 是否已有 `draft_markdown`
- 是否已有正式 `markdown`

设计原则：

- 用户需要“有反馈”，不需要“伪精确”
- 如果后端还没发布正式文档，前端可以继续显示本地平滑进度
- 一旦正式版文档已发布，前端立即切换结果态

### 3.3 Draft 策略

- `draft_markdown` 只作为构建期预览
- 正式对外文档始终以 `exists + markdown` 为准
- draft 和 live 可以同时存在，但 live 具有更高权威性

---

## 4. 文档页布局

### 4.1 当前固定布局

知识文档页当前采用以下规则：

- 左侧/正文：知识文档正文
- 右侧：AI 评论与划词问答区
- 正文顶部：学习计划面板

这里已经明确不采用：

- 右侧标签切换学习计划 / AI 评论
- 专门为学习计划新增独立浮层

### 4.2 学习计划整合

知识文档页顶部直接展示完整 `StudyPlanPanel`，用于提供：

- 学习阶段划分
- checklist 勾选
- 对应文档锚点
- 对应主题与教学单元

这意味着 docs 页是学习计划的主场景，图谱页只承担简版入口或概览。

---

## 5. 学习计划接口

学习计划只保留一个接口：

- `POST /api/v1/subjects/{subject}/knowledge/study-plan`

请求体统一为：

```json
{
  "item_id": "optional",
  "completed": true
}
```

语义规则：

- `item_id` 和 `completed` 都为空：返回完整学习计划
- 两者都有值：先更新 checklist，再返回完整学习计划

不再保留：

- `GET /study-plan`
- `PATCH /study-plan/checklist`

---

## 6. 文档结构与课程约束

知识文档不能只靠 prompt 自由发挥，必须受以下信号约束：

- 知识图谱中的主题、概念、方法骨架
- curriculum 派生的主题树与先修关系
- digest mode（`sprint` / `systematic`）

文档结构原则：

- `sprint` 模式更强调题型、方法、易错点和快速路径
- `systematic` 模式更强调依赖链、概念展开和完整课程层级
- 无论哪种模式，`Example` 只能是支撑内容，不能替代主题骨架

---

## 7. 当前前端规范

### 7.1 文档页必须做到

- 没有独立 build-status API 时仍能稳定工作
- 支持构建中、失败、已发布、草稿可预览四种状态
- 学习计划与文档正文共存
- 保持现有划词问答体验不回归

### 7.2 文档页不再追求

- 后端精确 ETA
- 后端真实 chunk 进度
- 额外 digest SSE
- 通过额外接口获取 sample cards

这些都可以由前端本地等待态和文案替代。

---

## 8. 与图谱文档的边界

知识文档关心的是“怎么讲清楚”，但它不能脱离图谱事实源。

因此 docs lane 的边界是：

- 不负责最终知识节点解析真相
- 不负责边与证据的最终一致性裁决
- 负责在课程结构约束下把事实讲成可学内容

更底层的节点解析、typed resolution、主题净化和聚类策略，见 [05b_digest_knowledge_graph.md](./05b_digest_knowledge_graph.md)。
