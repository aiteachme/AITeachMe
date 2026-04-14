## 二、三级模型策略

> 最后更新：2026-04-14
>
> **Tier 命名**：`reason / primary / light`
> 目标：在保证速度和质量的前提下，让 `Planner / Grounding / Writer / Asset` 走不同模型层级，同时保证 LangSmith 中可比较、可追踪。

---

## 2.1 当前代码基线

当前仓库已经不是"只有 TaskType，没有 tier"。
真实实现是：

- `TaskType` 仍然是模型任务语义
- `llm_support/fallback.py` 已定义 `LLMTier = "reason" | "primary" | "light"`
- `acompletion_with_fallback()` 同时接受 `task_type` 与可选 `tier`
- `writer.py`、`mermaid_generator.py`、`resolve_titles_node.py` 已经在显式传 `tier`

也就是说，当前正确理解应该是：

> `TaskType` 负责说明"这是哪类任务"，`tier` 负责说明"这次更偏速度、质量还是规划脑"。

---

## 2.2 三级模型的职责划分

| 层级 | 当前实现 | 主要场景 | 优先级 |
| --- | --- | --- | --- |
| `reason` | `TaskType.REASONING` 为主 | 规划、子查询生成、Build Contract 收紧、缺口评估 | 推理深度优先 |
| `primary` | `TaskType.DOCGEN` 为主 | 章节写作、题目生成、批改、对话、OCR | 质量均衡 |
| `light` | `TaskType.DOCGEN_LIGHT` 为主 | KG 抽取、标题解析、分类、Mermaid 规划、轻量评估 | 吞吐/成本优先 |

---

## 2.3 对 Digest 的推荐映射

### Planner

- `confirm_plan`、`chapter_plan`、`BuildContract` 校验建议：`reason`
- 目标：少调用，但要稳定、清楚、结构化

### Grounding / Retrieval

- `generate_sub_queries`：`reason`
- `assess_gaps`：`light`
- `purify_material`：`light`
- 目标：尽量把重质量用在"查什么"和"还缺什么"，不要把昂贵模型浪费在机械整理上

### Writer

- `PedagogyWriter` 主写作：`primary`
- 标题解析、块级修补：`light`
- 目标：把长文本质量留给正文，把格式整理和补洞交给轻量模型

### Asset

- Mermaid 规划：`light`
- 图片 prompt 规划：`light`
- 交互 HTML / 动画设计稿：`primary`
- 目标：资产规划和最终正文分开，不让富媒体拖垮主链路

---

## 2.4 失败语义（Strict Mode）

当前 `fallback.py` 采用 **strict failure 模式**：

- 没有 fallback chain — 一次调用失败就直接抛异常
- 调用方（workflow node）决定是否 retry 或降级
- LangSmith metadata 中始终记录 `llm_tier`、`llm_strict_mode=True`

这样做的好处：

- 不会静默降级导致质量下降而不自知
- 日志和 LangSmith 中可以清晰看到"哪些节点的哪次调用失败了"
- 产品逻辑不会因为 fallback 链里的 side-effect 而变得不可预测

---

## 2.5 建议的调用纪律

### 原则 1：优先声明 `task_type`

`task_type` 仍然是稳定的业务语义，决定：

- token/profile 预算
- 观测维度
- 该任务本来属于哪类模型动作

### 原则 2：只在确实需要"速度/质量偏置"时覆盖 `tier`

适合显式传 `tier` 的场景：

- 同一个 `task_type` 下要强制更快
- 某个节点内部包含多种子动作，需要人为收紧层级
- 需要把高质量配额留给真正重要的写作或规划节点

不适合乱传 `tier` 的场景：

- 所有节点都手动覆盖
- 为了"看起来聪明"统一上 `reason`
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
- 允许更多 `light` / `primary`
- 不建议大面积使用 `reason`

### `systematic`

- 更重结构完整性和解释质量
- 允许在 `BuildContract`、缺口评估、结构校正上多用 `reason`
- 写作阶段仍以 `primary` 为主

---

## 2.7 与参考项目的关系

### 借自 `gpt-researcher`

- 三级模型概念
- tier 是"逻辑能力分层"，不是简单换个模型名

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
- 对比分析失去意义

### 风险 2：`retrieval_profile` 和 `tier` 混淆

二者不是一回事：

- `retrieval_profile` 决定"去哪查"
- `tier` 决定"用多贵的脑子整理"

### 风险 3：富媒体抢正文预算

图片、Mermaid、交互设计不应和主文正文抢同一批高质量调用预算。

---

## 2.9 推荐默认值

| 阶段 | 默认层级 |
| --- | --- |
| Planner confirm / contract normalization | `reason` |
| 章节 query planning | `reason` |
| 章节 gap assessment | `light` |
| 研究笔记 purify | `light` |
| 正文写作 | `primary` |
| 标题修正 / 轻量结构补全 | `light` |
| Mermaid / 图片 prompt 规划 | `light` |
| 交互 HTML / 动画设计稿 | `primary` |

---

## 2.10 一句话结论

对 AITeachMe 来说，三级模型策略的重点不是"分三个名字"，而是：

- 把贵模型预算集中在规划和正文
- 把轻量模型预算集中在整理和资产规划
- 让所有调用都能在 LangSmith 中被清楚看见
