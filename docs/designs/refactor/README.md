# AITeachMe × GPT-Researcher 重构基线

> 文档定位：本目录不是“庆功手册”，而是后续 Digest 重构、工具分层和 LangSmith 接入的执行合同。
> 最后更新：2026-04-09

---

## 1. 本轮重构只做两件大事

### 1.1 工具体系与分层边界重整

核心目标不是“把 gpt-researcher 的目录搬过来”，而是把它的高价值模式吸收到当前仓库：

- Plan-Search-Compress-Write 的研究范式
- Fast / Smart / Strategic 的模型分层
- Retrievers / Scrapers / Skills 的可插拔设计
- 面向 LangSmith 的细粒度可观测性

同时要把 AITeachMe 自己的边界压实：

- `app.shared.infra`：通用 AI runtime、外部集成、canonical memory、retriever、scraper、skill 基座
- `app.teaching`：教学语义、教学模板、教学反馈解释、教学文档脚手架
- `app.workflows`：五大引擎的 LangGraph 编排

### 1.2 Digest 产出升级为“教育型 Deep Research”

目标不是生成一篇通用研究报告，而是生成一份真正可学习、可复习、可追问、可扩展的知识文档：

- 支持“速成课”与“系统课”两种课程模式
- 通过对话先确定构建选项，再进入构建
- 章节级 research 具备更强的靶向检索和缺口补齐能力
- 文档原生支持公式、Mermaid、配图、后续交互 HTML 插槽
- 与 `examine` / `profile` 的教学闭环自然衔接

---

## 2. 当前基线与主要风险

### 2.1 已有基线

- `digest/docgen` 已有 8 节点 LangGraph 主链路
- `shared/infra/skills`、`search`、`tools` 已具备初步骨架
- 前端已具备 Markdown、Mermaid、公式的基础阅读能力
- LangSmith tracing 已经有比较好的基础设施

### 2.2 当前最需要先写清楚的风险

| 风险 | 说明 | 本轮文档策略 |
| --- | --- | --- |
| `shared/infra` 与 `teaching` 边界仍有摇摆 | 典型例子是 `memory` 出现双份实现，且路径语义不一致 | 明确 canonical 模块和过渡模块 |
| 部分文档“完成态”表述过强 | 容易掩盖剩余技术债，误导后续开发 | 改为“现状 + 缺口 + 分阶段目标” |
| Digest 还没有真正 deep-research 化 | 当前更像“章节 fan-out 写作”，不是“质量驱动的研究型文档生产” | 增加 Build Contract、检索 profile、章节级研究微循环 |
| 课程模式约束还不够强 | 速成课/系统课的章节结构、字数目标、媒体策略仍需收敛 | 单独定义文档产物契约 |
| 不能为了 Digest 重构伤及其他引擎 | `ingest` / `interact` / `examine` / `profile` 需要保持稳定 | 所有实施计划都以“只改 Docs Lane”为前提 |

---

## 3. 重构原则

1. 不做全仓“大一统重写”，优先修正边界、补齐契约、增强 DocGen 主链路。
2. 不照搬 `gpt-researcher` 的目录树，只吸收可证明有价值的方法。
3. `shared/infra` 解决“能力从哪里来、怎么接、怎么观测”；`teaching` 解决“教学语义如何表达”。
4. `digest` 的重构只动 Docs Lane，不改变 KG / Curriculum / 其他四大引擎的主逻辑。
5. 每个阶段都必须能在 LangSmith 上看清输入、输出、耗时、失败点。

---

## 4. 阅读顺序

| 文件 | 作用 |
| --- | --- |
| [01_architecture_alignment.md](01_architecture_alignment.md) | 看两个项目的能力映射，明确“学什么，不学什么” |
| [03_tools_refactor.md](03_tools_refactor.md) | 看 `infra / teaching / workflows` 的工具分层与迁移边界 |
| [04_docgen_pipeline.md](04_docgen_pipeline.md) | 看 Digest 如何升级成教育型 deep research 流程 |
| [05_document_modes.md](05_document_modes.md) | 看速成课 / 系统课的输出契约 |
| [06_retrieval_strategy.md](06_retrieval_strategy.md) | 看检索 profile、教育资源库、合规策略 |
| [07_teaching_tools.md](07_teaching_tools.md) | 看教学工具和通用工具怎样合理拆分 |
| [08_migration_plan.md](08_migration_plan.md) | 看 canonical 模块、过渡目录和清理顺序 |
| [09_execution_plan.md](09_execution_plan.md) | 看真正的实施阶段、验收口径和不改范围 |
| [10_langsmith_observability.md](10_langsmith_observability.md) | 看全链路 trace 规范 |
| [11_open_questions.md](11_open_questions.md) | 看尚需确认的产品/技术决策 |

---

## 5. 推荐实施顺序

### Phase A：先冻结边界

- 明确 `memory`、`skill`、`teaching function`、`documents` 的 canonical 落点
- 停止继续在过渡目录里新增平行实现

### Phase B：先把 Docs Lane 的输入契约写清楚

- 通过对话确认课程模式、目标、风格、媒体偏好、检索策略
- 让 Planner 输出稳定的 `Build Contract`

### Phase C：再增强章节级研究与文档质量

- 做检索 profile、章节 research 微循环、结构化富媒体插槽
- 先保证质量，再追求更多花哨能力

### Phase D：最后补教学闭环

- 用 `teaching` 接住 `examine` / `profile` 的解释层
- 让知识文档、练习、画像形成统一教学语言

---

## 6. 一句话结论

这轮 refactor 的正确姿势不是“把 gpt-researcher 搬进来”，而是：

- 用它的研究范式升级 `digest`
- 用它的可插拔思路整理 `infra`
- 用 AITeachMe 自己的教学语义沉淀 `teaching`
- 用 LangSmith 把整个构建过程变成可持续优化的透明系统
