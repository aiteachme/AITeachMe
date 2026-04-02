# 05. Digest 引擎总控设计

## 1. 文档定位

本篇只讲 Digest 总控，不展开 docs lane / kg lane 的细节写法。  
目标是把“当前代码已经怎么跑”与“未来要怎么演进”分开写清楚。

细节文档：

- [05a_digest_knowledge_document.md](./05a_digest_knowledge_document.md)
- [05b_digest_knowledge_graph.md](./05b_digest_knowledge_graph.md)

---

## 2. 当前总控真相（已落地）

当前知识构建主入口是：

- API：`POST /api/v1/subjects/{subject}/knowledge/build`
- Service：`trigger_docgen_build()` + `run_unified_build_background()`
- Workflow Runtime：`run_unified_digest_build()`

统一构建主链路：

`prepare_shared -> doc/kg parallel lanes -> consistency check -> repair -> curriculum -> publish`

当前运行时阶段词汇（build status）：

1. `accepted / build_accepted`
2. `running / prepare_shared`
3. `running / doc_lane_staged`
4. `running / graph_ready`
5. `running / curriculum_deriving`
6. `publishing`
7. `completed` 或 `failed` 或 `cancelled`

说明：

- 旧的 `run_docgen_workflow/run_graph_digest_workflow/run_curriculum_derive_workflow` 仍保留，主要用于兼容与分 lane 调试；
- 正式用户链路已收敛到 unified build。

---

## 3. 当前各层职责

## 3.1 Shared Prepare

负责一次性准备全局输入：

- 读取 ready markdown 与资产；
- 生成材料画像和模式判断；
- 为 docs/kg/curriculum 提供共享输入。

## 3.2 Docs Lane

负责知识文档构建与 staging：

- 生成章节文档与 merged 草稿；
- 先写 `_build` 草稿，再等待 unified publish；
- 向 `/knowledge/docs` 提供 `draft_*` 预览信息。

## 3.3 KG Lane

负责知识图谱抽取与归并：

- 抽取候选节点/边；
- 聚类与 resolve；
- 持久化图谱快照；
- 输出给后续 consistency/curriculum 的语义输入。

## 3.4 Consistency + Repair

负责跨 lane 一致性与局部修复：

- 检查 docs 与 graph 覆盖与漂移；
- 在预算内做 repair；
- repair 不达标时本轮不切 live。

## 3.5 Curriculum + Publish

负责课程结构与统一发布：

- 生成课程快照（`curriculum + theme_tree_node + unit_dependency`）；
- 统一完成 docs/graph/curriculum 发布切换；
- 任一核心产物失败则保持旧 live。

---

## 4. 当前发布与锁语义

### 4.1 锁与状态文件

当前通过运行时文件协同：

- `.build.lock`：subject 级构建互斥
- `build_status.json`：当前/最近构建态
- `manifest.json`：已发布文档元数据

这些属于运行时产物，不是业务主表。

### 4.2 `/knowledge/docs` 的三层响应

当前查询接口返回：

1. live 发布态：`exists/markdown/updated_at`
2. staging 草稿：`draft_markdown/draft_updated_at`
3. 构建元信息：`build.{status,requested_at,stage,error_message,draft_available}`

约束：

- `draft != live`；
- 对外真相仍以 live 字段为准。

---

## 5. 版本与数据契约

当前 digest 版本语义必须保持一致：

- `knowledge_document.version_no`
- `knowledge_node.build_revision_no`
- `knowledge_edge.build_revision_no`
- `curriculum.version_no`

同一轮 unified build 应共享同一 `build_session_id`。

数据库语义以 [13_database_schema_inventory.md](./13_database_schema_inventory.md) 为准，不回退到三套版本表。

---

## 6. 当前可观测性（已落地）

digest 运行时已统一输出 timing/token summary：

- `docgen_timing_summary`
- `kg_digest_timing_summary`
- `curriculum_timing_summary`
- `unified_digest_timing_summary`

约束：

- 这些是 runtime observability；
- 当前不作为公共业务 API 合同字段；
- 后续如需对外暴露，应通过独立 observability 资源，不污染核心业务接口。

---

## 7. 与其他引擎的边界

## 7.1 与 Ingest

Digest 只消费“已有可用 markdown”的文件，不负责文件解析本身。

## 7.2 与 Interact / Examine / Profile

Digest 提供三类稳定输入给下游：

- 文档层：知识讲义与来源
- 图谱层：节点、边与证据锚点
- 课程层：teaching unit 与先修结构

下游引擎只消费，不回写 digest 主结构。

---

## 8. 未来演进（在现有架构上增量）

## 8.1 编排层

1. 从“统一流程”升级到显式 `Fast Pass / Deep Pass / Repair Pass` 分层预算。
2. 增强 lane 可恢复能力（按 lane/step 重试，而不是整轮重跑）。
3. 统一取消语义与超时治理，避免悬挂子任务。

## 8.2 质量层

1. 将一致性检查扩展到教学质量检查（章节粒度、依赖顺序、例题/易错点配比）。
2. 强化 bounded repair 预算与退出条件。

## 8.3 观测层

1. 增加跨版本回归对比（同学科、同资料、同模式）。
2. 在保持 API 简单前提下，增加独立观测读模型（可选）。

---

## 9. 非目标（当前阶段）

1. 不新增独立 digest job 业务表。
2. 不把运行时锁/状态文件替换成复杂分布式协调系统。
3. 不为“未来可能历史追溯”提前拆散主表。

---

## 10. 一句话结论

当前 Digest 已经是“统一构建 + 分 lane 执行 + 统一发布 + 运行时可观测”的稳定主链路。  
未来重点是提升恢复能力、教学质量门控和观测深度，而不是扩接口与扩表。
