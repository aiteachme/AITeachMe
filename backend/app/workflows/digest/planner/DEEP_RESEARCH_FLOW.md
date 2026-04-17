# Planner Deep Research 流程简版

最后更新：2026-04-17

这份文档只说明 `digest/planner` 后续怎么做得更像 Deep Research，但不把它写成复杂研究报告。

## 一句话结论

当前 Planner 主线是对的：

```text
读取资料 -> 快速摘要 -> 可见思考草稿 -> 证据检索 -> 合成 confirmed plan
```

后续不要大拆 graph，也不要把 Planner 改成完整多 Agent 系统。最该补的是：

```text
检索候选 -> 判断哪些值得打开 -> 读本地 section / 网页正文 -> 形成 grounding pack -> 再合成计划
```

也就是让 Planner 真正“读过关键证据”，而不是只看文件名、摘要和搜索 snippet。

## 当前流程

代码入口：

- `graph.py`
- `state.py`
- `nodes/`
- `prompts/`
- `lib/`
- `../common/prepare.py`
- `../common/material_digest.py`

当前 LangGraph：

```text
prepare_material_context
  -> summarize_material_digest
  -> bootstrap_plan_brief
  -> probe_evidence
  -> compose_build_plan
  -> finalize_plan_contract
```

## 每一步现在做什么

### 1. `prepare_material_context`

读取已解析资料，构建统一资料包：

- `source_documents`
- `material_sections`
- `material_hints`
- `material_assets`
- `learning_domain_profile`
- `material_stats_profile`
- `course_mode_decision`

如果正文还没解析好，会退化成 seed context，先基于文件名和用户目标生成临时方案。

### 2. `summarize_material_digest`

对每个文件做 light 摘要：

```text
每份资料取前 10000 字 -> 并行摘要 -> 写入 material_context.material_digest
```

这一步适合做“速览”，但它不是证据层。最终大纲如果只吃这个，仍然会偏粗。

### 3. `bootstrap_plan_brief`

并行做两件事：

```text
stream_plan_sketch       # reason 模型，SSE 输出可见草稿
extract_learning_intent  # light 模型，结构化识别目标
```

这一步的目标是快，让前端尽早看到系统正在如何理解学习目标。

### 4. `probe_evidence`

当前会：

```text
生成 probe queries
  -> 调用 local_rag 和外部 retriever
  -> 筛选来源
  -> 打开少量网页
  -> 生成 EvidenceBrief
```

这里是下一步最值得改的地方。

当前问题：

- 本地命中大多还是 snippet/preview，没有真正打开 section 正文。
- 选源偏规则，没有明确记录“为什么选这个来源”。
- EvidenceBrief 粒度偏粗，不能稳定告诉后续 compose：“这个章节为什么这么分”。

### 5. `compose_build_plan`

综合以下信息生成 `BuildPlannerDraft`：

- 资料理解包
- 可见草稿
- 学习意图
- evidence brief
- 用户历史消息
- latest plan

这一步可以保留，后续只需要让它多吃一个更扎实的 `GroundingPack`。

### 6. `finalize_plan_contract`

只做合同收口：

- normalize
- fallback merge
- 套用 sketch preferences
- 输出稳定 plan payload

这一步不要变复杂。主题边界和证据判断应该在前面完成。

## 参考外部方案后得到的简化原则

### OpenAI / Gemini Deep Research

共同点：

```text
先生成研究计划
  -> 用户可确认或修改
  -> 再多轮搜索、阅读、继续搜索
  -> 最后生成带来源的报告
```

对 Planner 的启发：

- 先给用户看“计划和理由”。
- 检索不是一次搜索，应该有“读后再判断缺口”的感觉。
- 来源策略要明确：本地优先、允许外部、search-only、可信站点等。

### GPT Researcher

核心模式：

```text
query
  -> 初始搜索
  -> 生成 sub queries
  -> 并发搜索和抓取
  -> 压缩上下文
  -> 写报告
```

可借鉴：

- query planning。
- 多来源检索。
- source curation。
- context compression。

不建议照搬：

- 递归 deep research。
- 嵌套多个 researcher。
- 通用报告写作方式。

### DeepTutor

核心模式：

```text
outline preview
  -> confirmed outline
  -> DynamicTopicQueue
  -> 每个 topic 多轮 tool call
  -> NoteAgent 压缩证据
  -> CitationManager 管理引用
  -> ReportingAgent 写报告
```

可借鉴：

- 先 preview，再确认。
- 每轮工具调用都留下 trace。
- 证据和引用要结构化保存。

不建议现在照搬：

- 动态新增章节。
- 多 Agent 全量队列。
- 自动改变用户已经确认的 plan。

## 推荐改造目标

Planner 下一版建议这样理解：

```text
prepare_material_context
  -> summarize_material_digest
  -> bootstrap_plan_brief
  -> open_grounding_context
  -> compose_build_plan
  -> finalize_plan_contract
```

其中 `open_grounding_context` 可以先沿用 `probe_evidence` 的节点名，避免立刻大改 graph。

## `open_grounding_context` 做什么

建议分 5 步：

```text
1. 生成 probe queries
2. 检索 local/web candidates
3. 判断哪些 candidates 值得打开
4. 打开本地 section 正文和少量网页正文
5. 汇总 GroundingPack
```

建议输出结构：

```text
GroundingPack
  - source_policy
  - selected_queries
  - selected_sources
  - opened_contexts
  - core_concepts
  - chapter_grounding_hints
  - gap_notes
```

字段含义：

- `source_policy`：本地优先、web-first、search-only 等。
- `selected_queries`：本轮真正执行的查询。
- `selected_sources`：被选中的来源。
- `opened_contexts`：实际打开读过的本地段落或网页正文摘要。
- `core_concepts`：证据里反复出现的核心概念。
- `chapter_grounding_hints`：对章节拆分有帮助的证据提示。
- `gap_notes`：仍不确定或资料不足的地方。

## 最小改造顺序

### Step 1：先补本地开读

在 `probe_evidence` 里做最小增强：

```text
local_rag 命中
  -> 找回对应 SectionPacket
  -> 截取 normalized_content
  -> 写入 opened_sources/opened_contexts
```

目标：

- compose 时能吃到真实资料正文。
- 前端能展示“已打开本地资料片段”。

### Step 2：补 `GroundingPack`

先不改 API，只扩 workflow state：

```text
state["grounding_pack"] = {...}
```

然后让 `compose_build_plan` prompt 消费它。

### Step 3：模型选源

在规则筛选之后，加一个轻量结构化判断：

```text
candidates -> light/primary -> selected_sources
```

让模型输出：

- source id
- reason
- 对哪个章节/概念有帮助
- 是否需要打开

### Step 4：前端展示事件

Planner SSE 事件建议保持简单：

```text
planner.material.ready
planner.thinking.delta
planner.intent.ready
planner.probe.started
planner.sources.triaged
planner.contexts.opened
planner.evidence.ready
planner.plan.composing
planner.plan.ready
```

前端只需要清楚展示：

- 当前在做什么。
- 本地命中多少。
- 外部命中多少。
- 打开了哪些资料。
- 计划为什么这样分。

## 当前明显问题

### P0

1. `probe_evidence` 没有真正打开本地 section 正文。
2. `compose_build_plan` 缺少精确 grounding context。
3. Planner 事件里还没有 `planner.contexts.opened` 这种明确“已开读”的阶段。

### P1

1. source selection 需要从规则筛选升级到“规则 + 模型选读”。
2. `GroundingPack` 应写入 planner debug/trace，方便排查大纲质量。
3. search-only/web-first 模式要在前端更明显提示。

## 和 DocGen 的边界

Planner 只负责：

```text
生成可确认的构建方案
```

DocGen 负责：

```text
逐章研究 -> 写作 -> 增强 -> 练习 -> 发布
```

所以 Planner 不应该做完整章节写作，也不应该替 DocGen 做详细 evidence ledger。Planner 只需要给 DocGen 一个更可靠的 confirmed plan：

- 章节标题更贴近真实资料。
- 每章目标更清晰。
- search queries 更可执行。
- required elements 更像证据里真实出现的知识边界。

## 近期不做什么

先不要做：

- 不引入完整多 Agent。
- 不做递归 deep research。
- 不让 Planner 自动新增复杂动态章节队列。
- 不恢复 `app/teaching` 旧层。
- 不新建第二套 search/tool registry。

保持当前架构边界：

```text
api -> workflows -> repositories / shared.infra / models / schemas
```

新能力优先复用：

- `app.shared.infra.search`
- `app.shared.infra.facade.research`
- `app.shared.infra.workflow`
- `digest/common`

## 一句话收束

Planner 下一步不是变成“万能研究助手”，而是变成一个更可靠的学习资料规划器：

```text
先快速说明理解方向，
再真正打开关键证据，
最后产出用户可确认、DocGen 可执行的构建方案。
```
