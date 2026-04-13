## 二、三级模型策略

> 最后更新：2026-04-12
> 目标：在保证速度和质量的前提下，让 `Planner / Grounding / Writer / Asset` 走不同模型层级，同时保证 LangSmith 中可比较、可追踪、可降级。

---

## 2.1 当前代码基线

当前仓库已经不是“只有 TaskType，没有 tier”。
真实实现是：

- `TaskType` 仍然是模型任务语义
- `llm_support/fallback.py` 已定义 `LLMTier = "strategic" | "smart" | "fast"`
- `acompletion_with_fallback()` 同时接受 `task_type` 与可选 `tier`
- `writer.py`、`mermaid_generator.py`、`resolve_titles_node.py` 已经在显式传 `tier`

也就是说，当前正确理解应该是：

> `TaskType` 负责说明“这是哪类任务”，`tier` 负责说明“这次更偏速度、质量还是规划脑”。

---

## 2.2 三级模型的职责划分

| 层级 | 当前实现 | 主要场景 | 优先级 |
| --- | --- | --- | --- |
| `strategic` | `TaskType.REASONING` 为主，fallback 到 `DOCGEN` / `DOCGEN_LIGHT` | 规划、子查询生成、Build Contract 收紧、缺口评估 | 质量优先 |
| `smart` | `TaskType.DOCGEN` 为主，fallback 到 `DOCGEN_LIGHT` / `DEFAULT` | 章节写作、长文本组织、总结、解释 | 平衡 |
| `fast` | `TaskType.DOCGEN_LIGHT` 为主，fallback 到 `DEFAULT` | 标题解析、术语/结构整理、Mermaid 规划、轻量评估 | 速度优先 |

---

## 2.3 对 Digest 的推荐映射

### Planner

- `confirm_plan`、`chapter_plan`、`BuildContract` 校验建议：`strategic`
- 目标：少调用，但要稳定、清楚、结构化

### Grounding / Retrieval

- `generate_sub_queries`：`strategic`
- `assess_gaps`：`fast`
- `purify_material`：`fast`
- 目标：尽量把重质量用在“查什么”和“还缺什么”，不要把昂贵模型浪费在机械整理上

### Writer

- `PedagogyWriter` 主写作：`smart`
- 标题解析、块级修补：`fast`
- 目标：把长文本质量留给正文，把格式整理和补洞交给轻量模型

### Asset

- Mermaid 规划：`fast`
- 图片 prompt 规划：`fast`
- 交互 HTML / 动画设计稿：`smart`
- 目标：资产规划和最终正文分开，不让富媒体拖垮主链路

---

## 2.4 当前 fallback 行为

当前 `fallback.py` 的真实逻辑是按 `tier` 跑稳定降级链：

| 请求层级 | 候选链 |
| --- | --- |
| `strategic` | `REASONING -> DOCGEN -> DOCGEN_LIGHT` |
| `smart` | `DOCGEN -> DOCGEN_LIGHT -> DEFAULT` |
| `fast` | `DOCGEN_LIGHT -> DEFAULT` |

每次候选尝试都会在 LangSmith metadata 中记录：

- `llm_tier`
- `llm_candidate_tier`
- `llm_candidate_task_type`
- `llm_fallback_from`
- `llm_fallback_to`

这意味着后续可以非常明确地看：

- 哪些节点经常发生降级
- 哪些 tier 配置过于乐观
- 哪些阶段真正的瓶颈在模型，而不是检索或抓取

---

## 2.5 建议的调用纪律

### 原则 1：优先声明 `task_type`

`task_type` 仍然是稳定的业务语义，决定：

- token/profile 预算
- 观测维度
- 该任务本来属于哪类模型动作

### 原则 2：只在确实需要“速度/质量偏置”时覆盖 `tier`

适合显式传 `tier` 的场景：

- 同一个 `task_type` 下要强制更快
- 某个节点内部包含多种子动作，需要人为收紧层级
- 需要把高质量配额留给真正重要的写作或规划节点

不适合乱传 `tier` 的场景：

- 所有节点都手动覆盖
- 为了“看起来聪明”统一上 `strategic`
- 业务语义不清，只是碰运气调模型

### 原则 3：Planner 少而贵，Writer 稳而准，Asset 轻而快

这是 Digest 最适合的默认策略：

- Planner：调用少，但要结构正确
- Grounding：把贵模型用在 query planning 和 gap assessment
- Writer：正文优先稳定质量
- Asset：默认不抢正文预算

---

## 2.6 与课程模式的关系

### `sprint`

- 更重速度和得分信息密度
- 研究补检索上限应更低
- 允许更多 `fast` / `smart`
- 不建议大面积使用 `strategic`

### `systematic`

- 更重结构完整性和解释质量
- 允许在 `BuildContract`、缺口评估、结构校正上多用 `strategic`
- 写作阶段仍以 `smart` 为主

---

## 2.7 与参考项目的关系

### 借自 `gpt-researcher`

- 三级模型概念
- fallback 是“逻辑能力降级链”，不是简单换个模型名

### 结合 AITeachMe 的改造

- 通过 LangSmith metadata 让 tier 可观测
- 通过 `TaskType + tier` 双层表达，让 workflow 代码更清楚
- 让 tier 服务于教育产品质量，而不是纯研究报告

---

## 2.8 风险与改进点

### 风险 1：tier 过度手动覆盖

如果每个节点都自己传 `tier`，最终会导致：

- 文档失真
- 观测难统一
- fallback 失去比较意义

### 风险 2：`retrieval_profile` 和 `tier` 混淆

二者不是一回事：

- `retrieval_profile` 决定“去哪查”
- `tier` 决定“用多贵的脑子整理”

### 风险 3：富媒体抢正文预算

图片、Mermaid、交互设计不应和主文正文抢同一批高质量调用预算。

---

## 2.9 推荐默认值

| 阶段 | 默认层级 |
| --- | --- |
| Planner confirm / contract normalization | `strategic` |
| 章节 query planning | `strategic` |
| 章节 gap assessment | `fast` |
| 研究笔记 purify | `fast` |
| 正文写作 | `smart` |
| 标题修正 / 轻量结构补全 | `fast` |
| Mermaid / 图片 prompt 规划 | `fast` |
| 交互 HTML / 动画设计稿 | `smart` |

---

## 2.10 一句话结论

对 AITeachMe 来说，三级模型策略的重点不是“分三个名字”，而是：

- 把贵模型预算集中在规划和正文
- 把轻量模型预算集中在整理和资产规划
- 让所有降级都能在 LangSmith 中被清楚看见
