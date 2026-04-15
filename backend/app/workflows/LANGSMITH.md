# LangSmith 规范

这份文档只回答一件事：`app/workflows/**` 应该怎么接 LangSmith。

## 一句话原则

- LangSmith 是研发排障的唯一 trace 真相源
- progress 只给前端展示，不是第二套 trace
- LangGraph 已经负责 root / node span，我们只补上下文

## Workflow 作者只需要记住 3 个入口

```python
from app.shared.infra.workflow import (
    invoke_state_graph,
    run_state_graph,
    workflow_tracer,
)
from langsmith import traceable
```

对应关系：

1. workflow root
   用 `run_state_graph(...)` 或 `invoke_state_graph(...)`
2. graph node
   用 `workflow_tracer(...).node(handler, ...)`
3. prompt / helper
   直接用官方 `@traceable`

## 标准写法

### workflow root

```python
result = await run_state_graph(
    workflow_name="digest.planner",
    graph_builder=lambda: build_planner_graph(context=context),
    initial_state=initial_state,
    context=context,
)
```

### workflow node

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

### prompt / helper

```python
@traceable(name="digest.planner.build_prompt", run_type="prompt")
def build_planner_prompt(...):
    ...
```

## 不要再做的事

下面这些不再是 `workflows` 作者的公开写法：

- `traceable_run`
- `tracked_step`
- `annotate_traceable`
- `build_langsmith_extra`
- `trace_substep`
- 直接手写 `langsmith_trace(...)`
- 直接手写 `tracing_context(...)`
- 直接调用 `llm_trace_scope(...)`

这些能力如果还需要，应该留在 `shared/infra/**` 的 infra-private 边界。

## 推荐心智模型

```text
workflow root   -> run_state_graph / invoke_state_graph
workflow node   -> workflow_tracer().node(handler, ...)
prompt/helper   -> @traceable
frontend 进度   -> 看 PROGRESS.md
```

