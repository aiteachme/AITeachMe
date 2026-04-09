## 三、工具体系重构

> 目标：把 `gpt-researcher` 的高价值工具组织方式吸收进来，同时彻底厘清 `shared/infra`、`teaching`、`workflows` 三层的职责边界。  
> 最后更新：2026-04-09

---

## 3.1 先讲结论

用户提出的方向需要进一步说死成下面这条规则：

- `shared/infra` 放接口、抽象、策略、统一 runtime 接入和可替换实现
- `teaching` 放 AITeachMe 教学任务适配、教学规则和教学表达

但必须加一条硬约束：

> **`teaching` 可以包装和解释 `infra`，不能复制一套新的 `infra`。**

这是当前最重要的结构纪律。

---

## 3.2 我们真正要复用 gpt-researcher 的是什么

### 应该复用的

- `Actions / Retrievers / Scrapers / Skills` 的层次化拆分
- “先研究、再压缩、再写作”的固定范式
- 用 profile 和工厂控制检索器组合
- 把复杂能力做成可独立追踪的组合 Skill

### 不应该复用的

- 目录名一比一复制
- 所有搜索源全量接入
- 为了“像它”而把现有 LangGraph 编排打散
- 把 MCP、retriever、tool、skill 混成一层

一句话：

> 复用的是方法，不是外壳。

---

## 3.3 当前最明显的结构问题

### 问题 1：`memory` 出现平行实现

当前仓库里同时存在：

- `app.shared.infra.memory`
- `app.teaching.memory`

而且它们并不是单纯 re-export，至少在 `learner_doc.py` 中已经出现了路径语义分叉：

- `shared/infra/memory/learner_doc.py` 走 `backend/data/users/<user_id>/LEARNER.md`
- `teaching/memory/learner_doc.py` 仍保留 `~/.atm/...` 语义

这会直接带来两个风险：

- 同一概念出现两个“真相源”
- 文档、调试、运行时路径判断会失真

**结论：**

- `app.shared.infra.memory` 必须成为 canonical memory 实现
- `app.teaching.memory` 只允许保留兼容 facade / adapter，不允许继续长新逻辑

### 问题 2：教学动作和组合 Skill 的边界还不够清楚

当前既有：

- `shared/infra/skills/*`
- `teaching/teaching.py`
- `teaching/skill_tools.py`

这三者都在表达“可复用能力”，但抽象层次不一致。

需要统一成下面的分工：

- 原子动作：`shared/infra/tools`
- 通用组合能力：`shared/infra/skills`
- 教学语义动作：`app.teaching`

### 问题 3：文档脚手架已经在 `teaching/documents`，但还缺少稳定的扩展契约

现在 `build_document_overview()` 和 `ensure_chapter_learning_scaffold()` 已经开始承接教学表达，这是好方向。  
但后续若要支持：

- 公式卡片
- 例题块
- 易错点块
- 交互 HTML
- 动画 / 图像说明

就不能继续只靠散落的字符串拼接和占位符约定，必须定义更稳定的 block / asset contract。

### 当前代码里已经能看到的边界事实

有三条代码事实很适合反向写入架构文档：

1. `app.teaching.context` 直接依赖 `app.shared.infra.memory.get_user_profile` 和 `recall`  
   说明 canonical memory 在 `infra`，teaching 负责按教学场景重组。
2. `app.shared.infra.skills.writer` 调用 `app.teaching.documents.ensure_chapter_learning_scaffold`  
   说明 writer 的执行骨架在 `infra`，教学脚手架在 `teaching`。
3. `workflows/digest/docgen/publish.py` 调用 `app.teaching.documents.build_document_overview`  
   说明发布阶段也已经把“怎样更像教学文档”的判断委托给 teaching。

这些事实支持的不是“infra 包办一切”，而是：

- `infra` 提供接口、执行骨架和统一策略
- `teaching` 提供任务适配和教学成功标准

同时应补一句约束：

- `shared/infra -> teaching` 这类调用目前只应作为显式教学表达 hook 存在，不能扩散成新的常态依赖

---

## 3.4 目标分层

### 3.4.1 `shared/kernel`

只放纯内核概念：

- `ids`
- `time`
- `events`
- `exceptions`

禁止放：

- LLM
- retriever
- storage
- teaching 语义

### 3.4.2 `shared/infra`

放通用 runtime、接口抽象与外部集成：

- LLM / embedding / model router / fallback
- retrievers / scrapers / search factory
- tools / tool registry / tool loader
- skills base 与通用组合 skill
- canonical memory / storage / cache / tracing / sandbox / mcp

这里解决的是：

- “系统有哪些稳定能力接口”
- “这些能力如何统一接入和替换”
- “这些能力的共通策略是什么”
- “这些能力如何统一 tracing”

这里优先沉淀的不是“某个具体教学任务怎么做”，而是：

- port / contract
- strategy / policy
- factory / registry
- base class / adapter point
- runtime 约束

### 3.4.3 `teaching`

放教学语义与教学表达：

- 教学脚手架
- 教学解释模板
- 错因诊断表达
- 练习设计与教学反馈
- 文档章节结构、教学块、教学导读

这里解决的是：

- “如何把底层能力适配成 AITeachMe 的教学任务”
- “如何把研究材料变成可学、可教、可练的课程内容”
- “什么才算符合我们产品理念的教学表达”

### 3.4.4 `workflows`

放编排，不放底层实现：

- LangGraph graph / state / runtime
- 并发策略
- 状态推进
- lane 间协作

这里解决的是：

- “先做什么，后做什么”
- “每一步的 state 如何流动”

---

## 3.5 新代码应该放哪里

| 新能力 | 正确落点 | 说明 |
| --- | --- | --- |
| 通用 Web 搜索、抓取、内容分析 | `shared/infra/tools` 或 `shared/infra/search` | 原子能力，和教学无关 |
| 研究上下文压缩、来源筛选、媒体生成 | `shared/infra/skills` | 多步组合能力，可被多个 workflow 复用 |
| 概念讲解、错因解释、章节导读、学习建议 | `app.teaching` | 明确是任务适配和教学表达，不是底层接入 |
| 章节级研究、写作、发布顺序 | `workflows/digest` | 属于编排 |
| 数据库查询 / 持久化 | `repositories` | 不要塞回 workflow / teaching |

---

## 3.6 从 gpt-researcher 到 AITeachMe 的映射

| gpt-researcher 概念 | AITeachMe 目标落点 | 说明 |
| --- | --- | --- |
| `actions/query_processing.py` | `shared/infra/tools/builtin/query_processing.py` | 保持原子工具属性 |
| `actions/web_scraping.py` | `shared/infra/tools/builtin/web_scraping.py` + `shared/infra/search/scraper` | 调度与实现分离 |
| `actions/report_generation.py` | `shared/infra/skills/writer.py` + `app.teaching.documents` | 写作与教学脚手架分层 |
| `skills/researcher.py` | `shared/infra/skills/researcher.py` | 研究组合能力 |
| `skills/context_manager.py` | `shared/infra/skills/context_manager.py` | 上下文压缩 |
| `skills/source_curator.py` | `shared/infra/skills/source_curator.py` | 来源质量控制 |
| `skills/image_generator.py` | `shared/infra/skills/image_generator.py` | 先做 asset skill，不直接绑 workflow |
| `retrievers/*` | `shared/infra/search/retrievers/*` | 只引入有价值的，不追求数量对齐 |

---

## 3.7 工具分级规范

### A. Atomic Tool

特征：

- 输入输出稳定
- 单一动作
- 易测
- 可被 Skill 或 agent loop 调用

示例：

- `web_search`
- `search_kb`
- `normalize_math_delimiters`
- `extract_key_terms`

### B. Composed Skill

特征：

- 内部会调用多个 tool / retriever / scraper / llm
- 需要独立 trace
- 会被 workflow 节点直接使用

示例：

- `ResearchConductor`
- `ContextManager`
- `PedagogyWriter`
- `MermaidGenerator`

### C. Teaching Action / Teaching Adapter

特征：

- 面向学习者或课程设计
- 目标是“任务适配正确、教学表达正确”，不是“底层接入正确”
- 可以调用 Infra Skill，但不复制它

示例：

- 概念对比
- 错因翻译
- 章节导读
- 学习目标对照
- 练习讲评

---

## 3.8 关于 `memory tools` 的明确决策

### canonical 设计

- Memory store / profile / learner doc 的真相源：`app.shared.infra.memory`
- Tool 级读写接口：`shared/infra/tools/builtin/memory_ops.py`
- 教学语义封装：`app.teaching` 调用 canonical memory，再组织成教学上下文

### 禁止事项

- 不允许在 `app.teaching.memory` 新增第二套存储逻辑
- 不允许在 `app.teaching.memory` 再定义与 canonical path 冲突的运行时路径
- 不允许在 workflow 节点里直接拼 learner doc 路径

### 允许事项

- `app.teaching.memory` 暂时作为兼容 facade 保留
- 旧调用可以逐步迁移，不必一次删光
- 但所有新实现必须直接站到 `app.shared.infra.memory` 上

---

## 3.9 下一步推荐迁移顺序

### Step 1：冻结 canonical 模块

- `shared/infra/memory` 设为唯一 canonical memory
- `teaching/memory` 标记为过渡层

### Step 2：收敛教学能力入口

- 轻量教学模板继续留在 `app.teaching`
- 一旦需要多步 LLM / retriever / asset orchestration，就升级为 `shared/infra/skills`

### Step 3：让 `teaching/documents` 成为文档表达层

- 章节导读
- glossary
- 学习目标对照
- 例题块 / 易错点块 / 总结块

这些都由 `teaching` 统一定义，不要再次回流到 workflow 节点里。

### Step 4：让 `digest` 只编排

- research 在 `ResearchConductor`
- 写作在 `PedagogyWriter`
- 教学结构在 `teaching/documents`
- 媒体生成在 media skills

这样后面继续升级时，图不会变脏，LangSmith 也更清楚。

---

## 3.10 一句话结论

`infra` 放“接口、抽象、策略和统一 runtime 能力”，`teaching` 放“面向 AITeachMe 任务的教学适配”，`workflows` 放“流程编排”，这条分层是对的。  
真正要避免的是：在 `teaching` 里再长出第二套 `infra`，或者在 `workflow` 里偷偷塞回教学实现。
