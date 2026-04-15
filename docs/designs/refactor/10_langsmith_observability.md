# LangSmith 可观测性

> 最后更新：2026-04-15

这份文档只保留当前收口后的核心原则，不再混讲 track / step / progress。

## 收口目标

全仓观测层只保留两层语义：

- `LangSmith trace`
  给研发排障
- `progress`
  给前端展示

它们是两套不同的消费者，不再共享同一套 step 生命周期。

## 代码分层

### Trace

- 底层实现：`backend/app/shared/infra/observability/trace.py`
- workflow 公开入口：
  - `run_state_graph(...)`
  - `invoke_state_graph(...)`
  - `workflow_tracer(...).node(handler, ...)`
  - 官方 `@traceable`

### Progress

- 最小 helper：`backend/app/shared/infra/workflow/progress.py`
- 公开入口：`emit_progress(...)`

## 当前固定规范

### 1. workflow root

用 `run_state_graph(...)` / `invoke_state_graph(...)`

### 2. workflow node

用 `workflow_tracer(...).node(handler, ...)`

### 3. prompt / helper

直接用官方 `@traceable`

### 4. 前端进度

只用 `emit_progress(...)`

## 不再作为公开规范的能力

下面这些不再属于 workflow 作者入口：

- `traceable_run`
- `tracked_step`
- `record_step_start`
- `record_step_end`
- `runtime_steps`
- `annotate_traceable`

下面这些仍可留在 infra，但不再对 workflow 作者公开：

- `traceable_with_context`
- `llm_trace_scope`
- `langsmith_trace`
- `trace_substep`
- `build_langsmith_extra`

## 为什么这么做

因为 LangSmith / LangGraph 原生已经负责：

- trace 树层级
- root / node 时间
- span 嵌套结构
- trace 诊断可视化

仓库如果再维护第二套本地 trace 生命周期，只会带来：

- 重复 node span
- 本地 trace / LangSmith trace 不一致
- workflow 作者需要记更多概念

## planner 的兼容策略

planner 当前仍保留 `runtime_stats`，但只作为兼容摘要：

- `elapsed_ms`
- `generation_mode`
- `steps`

其中 `steps` 只允许是顶层 node 摘要：

- `load_context`
- `ground_concepts`
- `draft_plan`

这不是 tracing 系统，只是给前端展示最多 3 个顶层节点耗时。

## 相关文档

- `backend/app/workflows/LANGSMITH.md`
- `backend/app/workflows/PROGRESS.md`
- `backend/app/workflows/README.md`
