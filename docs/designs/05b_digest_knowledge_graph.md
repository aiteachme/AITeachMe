# 05B. Digest 知识图谱设计

## 1. 目标

Digest 的知识图谱不是图谱页的附属展示数据，而是整个系统的语义事实源。它要同时服务于：

- 知识文档结构化生成
- curriculum views（主题树、先修图、线性大纲、学习计划）
- 后续的 interact / examine / profile

当前图谱设计的核心目标是：

- 消灭 `Question*` 假主题
- 消灭名称串线
- 让教学单元和主题树建立在正确的图谱骨架上
- 提升构建吞吐，避免随图谱规模退化

---

## 2. 三层结构

### 2.1 底层：Knowledge Graph

图谱真相源由三部分组成：

- 节点
- 边
- 证据

设计约束：

- Node 表承载身份、路由和状态
- 节点内容由 revision 承载
- 每次构建应尽量做增量更新，而不是全量重建

### 2.2 中层：Teaching Unit

教学单元由知识节点聚类得到，是最小可讲授单位。

约束：

- unit 只包含语义紧密相关的一组知识点
- `Topic / Concept / Method` 是主骨架
- `Definition / Example` 作为 support 附着，不反向成为主锚点

### 2.3 上层：Curriculum Views

从教学单元派生：

- 主题树
- 先修图
- 线性大纲
- 学习计划

图谱层负责提供稳定的事实源，不直接决定最终文案写法。

---

## 3. 当前重点修复

### 3.1 语义标题净化

图谱抽取阶段必须共享一套标题净化规则，过滤以下非语义标题：

- `Question bank`
- `Question 1`
- `Question 12`
- `第 1 题`
- `Preamble`
- `Page OCR`
- `(root)`

净化目标：

- 不让题号或过程性标题成为正式主题树叶子
- 不让 docs lane 和 kg lane 使用两套不同净化逻辑

### 3.2 Question fallback 约束

题库/试卷型材料的 fallback 结构固定为：

- `Topic -> Concept/Method -> Example`

其中：

- Topic 必须是清洗后的语义主题，而不是题号
- Example 只能作为叶子支撑节点
- 如果无法确定主题，宁可回落到“典型题与综合应用”这类教学语义名，也不能回落到 `Question 7`

### 3.3 Typed resolution

当前图谱解析不允许再依赖“纯名称盲查”。

节点与边解析至少要带上：

- `node_type`
- `normalized_name`
- 局部 bucket / local scope

约束：

- 同名 `Topic / Concept / Method` 不允许互串
- `Definition / Example` 的去重必须限制在父节点作用域内
- 边端点解析优先使用候选节点类型、父子上下文和本批 cluster 结果

### 3.4 taxonomy_hint 持久化

`taxonomy_hint` 不能只存在于内存候选节点中，必须落进节点元数据或证据路径，否则：

- teaching unit builder 读不到真实 hint
- theme tree builder 无法稳定分桶
- 上层 curriculum 只能退回脆弱的 connected component 策略

---

## 4. 性能策略

### 4.1 增量 chunk 物化

当前图谱构建优先使用稳定 chunk UID / hash 做增量物化：

- 未变化 chunk 复用已有记录
- 只对新增 chunk 做 embedding
- 不再每次 delete-and-rebuild 全量 chunk

### 4.2 embedding 复用

节点解析阶段不再对全量 active/pending 节点重复 embedding。

原则：

- 未变化节点禁止反复重算 embedding
- 只对新增候选或缓存失效项重算
- embedding cache 是吞吐优化，不应该暴露成前端接口能力

### 4.3 分桶聚类

聚类不再直接做同类型 O(n2) 全量比较，而是先分桶，再在桶内比较。

推荐分桶维度：

- `node_type`
- `taxonomy bucket`
- token / lexical bucket

目标：

- 20 / 80 / 200 chunk 三档材料下，扩展趋势接近分桶增长而非平方膨胀

---

## 5. 对前端的展示口径

### 5.1 图谱主视图

本轮学习者默认视图不是随机 3D 词云，而是稳定语义星图。

语义星图要求：

- 按主题或 cluster 稳定布局
- 支持类型过滤
- 支持邻居高亮
- 支持点击聚焦和侧栏联动
- 不做随机漂移

### 5.2 专家视图

底层 force graph 仍可保留为专家视图，但不作为普通学习者默认入口。

### 5.3 等待态

图谱页若要展示构建中状态，也只复用：

- `POST /knowledge/build`
- `POST /knowledge/docs`

不增加独立图谱构建状态接口。

---

## 6. 与 curriculum 的契约

图谱层向 curriculum 输出的核心不是“一个大连通分量”，而是稳定的课程组织信号：

- leaf topic 分桶
- unit 聚类
- prerequisite 信号
- taxonomy_hint

curriculum 层不应该再依赖：

- 脏标题
- 纯名称聚类
- 把 `Example` 当作主锚点
- 把整张 connected component 直接挂到单父节点

---

## 7. 当前不推荐的旧方案

以下方案不再作为设计目标：

- 让词云承担主要浏览交互
- 用 `Question*` 标题直接建主题
- 用 `candidate_name_to_*` 一类纯名称索引作为最终解析主逻辑
- 每次构建对整张现有图谱重新 embedding
- 依赖“专门进度接口”去表达图谱构建过程

---

## 8. 验收口径

### 8.1 语义正确性

- 主题树叶子中不允许出现 `Question bank`、`Question 1`、`第 1 题`
- 除非原始材料确实只有一个主题，否则不能出现“几乎所有单元挂到一个父节点”
- `Example` 只能作为叶子支撑节点

### 8.2 结构稳定性

- 同名跨类型节点不能错连
- 跨章节相似命名不能串父节点
- curriculum 产物应能从图谱稳定复现，而不是依赖 prompt 偶然性

### 8.3 性能

- 常规构建应尽量在 5 分钟内可用
- 大头优化优先放在 embedding 复用、增量物化、分桶聚类、减少串行

### 8.4 前端体验

- 默认给学习者稳定语义星图
- 图谱页和图谱侧面板都能看到学习计划入口
- 不依赖专门 build-status API
- 构建中信息统一复用 `POST /knowledge/docs`（可选 `build_preview/build_metrics`），不新增图谱专用进度接口
