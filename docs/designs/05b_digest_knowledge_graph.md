# 05B. Digest 知识图谱设计

## 1. 文档定位

本篇专门定义 Digest 的知识图谱 lane，回答三个问题：

- 图谱为什么不能只停留在“抽节点和边”
- 图谱怎样成为知识文档、curriculum、interact、examine 的语义底座
- 图谱要向 docs lane 暴露什么 richer contract，才能支撑高质量讲义生成

本篇不承担 unified 编排细节，也不细讲知识文档写作细节。相关内容分别见：

- [05_digest_engine.md](./05_digest_engine.md)
- [05a_digest_knowledge_document.md](./05a_digest_knowledge_document.md)

---

## 2. 当前图谱链路的问题审计

当前 kg lane 的主链大致是：

`prepare -> extract -> cluster -> resolve_nodes -> resolve_edges -> analyze_impact -> finalize_graph`

这个结构已经比早期版本清晰很多，但仍有几个明显短板。

### 2.1 问题一：对 docs lane 暴露的接口太薄

当前 finalize 阶段主要构建的是 `TopicAnchorSnapshot`，里面只有：

- `topic_name`
- `node_type`
- `confidence`
- `chunk_uids`

这对文档规划来说明显不够，因为它缺失：

- topic 的稳定别名
- topic 的代表证据
- topic 的核心公式与方法线索
- topic 与 topic 之间的依赖
- topic 是否适合成为章节主轴

### 2.2 问题二：当前 consistency 更偏 coverage，不偏教学

当前 `unified/consistency.py` 能发现：

- docs 有没有覆盖 graph
- graph 有没有没人用的主题
- docs / graph 命名是否漂移

但它看不到：

- prerequisite 顺序是否合理
- 某章是否只有概念没有例题
- 某个 topic 是否应该上升成主章节
- 某些边是否只是弱相关，而不该牵引 curriculum

### 2.3 问题三：图谱还没有显式区分“显示价值”和“教学价值”

当前所有 resolved node 在下游眼里都差不多，但现实里并不是：

- 有些主题适合做章节主轴
- 有些主题适合做辅助说明
- 有些主题只是术语别名
- 有些主题更像题型线索，而不是概念主干

如果不区分这些角色，docs lane 只能被迫自己再猜一遍。

### 2.4 问题四：impact 分析还没有真正驱动局部重建

当前已有 `impact_set`，但设计上还没有把它完全扩展为：

- 影响哪些 topic cluster
- 影响哪些 chapter blueprint
- 影响哪些 curriculum branch

这会限制未来的 bounded repair 和增量重建能力。

---

## 3. 目标图谱对象模型

未来 kg lane 需要正式引入 richer object model。

### 3.1 `TopicMapSnapshot`

这是 docs lane 的主要消费对象，至少包含：

- canonical topic name
- aliases
- node type
- confidence
- representative evidence
- core formulas
- related methods
- example clues
- chunk coverage
- pedagogical salience

### 3.2 `ConceptDependencySnapshot`

描述 topic 之间的关系，而不是只给一堆离散 node。

建议关系类型：

- `prerequisite`
- `derives_from`
- `applies_to`
- `contrasts_with`
- `supports`
- `example_of`

### 3.3 `CurriculumBlueprintSignal`

描述某个 topic 在课程组织上的价值。

建议信号包括：

- 是否适合做章节主轴
- 是否适合做单元子节点
- 是否更适合题型突破而非概念讲解
- 是否在冲刺模式中应被上提

### 3.4 `GraphImpactSet`

用于增量更新与 bounded repair，描述：

- 哪些 canonical topic 受影响
- 哪些 dependency 受影响
- 哪些 curriculum branch 受影响
- 哪些 docs chapter 应视为失效

---

## 4. 证据、别名与依赖关系模型

### 4.1 证据模型

图谱中的节点不是抽象存在，它必须能回溯到证据。

每个 topic 至少需要区分：

- primary evidence
- supporting evidence
- example evidence
- weak evidence

### 4.2 别名模型

别名不是附属功能，而是 canonicalization 的核心。

未来别名模型必须服务于：

- 跨 source 的术语归并
- 中英文或不同教材表述的统一
- docs lane 的命名稳定性
- interact / retrieve 的召回增强

### 4.3 依赖关系模型

依赖边不能只表示“有关联”，而要尽量表达教学意义。

优先保留的关系是：

- 学习前置
- 推导来源
- 方法应用
- 题型归属

不应让图谱膨胀为无意义的弱语义网络。

### 4.4 边的保留原则

- 能直接支持 docs / curriculum / retrieval 的边优先保留
- 仅有弱语义相关但无法稳定使用的边，宁可舍弃
- 图谱宁可少而稳，也不要大而乱

---

## 5. 知识图谱构建流程

目标态流程如下：

`candidate extraction -> canonicalization -> entity resolve -> evidence attach -> dependency build -> topic map publish -> curriculum signal derive`

当前代码对齐补充：

- docs lane 与 kg lane 在 unified digest 中并行执行；
- 两者共享同一轮 `shared prepare` 输入（材料画像、模式判断、section/chunk 先验）；
- 因此图谱抽取的输入边界与文档构建输入边界是一致的，不存在两套独立原料。

### 5.1 Candidate Extraction

职责：

- 从 primitives / sections 中抽取候选 topic、method、formula、example signals
- 保留来源与上下文，不要只保留字符串

### 5.2 Canonicalization

职责：

- 合并别名
- 对齐不同教材写法
- 过滤噪声术语

### 5.3 Entity Resolve

职责：

- 形成稳定的 canonical node
- 判断该 node 属于概念、方法、主题还是题型

### 5.4 Evidence Attach

职责：

- 给每个 node 绑定代表证据、支撑证据、例题证据

### 5.5 Dependency Build

职责：

- 构建带语义的 dependency，不只做宽泛关联

### 5.6 Topic Map Publish

职责：

- 输出可供 docs lane 消费的 `TopicMapSnapshot`

### 5.7 Curriculum Signal Derive

职责：

- 从 topic map 与 dependency 中推导 curriculum 可用信号

---

## 6. 对知识文档与 Curriculum 的输出契约

未来 kg lane 的价值，不在于“图谱自己长得漂亮”，而在于它能稳定服务下游。

### 6.1 对知识文档的输出契约

docs lane 至少需要拿到：

- 主题主干候选
- 前置依赖关系
- 代表证据集合
- 核心公式 / 方法 / 例题分布
- 哪些 topic 更适合冲刺模式上提

### 6.2 对 Curriculum 的输出契约

curriculum lane 至少需要拿到：

- 哪些 topic 适合做教学单元
- 哪些 topic 适合做章节树根节点
- 哪些 dependency 可以转成 prerequisite
- 哪些 topic 只应保留为叶子或补充说明

### 6.3 对 Retrieval / Interact / Examine 的潜在价值

虽然本轮只改设计文档，但图谱设计必须兼顾未来扩展：

- retrieval 可以基于 canonical topic 与 alias 增强召回
- interact 可以基于 prerequisite 判断解释顺序
- examine 可以基于 topic salience 生成更合理的题目覆盖

---

## 7. 增量更新、影响域与重建边界

未来 digest 必须支持增量更新，而不是每次都从零重建所有知识结构。

与当前数据库版本语义的关系：

- 现阶段版本仍通过 `curriculum.version_no` 与图谱 `build_revision_no` 字段表达；
- 不新增独立“图谱版本控制主表”；
- 增量重建能力应优先落在 workflow 与 impact 计算层，而不是先扩表。

### 7.1 Impact 分析目标

更新某些原始材料后，系统应能判断：

- 哪些 topic 变了
- 哪些 dependency 变了
- 哪些 curriculum branch 可能失效
- 哪些 chapter blueprint 应重审

### 7.2 增量重建边界

优先局部重建：

- 受影响的 topic cluster
- 受影响的 dependency 片段
- 受影响的 curriculum 分支
- 受影响的章节蓝图和章节文档

避免无意义全量重跑：

- 未受影响的 canonical topic
- 未受影响的章节
- 未受影响的文档包资源

### 7.3 与 Repair Pass 的关系

`GraphImpactSet` 必须成为 Repair Pass 的正式输入，而不是仅供日志观察。

---

## 8. 质量指标、失败模式与验收标准

### 8.1 核心质量指标

- canonical 命名稳定度
- alias 吸收率
- evidence 覆盖率
- prerequisite 合理性
- docs 可消费性
- orphan node 比例
- topic cluster 可解释性

### 8.2 常见失败模式

- 同一 topic 被拆成多个 node
- 不同 topic 被误合并
- dependency 太泛，无法支持教学顺序
- 例题和方法没有绑定到正确 topic
- 文档 lane 无法直接消费 graph 输出

### 8.3 文档层验收标准

- 能清楚解释为什么 `TopicAnchorSnapshot` 不足以支撑高质量讲义
- 能清楚定义 `TopicMapSnapshot / ConceptDependencySnapshot / CurriculumBlueprintSignal / GraphImpactSet`
- 能清楚说明图谱对 docs 和 curriculum 的服务关系
- 能清楚定义增量更新时的影响域与重建边界

## 2026-03-31 KG Lane 可观测性补充

knowledge-graph lane 现已遵循共享的 digest 可观测性契约。

- 成功完成与运行时失败两种情况都必须产出 `kg_digest_timing_summary`。
- 必填耗时字段包括 `workflow_elapsed_ms`、`acquire_lock_ms`、`prepare_ms`、`extract_ms`、`cluster_ms`、`resolve_nodes_ms`、`resolve_edges_ms`、`impact_ms`、`finalize_ms`。
- 必填抽取与解析计数包括：fast-path chunk 数、LLM 抽取 chunk 数、no-match 数、未解析端点数、持久化耗时，以及 Top-K 慢 chunk。
- token 维度至少应覆盖：总 token、extract/resolve token 总量、按模型统计的 token、按任务类型统计的 token、调用次数、总延迟，以及轻量模型与重型模型的占比。
- 新增图谱处理模块时，应通过共享 summary helper 上报指标，避免下游 dashboard 还要为不同 lane 适配不同格式。
