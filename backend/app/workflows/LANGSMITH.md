# LangSmith 接入说明

这份文档只回答一个问题:

`在 AiTeachMe 里，我写的新节点、新工具、新模型调用，到底该怎么接入 LangSmith？`

如果你之前看官方 examples 觉得很清楚，那是对的。  
这份文档现在也按那个思路来写: 先告诉你“什么时候用哪一种”，再给最小例子。

## 先记住 3 句话

在这个项目里，99% 的 LangSmith 接入只分成 3 类：

1. 我在写一个 LangGraph 节点  
   用 `@traced_digest_node(...)` 或 `@traced_workflow_node(...)`
2. 我在节点里面拆一个关键步骤  
   用 `async with tracked_step(...)`
3. 我在写独立工具、检索器、service、adapter  
   用 `@traceable`

如果只看这一页，先把这 3 句记住就够了。

## 和 examples 的对应关系

你提到的 examples 之所以清楚，是因为它们每个文件都只回答一个问题。  
我们项目里也可以这样对应去理解：

| examples 里的思路 | 在我们项目里的对应做法 | 什么时候用 |
| --- | --- | --- |
| `03_langgraph_manual_traceable.py` | `@traced_digest_node(...)` / `@traced_workflow_node(...)` | 你在写 LangGraph 节点 |
| `08_custom_retriever_traceable.py` | `@traceable(run_type="retriever")` | 你在写检索器 |
| `09_custom_wrapper_adapter.py` | `@traceable` 包 adapter 方法 | 你不想改老接口，只想加 trace |
| `10_custom_wrapper_with_openai.py` | `wrap_openai(...)` + `@traceable` | 你在封装模型客户端 |
| 官方 context / wrapper 思路 | `async with tracked_step(...)` | 你要在节点内部补关键步骤 |

最重要的一点是：

- 官方 examples 解决的是“怎么给函数加 trace”
- 我们项目除了 trace，还要同时保留 workflow/node/substep 结构、progress、runtime stats

所以我们不是照抄一个 `@traceable` 到所有地方，而是做了项目内的 3 个固定入口。

## 场景 1: 我在写 LangGraph 节点

这是最常见的情况。

### 应该怎么写

直接给节点函数加装饰器：

```python
@traced_digest_node(
    workflow_name=context.workflow_name,
    lane="planner",
    node_name="load_context",
)
async def load_context_node(state: BuildPlannerState) -> dict:
    ...
```

或者非 digest workflow：

```python
@traced_workflow_node(
    workflow="ingest.graph",
    lane="ingest",
    name="parse_files",
)
async def parse_files_node(state: dict) -> dict:
    ...
```

### 这相当于 examples 里的什么

它相当于 examples 里“给函数加 `@traceable`”，但是是我们项目自己的 LangGraph 版本。

为什么不能直接全都写成裸 `@traceable`？

因为我们这里还需要自动补这些信息：

- workflow 名
- lane 名
- node 名
- 白名单输入摘要
- 白名单输出摘要
- Ambient LLM trace context

所以你可以把 `@traced_digest_node(...)` 理解成：

`AiTeachMe 版、专门给 LangGraph 节点用的 @traceable`

### 命名建议

- 好名字: `load_context`、`ground_concepts`、`draft_plan`
- 不好名字: `step1`、`main_handler`、`process_data`

节点名要让人在 LangSmith 图里一眼知道业务动作。

## 场景 2: 我在节点内部拆关键步骤

这是第二常见的情况。

比如一个 node 里面要分成：

- 读资料
- 检索概念
- 组 prompt
- 流式生成
- fallback

这时候不要为了 trace 再把 LangGraph 节点拆得很碎，直接在 node 内部用 `tracked_step(...)`。

### 应该怎么写

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

### 这东西到底帮你做了什么

它把下面几件事收口成一个入口了：

- 记 runtime step 开始
- 记 runtime step 结束
- 必要时发 progress
- 创建一个 LangSmith substep span
- 把少量输出摘要挂到这个 span 上

所以你现在不需要自己手写：

- `record_step_start(...)`
- `record_step_end(...)`
- `with trace_substep(...)`
- `run.end(outputs=...)`

### 什么时候该建 substep

只给“业务上能说清楚”的关键步骤建 substep。

比如这些就很好：

- `prepare_shared_inputs`
- `concept_grounding`
- `local_retrieval`
- `web_retrieval`
- `plan_prompt_build`
- `planner_stream_generate`
- `planner_fallback_build`

不要建这种名字：

- `do_work`
- `inner_call`
- `temp_step`
- `part2`

### 一个 node 里建议几个 substep

一般 3 到 6 个最合适。  
太少看不出问题卡在哪，太多 LangSmith 图会炸开。

## 场景 3: 我在写独立工具 / 检索器 / service / adapter

这种场景最接近你看到的官方 examples。

### 应该怎么写

检索器：

```python
@traceable(name="digest.local_retrieval", run_type="retriever")
async def local_retrieval(query: str) -> list[dict]:
    ...
```

普通工具：

```python
@traceable(name="teaching.expand_example", run_type="tool")
async def expand_example(concept: str) -> str:
    ...
```

adapter：

```python
class TracedSearchAdapter:
    def __init__(self, inner):
        self.inner = inner

    @traceable(name="search_adapter.search", run_type="tool")
    def search(self, query: str, limit: int = 3):
        return self.inner.search(query=query, limit=limit)
```

### 这对应 examples 的什么

- 检索器场景，对应 `08_custom_retriever_traceable.py`
- adapter 场景，对应 `09_custom_wrapper_adapter.py`
- 模型客户端场景，对应 `10_custom_wrapper_with_openai.py`

如果你写的是这类“独立边界”，那就直接按 examples 的思路来，没问题。

## 场景 4: 我在封装模型客户端

如果你在项目里封自己的模型客户端，推荐做法和 examples 基本一致：

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

这里的重点是：

- OpenAI SDK 用 `wrap_openai(...)`
- 你自己的方法边界用 `@traceable`

这样 LangSmith 里既能看到你的业务方法，也能看到底层 LLM 调用。

## 一张图看懂项目里的层级

拿 planner 举例，LangSmith 里理想上看到的是这棵树：

```text
digest.planner
└─ planner.load_context
   └─ prepare_shared_inputs

digest.planner
└─ planner.ground_concepts
   ├─ concept_grounding
   ├─ local_retrieval
   └─ web_retrieval

digest.planner
└─ planner.draft_plan
   ├─ plan_prompt_build
   ├─ planner_stream_generate
   │  └─ ChatCompletion
   └─ planner_fallback_build
```

你可以直接这样理解：

- 最外层 `digest.planner`
  这是 workflow run
- `planner.load_context`
  这是 node
- `prepare_shared_inputs`
  这是 node 内的关键步骤
- `ChatCompletion`
  这是底层真实模型调用

## API 的 `steps` 和 LangSmith trace 不是一回事

这个点很容易让人绕进去，所以单独说一下。

LangSmith 里看到的是一棵 trace 树：

- workflow
- node
- substep
- llm

前端和接口里拿到的是一个简化步骤列表：

```json
[
  { "name": "prepare_shared_inputs", "kind": "substep", "status": "ok", "elapsed_ms": 42 },
  { "name": "load_context", "kind": "node", "status": "ok", "elapsed_ms": 51 }
]
```

它们的关系是：

- LangSmith trace 树: 给开发者调试流程结构
- `runtime_stats.steps`: 给前端和接口展示简洁摘要

所以不要期待 API 返回一整棵和 LangSmith 一样的树。

## 以后协同开发时，直接按这张表抄

| 我要做的事 | 该用什么 |
| --- | --- |
| 新增一个 LangGraph 节点 | `@traced_digest_node(...)` / `@traced_workflow_node(...)` |
| 在节点内部新增一个关键业务步骤 | `async with tracked_step(...)` |
| 写独立 retriever / tool / service | `@traceable` |
| 包 OpenAI SDK 客户端 | `wrap_openai(...)` + `@traceable` |
| 给旧接口加 trace，但不改调用方 | adapter 类 + `@traceable` |

如果一个同学只看这一张表，基本就能开始接了。

## 命名约定

- workflow: `digest.planner`
- lane: `planner`
- node: `load_context`、`ground_concepts`、`draft_plan`
- substep: `prepare_shared_inputs`、`plan_prompt_build`、`local_retrieval`
- tool/service: `digest.local_retrieval`、`teaching.expand_example`

一句话：

- node / substep 用短动宾结构
- tool / service 用带命名空间的点号形式

## 对应代码位置

- 节点装饰器: [`observability.py`](d:/Project0GIT/aiteachme/AiTeachMe-main/backend/app/workflows/common/observability.py)
- 统一步骤入口: [`runtime_stats.py`](d:/Project0GIT/aiteachme/AiTeachMe-main/backend/app/workflows/common/runtime_stats.py)
- workflow 入口: [`runtime.py`](d:/Project0GIT/aiteachme/AiTeachMe-main/backend/app/workflows/common/runtime.py)
- planner 示例: [`graph.py`](d:/Project0GIT/aiteachme/AiTeachMe-main/backend/app/workflows/digest/planner/graph.py)
- planner 检索步骤示例: [`concept_grounding.py`](d:/Project0GIT/aiteachme/AiTeachMe-main/backend/app/workflows/digest/planner/concept_grounding.py)

## 最后一句

现在这套约定，不是想把 LangSmith 搞复杂，反而是想把团队协作时真正会遇到的 3 类场景固定下来：

- 节点怎么接
- 节点里的步骤怎么接
- 独立工具怎么接

只要按这 3 类写，后面别人接手时一眼就能看懂。
