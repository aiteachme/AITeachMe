## 一、三项目架构对齐

> 最后更新：2026-04-11
> 目标：回答”我有什么 / 他们有什么 / 我真正该借什么 / 当前最大的执行差距是什么”。

---

## 1.1 三个项目的角色定位

| 项目 | 强项 | 不足 | 对 AITeachMe 的价值 |
| --- | --- | --- | --- |
| `gpt-researcher` | 深度研究范式、检索器生态、上下文压缩、三级模型与 fallback | 教育语义弱，产物偏通用报告 | 提供 research 方法论和工具组织方式 |
| `DeepTutor` | 教育能力拆分、guide/interactive/media pipeline、统一能力入口 | runtime 较重，产品面较宽，不适合照搬 | 提供课程产品形态、富媒体 sidecar 思路 |
| AITeachMe | 五大引擎、LangGraph/LangSmith、前后端一体、教学闭环方向明确 | Digest 还未完全产品化，教学块与媒体链偏轻 | 把研究能力、教学能力、学习闭环整合成统一系统 |

---

## 1.2 能力矩阵对照

| 能力维度 | `gpt-researcher` | `DeepTutor` | AITeachMe 现状 | 当前判断 |
| --- | --- | --- | --- | --- |
| 研究范式 | `plan -> search -> compress -> write`，有 `DetailedReport / DeepResearch` | `planning -> researching -> reporting`，有 dynamic topic queue | `ChapterContextRuntime + PedagogyWriter + docgen graph`，但章节上下文构建仍偏单轮 | AITeachMe 需要借这两者的“研究深度控制” |
| 检索器生态 | 丰富，profile 驱动 | search providers + tool registry | `search/factory.py` 已支持 profile，retrievers 也较全 | 结构已经有，但 `profile` 还未完整打入执行链 |
| URL 读取 | 多 reader + URL 去重 | 较偏 research tool 调度 | `search/readers` + `web_reading` 已可用 | 现有方案足够，先不追求更多 provider |
| 课程产物 | 通用报告 | guide page / chat / summary / animator | 教学文档已有脚手架，但课程产品感还不够强 | 需要借 `DeepTutor` 的产物链 |
| 富媒体 | image skill，偏插图 | interactive page、math animator、summary | Mermaid 已较成熟，image 仍偏占位，interactive/animation 还没有 sidecar | 这是重要升级点 |
| 统一能力入口 | skill/action/retriever 分层 | capability/orchestrator/tool/service 分层 | `workflows + infra skills/tools + teaching` 三层已有雏形 | 当前结构更适合渐进式重构 |
| 教学块 | 基本没有 | 有 guide/chat/summary 等教育 agent | `teaching/documents` 已有 overview/guide/目标对照/模式块/recap | 需要继续向错因卡、公式卡、例题块扩展 |
| 观测能力 | LangSmith 可选 | 事件和 trace callback 较丰富 | LangSmith 已深度接入 | AITeachMe 已经具备后续优化优势 |

---

## 1.3 已完成、不必幻想重写的部分

### 已经做对了

- `shared/kernel` 与 `shared/infra` 的分层已经成立
- `digest/unified` 已把 Doc/KG/Curriculum 隔开
- `docgen` 已经不是单 prompt，而是稳定的多节点 pipeline
- `teaching/documents` 已经不是空壳，已有 overview、导读、模式块、recap 等实装
- LangSmith 已经能覆盖 workflow/node/skill/retriever/llm

### 不要为了参考项目推翻的部分

- 不要拆掉现有五大引擎
- 不要把 `digest` 改成编辑部式多 Agent
- 不要把 `DeepTutor` 的 capability runtime 搬进当前后端
- 不要让 `teaching` 长成第二套 infra

---

## 1.4 当前最关键的执行差距

### 差距 1：`retrieval_profile` 有观测，没有落执行

现在的事实是：

- `planner/docgen` state 中已经有 `course_type` 和 `retrieval_profile`
- `search/factory.py` 已经支持 `profile` 参数
- 但 `ChapterContextRuntime` 仍直接调用 `get_retrievers_for_subject(subject=..., local_sections=...)`
- 也就是说，课程模式下的检索差异，目前主要存在于 state 和 trace，而不是实际 retriever 组合

这是文档和代码之间最需要写实的一个点。

### 差距 2：研究深度仍偏“一次成稿”

`gpt-researcher` 的 `DeepResearchSkill` 和 `DetailedReport`，以及 `DeepTutor` 的 `ResearchPipeline`，都有显式的：

- 子话题拆解
- follow-up question
- 学到什么
- 下一轮查什么
- 并发/队列/重试

AITeachMe 当前的 `ChapterContextRuntime` 已有：

- 子查询规划
- local + external 检索
- curator
- compressor
- purify

但缺的仍是：

- 对 `required_elements` 的覆盖评估
- 轻量补检索
- 置信度与停机条件

### 差距 3：课程产物还没有真正比 Deep Research 更“会教”

当前 `teaching/documents/report_generation.py` 已经能自动补：

- `## 本章导读`
- `## 学习目标对照`
- `## 术语速览`
- 课程模式相关的二级标题
- `## 快速回顾` / `## 本章要点`

但离你要的“强教育产品”还差：

- 错因卡
- 公式逐项讲解卡
- 范例题变式
- 延伸迁移问题
- 交互 HTML / 动画 sidecar
- 更明确的章节质量契约

### 差距 4：富媒体还没有独立 sidecar 流程

`DeepTutor` 的 `GuideManager` 和 `MathAnimatorPipeline` 给了两个非常关键的启发：

- 正文生成不该和富媒体耦死
- 富媒体应该有自己的分析、设计、生成、重试、总结链

AITeachMe 当前状态：

- Mermaid：可用
- Image：偏占位
- Interactive HTML：还没真正进入文档 sidecar
- Animation：还没有独立 pipeline

结论不是“现在就做动画”，而是现在就要把接口预留对。

---

## 1.5 DeepTutor 深度分析（2026-04-11 补充）

### 1.5.1 DeepTutor 的核心架构特征

DeepTutor 采用 **Tool vs Capability** 两层插件模型：
- **Tool**：原子动作（retrieval、web_search、code_execution）
- **Capability**：多阶段 agent 流水线（deep_solve、deep_research、guide、question）

其 **统一 Turn Runtime** 是最值得借鉴的工程资产：
- 一致的请求格式（CLI / WebSocket）
- session + turn 创建与持久化
- 带 summarization budget 的 context 构建（长对话不爆上下文）
- capability 路由
- 流式事件总线（stage start/end、tool calls/results、partial LLM chunks）

### 1.5.2 DeepTutor 具体可借鉴点

| 特性 | DeepTutor 实现 | AITeachMe 借法 |
| --- | --- | --- |
| **Pre-retrieval planning** | DeepSolve planner 先生成多条检索 query → 并行检索 → LLM 聚合 → 再规划 | 借入 research micro-loop 的 query planning 阶段 |
| **Guided Learning 页面生成** | `InteractiveAgent` 为每个知识点生成交互 HTML（KaTeX 支持） | 借入 sidecar asset pipeline 的产品形态 |
| **KB 进度追踪** | ready/processing/error + per-stage progress API | 当前 `docgen_store` 已有类似机制，可对齐事件语义 |
| **Quiz follow-up** | 结构化问题上下文（correctness + explanation + knowledge context） | 借入 examine 引擎的 follow-up 设计 |
| **Context summarization** | 对话历史压缩到 token budget 内 | 借入 interact 引擎的长对话管理 |

### 1.5.3 DeepTutor 不应借的部分

- 其 RAG 管线较简单（纯 LlamaIndex vector retrieval，无 rerank、无 hybrid）
- 其 Guide 子系统与主 Turn Runtime 分离（JSON 文件持久化），不如 AITeachMe 的 LangGraph 统一
- 其 TutorBot 持久化 agent 概念过重，不适合当前阶段

### 1.5.4 与 gpt-researcher 的互补关系

| 维度 | gpt-researcher 更强 | DeepTutor 更强 |
| --- | --- | --- |
| 研究深度 | 递归子话题、多轮补检索、详细报告 | — |
| 检索器生态 | 多 provider、profile 驱动 | — |
| 教育产品形态 | — | guide page、quiz follow-up、math animator |
| 交互式学习 | — | 知识点级交互 HTML、进度追踪 |
| 上下文管理 | — | summarization budget、长对话压缩 |

结论：gpt-researcher 借”研究方法论”，DeepTutor 借”教育产品形态”。

---

## 1.6 三个项目的最优借法

### 从 `gpt-researcher` 借

- `ChapterContextRuntime` 的下一步：加微循环，不改 graph
- 检索 profile 明确化
- query planning / purify / curator 的工程纪律
- tier fallback 的稳定 trace

### 从 `DeepTutor` 借

- `BuildContract -> Draft -> AssetPlan -> Publish` 的产品形态
- sidecar 媒体链，而不是把媒体挤进正文 prompt
- 课程内容支持”设计 -> 互动 -> 追问 -> 总结”的可能性
- 面向教育产品的任务目录、输出文件和进度事件语义
- **Pre-retrieval planning 模式**：先检索再规划，提升 planner 质量
- **交互 HTML 生成**：为知识点生成 KaTeX 兼容的交互页面
- **Context summarization**：长对话/长构建的上下文压缩策略

### AITeachMe 自己必须坚持

- 五大引擎主架构不动
- `shared/infra / teaching / workflows` 三层边界不动
- Docs Lane 升级只影响 `digest` 本身，不外溢重写其他引擎
- LangSmith 作为后续所有优化的第一观测面板

---

## 1.7 一句话结论

AITeachMe 不缺骨架，缺的是：

- 让 `retrieval_profile` 真正生效
- 让 research 更像深度研究
- 让文档产物更像课程产品
- 让富媒体走独立 sidecar 流程

这正好对应 `gpt-researcher` 和 `DeepTutor` 各自最值得借的部分。
