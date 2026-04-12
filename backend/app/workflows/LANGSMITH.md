# LangSmith 接入说明

这份文档只回答一件事：

如何让 `workflows/` 里的 LangSmith 追踪足够简单，后续改动时不需要在大量节点和 infra helper 之间来回同步。

## 当前结论

现在默认采用两层策略：

1. workflow 层统一绑定 tracing
2. infra 层只保留少数共享边界的 trace

对应到代码里，workflow 作者平时只需要记住 4 个入口：

```python
from app.workflows.common import run_state_graph, workflow_tracer, traceable_run, tracked_step
```

推荐分工：

- `run_state_graph(...)`
  workflow 根 span
- `trace = workflow_tracer(...); trace.node(...)`
  workflow node 的统一入口
- `@traceable_run(..., run_type="prompt" | "retriever" | "tool" | ...)`
  稳定的 prompt / helper / retriever 函数
- `async with tracked_step(...)`
  node 内部关键子步骤

旧的 workflow tracing 兼容别名已经移除；
新 graph 文件默认直接写 `workflow_tracer(...).node(...)`。

## 为什么默认不去 infra 层逐个加注解

你担心的是对的。

如果把 LangSmith 主要接入点放在 infra 层大量 helper 上，会有 4 个明显问题：

1. 工具很多，分布太散，后续一改 trace 规范就要到处改。
2. workflow 级业务 ID 很难保持一致，容易出现 `subject / build_session_id / lane / node` 漏传。
3. 同一个业务节点的 trace 会碎成很多层，图越来越难看。
4. 新同学容易误以为“每个 helper 都必须自己埋 LangSmith”，维护成本会持续升高。

所以现在的默认策略是：

- workflow node 负责把业务上下文绑定进去
- infra 里的共享执行器只负责复用这份上下文
- 真正值得单独展示的共享边界，再在 infra 层保留 trace

换句话说：

`LangSmith 的主入口在 workflows，不在 infra。`

## 这套策略为什么可行

`workflow_tracer(...).node(...)` 最终会在 node 执行时统一做两件事：

1. 创建 node span
2. 进入 `llm_trace_scope(...)`

而 infra 层现有这些共享入口，本来就会读取 ambient trace context：

- LLM 调用包装
- Tool registry
- Search retriever / reader
- `traced_execution` 这类长运行单元

所以链路变成：

```text
workflow root
-> workflow node
   -> tracked_step substep
   -> infra llm/tool/retriever/reader trace
```

这正好满足“workflow 层统一收口，infra 层自动继承”的目标。

## 一张总表

| 你在写什么 | 推荐接口 | 备注 |
| --- | --- | --- |
| 整条 workflow | `run_state_graph(...)` | workflow 根 span |
| graph 里的 node 接线 | `trace = workflow_tracer(...); trace.node(...)` | 默认写法 |
| 工厂函数里返回的 node | `@trace.node(...)` | 适合 `build_xxx_node(...)` 这种模式 |
| 稳定 prompt builder | `@traceable_run(..., run_type="prompt")` | 不需要每次手传 workflow/lane |
| 稳定 retriever / helper | `@traceable_run(..., run_type="retriever" / "tool")` | 只给真正稳定边界 |
| node 内关键步骤 | `tracked_step(...)` | 同时服务 runtime stats / progress / subspan |
| LLM SDK / Tool registry / Reader | infra 现有 trace | 继续复用 ambient context |

## 最推荐的写法

### 1. graph 接线

```python
from app.workflows.common import workflow_tracer


def build_docgen_graph(*, context: WorkflowContext) -> StateGraph:
    workflow = StateGraph(DocGenState)
    trace = workflow_tracer(context=context, lane="docgen")

    workflow.add_node(
        "load_context",
        trace.node(
            build_load_context_node(context=context),
            name="load_context",
            timing_field="load_ms",
        ),
    )
    workflow.add_node(
        "finalize_assemble",
        trace.node(
            build_finalize_assemble_node(context=context),
            name="finalize_assemble",
        ),
    )
    return workflow
```

这里最重要的变化是：

- `workflow` 和 `lane` 只绑定一次
- 后面每个 node 只写 `name` 和少量差异化参数
- 后续 trace 策略要改，只需要改公共封装

### 2. 工厂函数里的 node decorator

```python
from app.workflows.common import workflow_tracer


def build_load_context_node(*, context: WorkflowContext):
    trace = workflow_tracer(context=context, lane="planner")

    @trace.node(
        name="load_context",
        output_keys=("digest_mode", "course_type", "retrieval_profile"),
    )
    async def load_context_node(state):
        ...

    return load_context_node
```

这个写法最接近你想要的“一个注解就够了”。

注意：

- 这里依然是 workflow 层统一处理 tracing
- 不需要去 infra helper 上重复补 decorator

### 3. prompt builder

```python
from app.workflows.common import traceable_run


@traceable_run(name="digest.docgen.writer_prompt", run_type="prompt")
def build_writer_messages(*, subject: str, tone: str) -> list[dict]:
    ...
```

这里不推荐再额外塞 `workflow/lane`，原因是：

- prompt builder 通常运行在 node 内
- node span 已经进入了统一上下文
- 让 prompt builder 保持“薄而稳定”更容易复用

### 4. node 内关键步骤

```python
from app.workflows.common import tracked_step


async with tracked_step(
    state,
    name="web_retrieval",
    kind="substep",
    trace_run_type="retriever",
    trace_inputs={"query_count": len(queries)},
) as step:
    hits = await search_web(queries)
    step.set_outputs(result_count=len(hits))
```

`tracked_step(...)` 的意义没有变：

- runtime step 计时
- 前端 progress 事件
- LangSmith 子 span

## infra 层到底保留哪些 trace

默认只保留这几类共享边界：

1. LLM 调用包装
2. Tool registry / tool execute
3. retriever / reader 这类共享 IO 边界
4. `BaseTracedExecution` 这类长运行共享执行单元

原因是这几类边界天然具有复用价值，也适合被跨 workflow 比较。

补充一条当前已经固定下来的约束：

- runtime cache 的观测也跟着这些共享边界走
- retriever / reader / `BaseTracedExecution` 直接输出 `cache_status / cache_hit`
- 不再为了 cache 去给 `shared/infra/search/cache.py` 里的内部 helper 单独加 decorator

除此之外，普通 infra helper 默认不要为了 LangSmith 再单独加一层 decorator。

## 什么时候才应该在 infra 层新增 trace

只有满足下面至少一条时，才考虑在 infra 层新增：

- 这是跨 workflow 复用的稳定边界
- 单独排障价值很高
- 脱离当前 workflow 仍然值得独立观察
- 它本身就是“执行器”，不是一个零散 helper

反过来，以下情况不要新增：

- 只是某个 workflow 内部临时辅助函数
- 只是为了“图上更热闹”
- 只是在已有 node span 下面多切一层没有实际诊断价值的包装

## legacy 清理

旧的 workflow tracing 兼容别名已经移除。

现在默认只保留这套最小入口：

- `run_state_graph(...)`
- `workflow_tracer(...).node(...)`
- `@traceable_run(...)`
- `tracked_step(...)`

这样做的目的只有一个：

`减少噪声，避免后续改动时被多套旧名字干扰。`

## 迁移纪律

以后新增或重构 workflow tracing 时，按下面的顺序判断：

1. 这是 workflow root 吗？
   用 `run_state_graph(...)`
2. 这是 graph node 吗？
   先写 `trace = workflow_tracer(...)`，再用 `trace.node(...)`
3. 这是稳定 prompt / helper 吗？
   用 `@traceable_run(...)`
4. 这是 node 内关键步骤吗？
   用 `tracked_step(...)`
5. 这是 infra 共享执行边界吗？
   才考虑在 infra 层保留或新增 trace

如果你在做的是缓存、重试、fallback 之类的横切能力，也先问自己：

- 这是不是已经可以挂在现有共享边界 outputs 上？

如果答案是是，就优先扩展已有 span 的 metadata，而不是再新开一层 trace。

## 一句话版本

```python
workflow root 用 run_state_graph
workflow node 默认先 workflow_tracer(...)
prompt / helper 用 @traceable_run
node 内关键步骤用 tracked_step
infra 只保留少数共享边界 trace，不再逐个 helper 扩散
```
