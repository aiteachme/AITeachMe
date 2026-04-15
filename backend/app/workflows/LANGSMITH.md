# LangSmith 规范

这份文档只回答一件事：

`app/workflows/**` 里应该如何接 LangSmith，且不要重复实现 LangSmith 已经原生提供的职责。

## 一句话原则

- LangSmith 是唯一的研发排障 trace 真相源。
- 前端展示进度只走 `progress`，不要再维护第二套本地 trace 生命周期。
- LangGraph 负责 root / node 层级；我们只补上下文，不再手工再包一层 node span。

## Workflow 作者只需要记住 3 个入口

```python
from app.shared.infra.workflow import (
    invoke_state_graph,
    run_state_graph,
    workflow_tracer,
)
from langsmith import traceable
```

对应规则：

1. workflow root
   用 `run_state_graph(...)` 或 `invoke_state_graph(...)`
2. graph node 接线
   用 `workflow_tracer(...).node(handler, name=..., timing_field=...)`
3. prompt / helper
   直接用官方 `@traceable`

## 现在允许的 trace 分层

### 1. workflow root

```python
result = await run_state_graph(
    workflow_name="digest.planner",
    graph_builder=lambda: build_planner_graph(context=context),
    initial_state=initial_state,
    context=context,
)
```

- 负责构建 LangGraph invoke config
- 通过 `config.metadata/tags` 把业务上下文传给 LangGraph / LangSmith
- 不手工创建第二个 root span

### 2. workflow node

```python
trace = workflow_tracer(context=context, lane="planner")

workflow.add_node(
    "load_context",
    trace.node(
        build_load_context_node(context=context),
        name="load_context",
        timing_field="load_ms",
    ),
)
```

- 这是 workflow node 的唯一规范接线方式
- 只保留 handler 形式，不再使用 `@trace.node(...)`
- 作用是补 metadata / tags / ambient trace context
- 不手工创建第二个 node span

### 3. prompt / helper

```python
from langsmith import traceable

@traceable(name="digest.planner.build_prompt", run_type="prompt")
def build_planner_prompt(...):
    ...
```

- prompt helper 一律直接用官方 `@traceable`
- 不再使用 `traceable_run`
- 如果将来需要额外子 span，优先把逻辑提成 helper，再用官方 `@traceable`

## app/workflows 里不要再做的事

下面这些不再属于 workflow 作者规范：

- `traceable_run`
- `tracked_step`
- `annotate_traceable`
- `build_langsmith_extra`
- `trace_substep`
- 直接手写 `langsmith_trace(...)`
- 直接手写 `tracing_context(...)`
- 直接调用 `llm_trace_scope(...)`

说明：

- `llm_trace_scope`、`traceable_with_context` 这些能力仍然存在，但属于 infra-private 或底层桥接能力。
- 它们可以留在 `shared/infra/**` 或少量服务编排层，不再是 `app/workflows/**` 的公开写法。

## 为什么这样更简洁

因为 LangSmith / LangGraph 原生已经负责：

- span 层级
- 执行时间
- trace 树结构
- node 层级可视化

我们仓库只补三类信息：

- 业务 metadata
- 业务 tags
- 共享 I/O 边界上的少量自定义 span

这能避免两类历史问题：

1. 重复 node span
2. 本地维护第二套 runtime trace 生命周期

## infra-private 边界

下面这些能力仍可保留，但不属于 workflow 作者入口：

- `traceable_with_context`
  仅给 `tool / retriever / reader / execution` 这些共享 I/O 边界使用
- `llm_trace_scope`
  仅给共享 runtime / 服务编排桥接使用
- `langsmith_trace`
  仅给底层 LLM helper 等少数非-LangGraph 场景使用

如果你在 `app/workflows/**` 新代码里想用这些能力，通常说明分层已经跑偏了。

## 推荐心智模型

```text
workflow root   -> run_state_graph / invoke_state_graph
workflow node   -> workflow_tracer().node(handler, ...)
prompt/helper   -> @traceable
infra I/O 边界 -> infra 内部按需保留 traceable_with_context / langsmith_trace
frontend 进度   -> 看 PROGRESS.md，不属于 LangSmith 规范
```
