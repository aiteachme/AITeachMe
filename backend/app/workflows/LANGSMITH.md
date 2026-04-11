# LangSmith 团队接入速查

这份文档只回答一个核心问题：

`在 workflows 里写好的流程，到底用哪些函数方法可以轻松接入 LangSmith？`

答案非常简单，团队里只需要记住这 5 个入口。

## 先记住这 5 个入口

| 场景 | 应该用什么 |
| --- | --- |
| 整个 workflow 执行入口 | `run_state_graph(...)` |
| LangGraph 节点 | `@traced_digest_node(...)` / `@traced_workflow_node(...)` |
| 节点内部关键步骤 | `async with tracked_step(...)` |
| 独立工具 / retriever / service / adapter | `@traceable` |
| OpenAI SDK 客户端 | `wrap_openai(...)` |

如果一个同学只记住这张表，基本就够用了。

## 1. workflow 入口怎么接

整个 workflow 不需要手动再写 LangSmith span。  
统一从 [`run_state_graph`](d:/Project0GIT/aiteachme/AiTeachMe-main/backend/app/workflows/common/runtime.py) 进去就行。

```python
result = await run_state_graph(
    workflow_name="digest.planner",
    graph_builder=lambda: build_planner_graph(context=context),
    initial_state=initial_state,
    context=context,
)
```

这一步会自动创建最外层的 workflow trace。

团队约定：

- 不要在业务 workflow 里再手动开第二层 workflow span
- workflow 名要稳定，比如 `digest.planner`、`digest.docgen`

## 2. LangGraph 节点怎么接

节点一律用装饰器。

Digest 节点用 [`@traced_digest_node(...)`](d:/Project0GIT/aiteachme/AiTeachMe-main/backend/app/workflows/digest/observability.py)：

```python
@traced_digest_node(
    workflow_name=context.workflow_name,
    lane="planner",
    node_name="load_context",
)
async def load_context_node(state: BuildPlannerState) -> dict:
    ...
```

通用 workflow 节点用 [`@traced_workflow_node(...)`](d:/Project0GIT/aiteachme/AiTeachMe-main/backend/app/workflows/common/observability.py)：

```python
@traced_workflow_node(
    workflow="ingest.graph",
    lane="ingest",
    name="parse_files",
)
async def parse_files_node(state: dict) -> dict:
    ...
```

它们负责：

- 创建 node span
- 自动补 workflow / lane / node 元数据
- 记录少量白名单输入输出摘要
- 继承当前 workflow 的 LLM trace 上下文

团队约定：

- 一个 LangGraph 节点只包一层 node trace
- 节点名直接写业务动作，比如 `load_context`、`ground_concepts`
- 不要写 `step1`、`handler`、`main_process`

## 3. 节点内部关键步骤怎么接

节点里面如果还有关键步骤，不要为了 trace 再把 LangGraph 节点拆得很碎。  
直接用 [`tracked_step(...)`](d:/Project0GIT/aiteachme/AiTeachMe-main/backend/app/workflows/common/runtime_stats.py)。

```python
async with tracked_step(
    state,
    name="prepare_shared_inputs",
    kind="substep",
    trace_metadata={"file_count": len(state.get("file_ids", []))},
    trace_inputs={"user_goal_present": True},
) as step:
    shared_inputs = await prepare_shared_inputs(...)
    step.set_outputs(source_packet_count=len(shared_inputs.source_packets))
```

它会统一处理：

- substep trace
- runtime stats
- progress

也就是说，协作者一般不需要自己手写这些底层动作：

- `record_step_start(...)`
- `record_step_end(...)`
- `trace_substep(...)`
- `run.end(outputs=...)`

团队约定：

- 只有关键业务步骤才建 substep
- 一个 node 一般保留 3 到 6 个 substep
- `step.set_outputs(...)` 只放计数、状态、少量摘要，不放整段正文

## 4. 独立工具 / retriever / service 怎么接

这类场景直接按官方 examples 的思路来，用 `@traceable`。

```python
@traceable(name="digest.local_retrieval", run_type="retriever")
async def local_retrieval(query: str) -> list[dict]:
    ...
```

```python
@traceable(name="teaching.expand_example", run_type="tool")
async def expand_example(concept: str) -> str:
    ...
```

```python
class TracedSearchAdapter:
    def __init__(self, inner):
        self.inner = inner

    @traceable(name="search_adapter.search", run_type="tool")
    def search(self, query: str, limit: int = 3):
        return self.inner.search(query=query, limit=limit)
```

这类函数适合：

- retriever
- adapter
- 纯 service 方法
- 老接口的薄包装

## 5. 模型客户端怎么接

如果你在封装 OpenAI SDK，直接用 `wrap_openai(...)`，再在你的方法边界上加 `@traceable`。

```python
from langsmith import traceable
from langsmith.wrappers import wrap_openai


class TutorModelClient:
    def __init__(self):
        self.client = wrap_openai(openai.Client())

    @traceable(name="tutor_model_client.generate_answer", run_type="llm")
    def generate_answer(self, system_prompt: str, user_prompt: str) -> str:
        response = self.client.chat.completions.create(...)
        return response.choices[0].message.content or ""
```

这样 LangSmith 里既能看到你的业务方法，也能看到底层真实模型调用。

## 项目里的推荐分工

团队协作时，直接按下面的规则判断：

| 我要做的事 | 该用什么 |
| --- | --- |
| 新增一个 workflow 执行入口 | `run_state_graph(...)` |
| 新增一个 LangGraph 节点 | `@traced_digest_node(...)` / `@traced_workflow_node(...)` |
| 在节点内部新增一个关键业务步骤 | `async with tracked_step(...)` |
| 新增一个 retriever / tool / service | `@traceable` |
| 给 OpenAI 客户端加观测 | `wrap_openai(...)` + `@traceable` |

## 不建议业务代码直接碰的底层函数

普通协作者通常不要直接调用这些底层函数：

- `langsmith_trace(...)`
- `langsmith_tracing_scope(...)`
- `llm_trace_scope(...)`
- `trace_substep(...)`

原因不是它们不能用，而是：

- 这些是 infra 层的底层 primitive
- 日常扩展 workflow 时，直接用上面的 5 个入口更稳定
- 大家都走统一入口，LangSmith 图和代码风格才会一致

## 一张最短总结

```python
workflow 用 run_state_graph
node 用 @traced_digest_node / @traced_workflow_node
node 内关键步骤用 tracked_step
独立工具用 @traceable
OpenAI 客户端用 wrap_openai
```

如果后续有人问“我写的新流程怎么接 LangSmith”，就把这 5 句发给他。
