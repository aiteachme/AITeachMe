# 05. Digest 引擎总控设计

## 1. 定位

Digest 是 AITeachMe 的“织网引擎”，负责把 ingest 已产出的规范化材料，重组为一套可发布、可学习、可被后续引擎消费的知识资产包。它不是单纯的“总结器”，而是统一编排以下三层结果：

- 面向学习者的知识文档
- 面向系统的知识图谱与教学单元
- 面向教学组织的 curriculum views（主题树、先修图、线性大纲、学习计划）

Digest 的目标优先级固定为：

1. 语义结构正确
2. 构建速度足够快，常规材料尽量控制在 5 分钟内可用
3. 构建等待期可感知
4. 对前端暴露尽可能少的接口

---

## 2. 当前统一口径

### 2.1 后端主链路

统一构建仍然走一条主链：

`prepare shared -> docs / kg -> curriculum -> publish`

但当前实现重点不再放在“拆更多 lane”，而是放在以下几个系统问题的治理：

- 语义标题净化，避免 `Question 1`、`Question bank`、`第 1 题` 这类过程性标题进入主题骨架
- typed resolution，避免仅按名称做跨类型、跨层级串线
- chunk 物化增量化与 embedding 复用，避免每次全量重算
- 教学单元、主题树、先修图围绕同一份知识图谱事实源构建

### 2.2 模式决策

Digest 继续支持两种教学模式：

- `sprint`：速成课，强调高频考点、题型、方法、易错点
- `systematic`：系统课，强调完整依赖链、概念覆盖和课程结构

模式由后端根据材料画像自动判断，但前端不需要依赖额外模式接口。模式信息如需展示，只允许作为已有响应中的附属字段出现，不能为此新增专用 API。

---

## 3. 接口原则

Digest 当前遵循“少 API、POST 优先”的约束。

### 3.1 保留接口

- `POST /api/v1/subjects/{subject}/knowledge/build`
- `POST /api/v1/subjects/{subject}/knowledge/docs`
- `POST /api/v1/subjects/{subject}/knowledge/overview`
- `POST /api/v1/subjects/{subject}/knowledge/study-plan`

### 3.2 不再推荐的接口形态

以下形态不再作为 digest 设计目标：

- 独立 `build-status` 接口
- `GET /study-plan`
- `PATCH /study-plan/checklist`
- 为等待态额外新增 SSE 通道

### 3.3 等待态原则

知识文档和图谱页的等待态统一复用：

- `POST /knowledge/build` 触发构建
- `POST /knowledge/docs` 轮询文档与最小 build 状态
- 前端本地生成平滑进度，不要求后端提供精确 ETA、chunk 计数或 sample cards

后端对 `POST /knowledge/docs` 的 `build` 字段只需暴露最小可用集：

- `status`
- `requested_at`
- `stage`
- `error_message`
- `draft_available`

---

## 4. 统一产物

Digest 的统一产物分三层。

### 4.1 底层真相源：Knowledge Graph

- 节点、边、证据是语义事实源
- 节点内容通过 revision 承载
- `taxonomy_hint` 必须进入可持久化元数据，而不是只停留在内存候选节点

### 4.2 中层组织：Teaching Unit

- 教学单元由知识图谱聚类而来
- unit 是最小可讲授粒度
- `Example`、`Definition` 作为 support 节点，不应该反向成为主题主锚点

### 4.3 上层视图：Curriculum Views

- 主题树：浏览和目录导航
- 先修图：依赖与学习路径
- 线性大纲：课程顺序
- 学习计划：学习阶段 + checklist

---

## 5. 前端展示约束

### 5.1 知识文档页

- 右侧继续保留 AI 评论区
- 学习计划在正文顶部内联展示
- 构建等待态和更新 banner 只读 `POST /knowledge/docs`

### 5.2 知识图谱页

- 学习者默认视图改为稳定语义星图
- 随机漂移的 3D 词云不再作为主方案
- `DigestBuildProgress` 与 `StudyPlanPanel` 可在图谱页和侧边图谱面板展示，但都基于已有接口

### 5.3 Study Plan 交互

- 学习计划保留一个单独的 `POST /study-plan`
- 空请求体表示查询
- 带 `item_id + completed` 表示更新后返回全量
- 前端直接用全量响应刷新缓存，不拆局部接口

---

## 6. 当前最重要的设计约束

- 不再为了“看起来更实时”而堆更多专用接口
- 优先保持知识图谱、主题树、学习计划三者语义一致
- 任何性能优化都优先做在 embedding 复用、chunk 增量物化、聚类分桶和减少串行上
- 任何等待体验优化都优先复用现有接口和前端本地状态，而不是扩接口

---

## 7. 与子文档的关系

- [05a_digest_knowledge_document.md](./05a_digest_knowledge_document.md)：文档生成、等待态、学习计划在 docs 页的整合
- [05b_digest_knowledge_graph.md](./05b_digest_knowledge_graph.md)：知识图谱、typed resolution、语义星图与 curriculum 依赖
