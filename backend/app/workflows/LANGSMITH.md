# LangSmith 规范

这份文档只回答一件事：

`app/workflows/**` 里应该如何接 LangSmith，并且不要重复实现 LangSmith / LangGraph 已经原生提供的职责。

## 一句话原则

- LangSmith 是唯一的研发排障 trace 真相源
- 前端进度只走 `progress`，不要再维护第二套本地 trace 生命周期
- LangGraph 负责 root / node 层级和基础耗时记录，我们只补业务上下文

## workflow 作者只需要记住的入口

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

## 允许的 trace 分层

### 1. workflow root

```python
result = await run_state_graph(
    workflow_name="digest.planner",
    graph_builder=lambda: build_planner_graph(context=context),
    initial_state=initial_state,
    context=context,
)
```

职责：

- 构建 LangGraph invoke config
- 把 workflow metadata / tags 传给 LangGraph / LangSmith
- 提供统一 root 入口

不要做的事：

- 不要再手工包第二个 root span
- 不要在 workflow 里再维护自定义 root timing 生命周期

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

职责：

- 给 node 补 metadata / tags / ambient trace context
- 在需要时把顶层节点耗时写回 state，例如 `load_ms`

不要误解：

- `workflow_tracer().node(...)` 不是第二套 tracing 框架
- 它不会再人为创建重复的 node span
- LangSmith / LangGraph 原生已经会记录 node 层级和执行时间

`timing_field` 的定位也要收敛理解：

- 它只是把少量顶层节点耗时回填到 state，便于接口兼容或前端摘要展示
- 它不是为了替代 LangSmith 里的真实 timing
- 一般只给少数顶层 node 用，不要滥用到每个 helper

### 3. prompt / helper

```python
from langsmith import traceable

@traceable(name="digest.planner.build_prompt", run_type="prompt")
def build_planner_prompt(...):
    ...
```

职责：

- 给 prompt helper、query batch、research round 这类局部逻辑补一个清晰子层
- 让 LangSmith trace 结构更容易读

推荐用法：

- prompt builder
- 小范围的 helper 聚合逻辑
- 一个顶层 node 下确实值得单独观察的子任务

不推荐：

- 为了“看起来完整”给每个小函数都加 `@traceable`
- 把 helper tracing 变成 workflow 内部的第二套 step 体系

## 什么时候应该增加子 span

只有在下面这类情况，才值得额外提 helper 并加官方 `@traceable`：

- 一个 node 里有明显的多轮检索 / 多轮生成聚合
- LangSmith 里当前结构过平，读起来很乱
- 你真的需要把某个子阶段单独拿出来排障

典型例子：

- planner concept grounding 的 query batch
- docgen chapter context 的 research round

如果只是普通的小函数，不值得单独 trace。

## `app/workflows/**` 里不要再做的事

下面这些已经不属于 workflow 作者规范：

- `traceable_run`
- `tracked_step`
- `annotate_traceable`
- `build_langsmith_extra`
- `trace_substep`
- 手写 `langsmith_trace(...)`
- 手写 `tracing_context(...)`
- 直接在 workflow 里调用 `llm_trace_scope(...)`

原因很简单：

- 它们要么重复 LangSmith 原生职责
- 要么会把 workflow 层重新带回“第二套本地 trace 框架”

## infra-private 边界

下面这些能力仍可保留，但它们不属于 workflow 作者公开入口：

- `traceable_with_context`
  仅给 `tool / retriever / reader / execution` 这类共享 I/O 边界使用
- `llm_trace_scope`
  仅给共享 runtime / 服务编排桥接使用
- `langsmith_trace`
  仅给底层 LLM helper 等少数非-LangGraph 场景使用

如果你在 `app/workflows/**` 新代码里想直接调用这些能力，通常说明分层已经跑偏。

## 为什么这样更简洁

因为 LangSmith / LangGraph 原生已经负责：

- span 层级
- trace 树结构
- node 可视化
- 执行耗时

我们仓库只补三类信息：

- 业务 metadata
- 业务 tags
- 共享 I/O 边界上的少量辅助 span

这可以避免两类老问题：

1. 重复 node span
2. 本地维护第二套 runtime trace 生命周期

## 推荐心智模型

```text
workflow root   -> run_state_graph / invoke_state_graph
workflow node   -> workflow_tracer().node(handler, ...)
prompt/helper   -> 官方 @traceable
infra I/O 边界 -> infra 内部按需保留 traceable_with_context / langsmith_trace
frontend 进度   -> 看 PROGRESS.md，不属于 LangSmith 规范
```

## 一句话结论

workflow 层要做的是“把业务上下文接给 LangSmith”，不是“再造一套 LangSmith”。
