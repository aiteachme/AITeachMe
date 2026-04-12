# 04. DocGen Pipeline

最后更新：2026-04-13

## 1. 当前主骨架

DocGen 顶层 graph 现在的真实骨架是：

```text
load_context
-> targeted_research (fan-out by chapter)
-> collect_materials
-> resolve_titles
-> pedagogy_craft (fan-out by chapter)
-> collect_drafts
-> enrich_document
-> inject_examine
-> finalize_assemble
```

这里有两个容易误解的点：

1. `targeted_research` 和 `pedagogy_craft` 不是串行单章，而是章节 fan-out。
2. `collect_materials` / `collect_drafts` 不是噪声节点，它们承担 fan-in 汇总与后续阶段的状态收口。

所以这轮优化的原则仍然是：

- 不推倒 graph
- 不把 runtime 再搬回 infra
- 在现有骨架内继续增强 research、writing、asset、practice 质量

## 2. 当前 ownership

### 2.1 Workflow-local runtime

当前 DocGen 业务专属多步逻辑已经明确归到：

- `workflows/digest/docgen/runtime/chapter_context.py`
- `workflows/digest/docgen/runtime/writer.py`
- `workflows/digest/docgen/runtime/assets.py`

这些 runtime 负责：

- 章节 research micro-loop
- chapter-level teaching writing
- asset sidecar 展开

### 2.2 Infra helper

当前仍应放在 infra 的，是离开 DocGen 仍可复用的基础能力：

- search factory / retrievers / readers
- `ContextCompressor`
- `SourceCurator`
- LLM routing / fallback / traced execution
- 工具注册与 skillpack 解析

### 2.3 Teaching

当前 teaching 层继续负责：

- 教学脚手架
- chapter title resolution
- 教学表达块
- teaching-owned 原子工具

不负责 DocGen graph 编排和 research runtime。

## 3. Confirmed Plan 与 Skillpack 入口

当前已经打通的链路是：

```text
planner
-> confirmed plan contract
-> load_context
-> document_context / chapter assignment
-> research runtime / writer runtime
```

当前 `load_context` 已经会解析并下发：

- `selected_skillpacks`
- `skillpack_defaults`
- `recommended_tool_tags`
- `skillpack_guidance`
- `course_type`
- `retrieval_profile`
- confirmed plan 的 chapter assignment / execution contract

这意味着 skillpack 现在已经是真正影响 DocGen 的执行输入，而不再只是 prompt 附件。

## 4. Research runtime 的当前状态

`DocGenChapterContextRuntime` 当前已经不是单轮 research helper，而是受控 micro-loop：

- 先做 seed query + sub query planning
- 按 round 执行 retrieve -> curate -> compress
- 根据 `coverage_score / gaps_remaining` 补 gap queries
- 用 `round cap / diminishing returns / coverage target` 停机
- 额外可对 dense context 做 `purify`

当前已经输出到 metadata / lane summary 的关键字段包括：

- `requested_profile`
- `applied_profile`
- `executed_queries`
- `fallback_queries`
- `retriever_stats`
- `research_rounds`
- `research_round_count`
- `coverage_score`
- `gaps_remaining`
- `source_class_breakdown`
- `stop_reason`

所以“research micro-loop”不再是未来计划，而是已经进入当前执行链；后续重点是调优，不是从零设计。

## 5. Writing、Enrich、Practice 的当前状态

### `resolve_titles`

- 负责把章节标题从 provisional task title 收敛为更稳定的教学标题。
- 这一步已经和 planner 产出的 chapter plan 协同，不再是孤立 prompt。

### `pedagogy_craft`

- 当前按章节 fan-out 执行。
- writer runtime 已带 `course_type / retrieval_profile / selected_skillpacks / teaching_action`。
- 文档产物已经具备比“摘要”更强的教学脚手架，但 richer blocks 仍可继续补强。

### `inject_examine`

- 当前已经是 digest-local 的 mode-aware practice layer。
- 它的职责是把练习内容注入当前文档构建链。
- 但它还没有和独立 Examine 引擎共享更深的题目上下文与知识状态。

## 6. Asset sidecar 的当前状态

当前 asset sidecar 已经不是纯设计，它已经具备最小执行链：

- Mermaid placeholder -> runtime 生成/回退
- image placeholder -> runtime 展开为建议块
- interactive placeholder -> runtime 生成最小 HTML 模板

当前 summary 侧已经能聚合：

- `mermaid_block_count`
- `image_block_count`
- `interactive_block_count`
- `asset_count`
- `asset_summary`

需要明确的是：

- `interactive_html` 已经进入最小主线，但仍属于模板级 MVP
- `animation` 目前仍只是 contract / trace 预留位，尚未进入真正执行链

## 7. `sprint / systematic` 的真实落点

这两种模式现在已经不只存在于 prompt：

- confirmed plan contract
- chapter execution contract
- research runtime strategy
- writer/runtime 的表达与组织
- practice layer
- lane summary 与 trace metadata

因此后续工作不再是“让模式进入代码”，而是：

- 继续细化不同学科的章节合同
- 继续细化 mode-specific 资产策略和练习策略
- 继续让不同模式在质量评分上形成更明显分层

## 8. 现在还差什么

DocGen 当前最值得继续推进的不是改骨架，而是下面四件事：

1. 让 research micro-loop 的 coverage / stop 逻辑更稳。
2. 把 richer teaching blocks、质量契约和 repair 机制继续做深。
3. 把 interactive/image sidecar 从 MVP 模板做成真正有教学价值的富媒体链。
4. 把 Digest 与 Interact / Examine / Profile 的合同进一步打通。

## 9. 一句话结论

DocGen 这轮已经完成了“边界重排 + 最小能力贯通”。
下一步应该做的是“在现有 graph 内继续加深质量”，而不是重新发明一套更复杂的 runtime 结构。