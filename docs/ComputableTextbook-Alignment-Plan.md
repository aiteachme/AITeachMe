# ComputableTextbook Alignment Plan (Todo List)

> 目标：让当前系统逐步对齐 `docs/ComputableTextbook.md` 的设计形态。  
> 执行原则：先“命名对齐”，再“语义对齐”，最后“能力闭环”。

## 0. 里程碑顺序（必须按序）

1. **P0 命名统一：KnowledgeNode -> KnowledgeUnit（最高优先级）**
2. **P1 KnowledgeUnit 类型体系与 KG 关系类型体系对齐**
3. **P2 Markdown 锚点 + KnowledgeUnit 双向定位**
4. **P3 KnowledgeUnit/KG 查询与子图能力 API 化**
5. **P4 学习路径、出题、评估、掌握度闭环**
6. **P5 KG + RAG 主流程改造**
7. **P6 增量同步、迁移、测试、发布**

---

## P0 命名统一：KnowledgeNode -> KnowledgeUnit（先做）

- [x] 冻结命名规范：统一使用 `KnowledgeUnit`（实体名、接口名、前后端字段名、日志名）。
- [x] 后端领域模型重命名：核心实体由 `KnowledgeNode` 升级为 `KnowledgeUnit`。
- [x] API schema 重命名：详情请求/响应改用 `KnowledgeUnit` 命名，并保留旧字段兼容。
- [x] 知识图 API 增加 `knowledge-units` 路由，并保留旧路由兼容。
- [x] 数据模型表名对齐：`KnowledgeUnit.__tablename__` 改为 `knowledge_unit`。
- [x] 关联外键对齐：`knowledge_node.id` 外键引用改为 `knowledge_unit.id`。
- [x] 仓储层命名清理：`kg_repo` 中 node 命名方法迁移为 `knowledge_unit` 语义（旧别名/兼容函数已删除）。
- [x] 前端类型与调用链重命名：generated model + 页面状态 + props 全链路统一。
- [x] 迁移说明：补齐旧名到新名映射（DB/API/前端）。

**验收标准**
- [x] 主路径代码中不再把 Node 作为核心知识实体（仅兼容层保留）。
- [x] 对外 API 文档默认展示 `KnowledgeUnit`。

---

## P1 KnowledgeUnit 类型体系 + KG 关系类型体系对齐

### KnowledgeUnit 类型体系
- [ ] 定义 `KnowledgeUnit` 类型枚举：`concept/definition/theorem/formula/example/exercise/method/proof_step/remark`。
- [ ] 建立类型校验与默认映射策略（旧类型 -> 新类型）。
- [ ] 为 `KnowledgeUnit` 增加类型置信度与来源字段（`rule/llm/manual`）。

### KG 关系类型体系
- [ ] 定义关系枚举：`prerequisite/derivation/application/example_of/similar/contrast`。
- [ ] 建立旧关系到新关系映射：`prerequisite_of/defined_by/illustrated_by/part_of/belongs_to_topic` -> 标准关系。
- [ ] 更新抽取、解析、持久化、查询层以统一关系语义。
- [ ] 增加关系方向约束与合法性校验（如 prerequisite 方向约束）。

**验收标准**
- [ ] 新构建图仅包含标准 `KnowledgeUnit` 类型与标准关系类型。
- [ ] 旧数据可迁移并正确映射到新体系。

---

## P2 Markdown 锚点与 KnowledgeUnit 双向定位

- [ ] 引入显式锚点规范 `{#ku_xxx}` 作为稳定外部标识。
- [ ] 为 `KnowledgeUnit` 落库 `content_ref`（`doc_id + anchor`）。
- [ ] 建立 Markdown -> `KnowledgeUnit` 抽取器（支持 `[type:] [prerequisite:] [related:]` 标签）。
- [ ] 建立 `KnowledgeUnit` -> Markdown 回溯能力（定位、高亮、上下文提取）。
- [ ] 设计锚点变更策略（rename/move/split/merge）。

**验收标准**
- [ ] 任一 `KnowledgeUnit` 都可稳定回指 Markdown 原文位置。
- [ ] 同一锚点在增量构建中保持身份稳定。

---

## P3 KnowledgeUnit/KG 查询能力与子图 API

- [ ] 增加 `KnowledgeUnit` 列表/详情/关系查询 API。
- [ ] 增加路径查询 API（前置依赖展开、最短学习路径）。
- [ ] 增加子图 API（按主题、薄弱点、目标 `KnowledgeUnit` 生成 focus subgraph）。
- [ ] 增加关系解释 API（返回路径证据与来源片段）。

**验收标准**
- [ ] 前端可基于 API 展示“书 + 图 + 坐标”的统一视图。

---

## P4 学习路径、出题、评估、掌握度闭环

- [ ] 恢复并正式开放 `profile` API（移除 offline 占位）。
- [ ] 恢复并正式开放 `exams` API（移除 offline 占位）。
- [ ] 出题绑定主/辅 `KnowledgeUnit` 映射并回写作答结果。
- [ ] 掌握度更新基于 `KnowledgeUnit` 粒度（含遗忘曲线与复习优先级）。
- [ ] 学习路径生成使用 prerequisite 图与 mastery 状态。

**验收标准**
- [ ] 形成“出题 -> 作答 -> 评估 -> mastery 更新 -> 路径重排”闭环。

---

## P5 KG + RAG 主流程改造

- [ ] 检索主单元从粗粒度 chunk 切换到 `KnowledgeUnit`。
- [ ] 引入“先图约束、后文本回溯”的检索链路。
- [ ] 回答中返回 `KnowledgeUnit` 路径解释与引用片段。
- [ ] 对话策略接入用户子图与 mastery 上下文。

**验收标准**
- [ ] 相比纯向量检索，回答路径可解释且漂移率下降。

---

## P6 增量同步、迁移、测试、发布

- [ ] 建立 Markdown -> `KnowledgeUnit` -> KG 增量同步 pipeline（支持 diff）。
- [ ] 编写数据迁移脚本（旧 node/edge/type 全量迁移）。
- [ ] 建立契约测试：类型、关系、路径、回指、兼容 API。
- [ ] 建立回归测试：构建耗时、检索质量、出题命中率。
- [ ] 发布策略：灰度开关 + 回滚方案 + 观测看板。

**验收标准**
- [ ] 新旧版本可平滑切换，核心链路有监控与回滚保障。

---

## 跨阶段并行任务

- [ ] 维护术语对齐词典（`KnowledgeNode -> KnowledgeUnit`，`Unit/Topic` 等术语边界）。
- [ ] 维护兼容层清单（含预计删除版本）。
- [ ] 每阶段结束更新 OpenAPI 与前端生成类型。
- [ ] 每阶段输出迁移报告与风险清单。

---

## Definition of Done

- [ ] 系统核心实体命名与设计文档一致（`KnowledgeUnit` 为一等公民）。
- [ ] `KnowledgeUnit` 类型体系与 KG 关系体系完全对齐设计文档。
- [ ] Markdown 成为事实源，KnowledgeUnit/KG 支持稳定增量同步。
- [ ] Profile + Exams + Study Path + KG+RAG 形成闭环。
- [ ] 前后端接口、文档、测试全部收敛到新语义。
