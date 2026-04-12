# LangSmith 接入说明

这份文档回答 3 个问题：

1. workflow 作者平时到底该用哪些统一入口
2. 为什么现在默认推荐“同一种注解 + 不同 run_type”
3. prompt、retriever、tool、llm 这些边界应该怎么分

## 先看结论

如果你喜欢 `11_litellm_tutor_app` 那种风格，这个仓库现在默认也推荐同一种注解思路：

```python
from app.workflows.common import (
    run_state_graph,
    traceable_run,
    wrap_traceable_run,
    tracked_step,
)
```

它们各自负责：

1. `run_state_graph(...)`
   workflow 根 span
2. `@traceable_run(...)`
   同一种注解，靠 `run_type` 区分 node / prompt / tool / retriever
3. `wrap_traceable_run(...)`
   工厂式节点接线
4. `async with tracked_step(...)`
   节点内部关键步骤

`node(...)`、`wrap_node(...)`、`prompt_traceable(...)` 还保留着，但现在更适合看作语义糖，不再是唯一推荐入口。

## 为什么不再强调很多不同注解

你指出的问题是对的。

之前把：

- `@node(...)`
- `@prompt_traceable(...)`
- `@workflow_node(...)`

分开写，虽然语义上清楚，但会让协作者误以为“不同对象必须学不同注解”，这和你给的官方示例风格不一致，也不利于上手。

所以现在我们把推荐心智模型改成：

`大多数时候只有一种注解：@traceable_run(...)`

区别只是 `run_type` 不同：

- node 用 `run_type="chain"`
- prompt builder 用 `run_type="prompt"`
- retriever 用 `run_type="retriever"`
- 普通小工具用 `run_type="tool"`

这更贴近 LangSmith 官方和你给的例子。

## 一张总表

| 你在写什么 | 推荐接口 | LangSmith run_type |
| --- | --- | --- |
| 整条 workflow | `run_state_graph` | `chain` |
| LangGraph node | `@traceable_run(..., run_type="chain")` | `chain` |
| 工厂式 node 接线 | `wrap_traceable_run(..., run_type="chain")` | `chain` |
| 稳定 prompt builder | `@traceable_run(..., run_type="prompt")` | `prompt` |
| 检索函数 / 检索步骤 | `@traceable_run(..., run_type="retriever")` 或 `tracked_step(..., trace_run_type="retriever")` | `retriever` |
| 普通工具步骤 | `tracked_step(..., trace_run_type="tool")` | `tool` |
| llm SDK / LLM 调用 | infra 统一封装 | `llm` |
| embedding 批处理 | `tracked_step(..., trace_run_type="embedding")` | `embedding` |
| parser / 结构化解析 | `tracked_step(..., trace_run_type="parser")` | `parser` |

## 1. workflow 根入口

整个 workflow 统一走 [`run_state_graph`](./common/runtime.py)：

```python
from app.workflows.common import run_state_graph


result = await run_state_graph(
    workflow_name="digest.planner",
    graph_builder=lambda: build_planner_graph(context=context),
    initial_state=initial_state,
    context=context,
)
```

这一步已经会自动创建 workflow 根 span。

团队约定：

- 不要在 workflow 入口手写 `langsmith_trace(...)`
- 不要自己再包第二层 workflow span
- `workflow_name` 直接用稳定业务语义，例如 `digest.planner`、`ingest.graph`

## 2. 同一种注解怎么覆盖 node 和 prompt

### node

```python
from app.workflows.common import traceable_run


@traceable_run(
    name="draft_plan",
    run_type="chain",
    workflow="digest.planner",
    lane="planner",
)
async def draft_plan_node(state):
    ...
```

### prompt builder

```python
from app.workflows.common import traceable_run


@traceable_run(
    name="digest.planner.build_prompt",
    run_type="prompt",
)
def build_planner_prompt(...):
    ...
```

你可以看到，注解本身是一种，差别只是：

- node 需要 `workflow/lane`
- prompt builder 不需要
- `run_type` 不同

## 3. 工厂式节点为什么还需要 wrapper

这个不是因为 LangSmith 要多一种接口，而是因为 Python 语法限制。

如果节点是这种形式：

```python
def build_xxx_node(context):
    async def xxx_node(state):
        ...
    return xxx_node
```

那就没法直接在定义处写装饰器，所以只能在 graph 接线处包一层：

```python
from app.workflows.common import wrap_traceable_run


workflow.add_node(
    "targeted_research",
    wrap_traceable_run(
        build_targeted_research_node(context=context),
        name="targeted_research",
        run_type="chain",
        workflow=context.workflow_name,
        lane="docgen",
    ),
)
```

所以这里的区别不是“LangSmith 有两套注解”，而是：

- 能写装饰器时，用 `@traceable_run(...)`
- 不能写装饰器时，用 `wrap_traceable_run(...)`

## 4. tracked_step 到底还保留干嘛

[`tracked_step`](./TRACKED_STEP.md) 不是另一套 decorator 体系，它解决的是另一个问题：

`node 内部关键步骤怎么统一记 runtime stats + progress + LangSmith substep`

例如：

```python
from app.workflows.common import tracked_step


async with tracked_step(
    state,
    name="plan_prompt_build",
    kind="substep",
    trace_run_type="prompt",
) as step:
    prompt = build_planner_prompt(...)
    step.set_outputs(prompt_chars=len(prompt))
```

这里它不是替代 `@traceable_run(...)`，而是在 node 内继续往下切子边界。

## 5. 为什么我们不能只像 demo 一样全靠一个 `@traceable`

你给的 demo 很清楚，也确实值得对齐。  
但它比我们这个项目简单很多，少了 3 类需求：

1. LangGraph node 里要从 `state` 自动提取白名单输入输出摘要
2. node 执行时要自动继承 workflow 的 `subject / build_session_id / lane`
3. node 内部还要同时驱动 runtime stats 和前端 progress

所以我们不能原封不动只暴露 LangSmith 原生 `@traceable`，否则：

- 每个 workflow 作者都要自己写状态摘要逻辑
- 每个 node 都要自己补 `workflow/lane/session` 元信息
- 风格很快会重新分叉

现在的做法是折中：

- 对协作者暴露成“同一种注解”心智模型
- 但底层仍保留 repo 自己的 stateful node wrapper

也就是说，外面看起来像 demo，里面仍然保留我们项目需要的约束和自动注入。

## 6. prompt tracing 现在是默认要求

这个项目里，prompt tracing 不是“可选增强”，而是默认要求。

我们现在默认分两类：

### 稳定 prompt builder

直接用：

```python
@traceable_run(
    name="digest.docgen.writer_prompt",
    run_type="prompt",
)
def build_docgen_writer_messages(...):
    ...
```

### node 里的临时 prompt build 步骤

直接用：

```python
async with tracked_step(
    state,
    name="writer_prompt_build",
    kind="substep",
    trace_run_type="prompt",
) as step:
    messages = build_docgen_writer_messages(...)
    step.set_outputs(message_count=len(messages))
```

这样 LangSmith 里会同时看到：

- 这个 node 里发生了 prompt build
- 具体是哪个 prompt builder 产出的 prompt

## 7. LangSmith run_type 我们怎么约定

目前团队统一按 LangSmith 官方常见 run type 来写：

- `chain`
- `tool`
- `llm`
- `retriever`
- `embedding`
- `prompt`
- `parser`

在这个仓库里：

- workflow / node 默认是 `chain`
- prompt builder 默认是 `prompt`
- `tracked_step` 默认是 `tool`
- prompt / retriever / embedding / parser 这些步骤应该显式改掉默认值

## 8. 四个完整例子

### 例子 A：planner node

```python
from app.workflows.common import traceable_run


@traceable_run(
    name="draft_plan",
    run_type="chain",
    workflow="digest.planner",
    lane="planner",
)
async def draft_plan_node(state):
    return {"plan": plan}
```

### 例子 B：工厂式 node 接线

```python
from app.workflows.common import wrap_traceable_run


workflow.add_node(
    "targeted_research",
    wrap_traceable_run(
        build_targeted_research_node(context=context),
        name="targeted_research",
        run_type="chain",
        workflow=context.workflow_name,
        lane="docgen",
    ),
)
```

### 例子 C：prompt builder

```python
from app.workflows.common import traceable_run


@traceable_run(
    name="digest.planner.build_prompt",
    run_type="prompt",
)
def build_planner_prompt(...):
    ...
```

### 例子 D：node 内 retrieval step

```python
from app.workflows.common import tracked_step


async with tracked_step(
    None,
    name="web_retrieval",
    kind="substep",
    trace_run_type="retriever",
    trace_inputs={"query_count": len(queries)},
) as step:
    hits = await search(...)
    step.set_outputs(result_count=len(hits))
```

## 9. 旧名字现在怎么看

这些名字还保留着：

- `node(...)`
- `wrap_node(...)`
- `workflow_node(...)`
- `wrap_workflow_node(...)`
- `prompt_traceable(...)`
- `digest_node(...)`
- `wrap_digest_node(...)`

但现在推荐这样理解：

- `traceable_run / wrap_traceable_run` 是统一入口
- `node / wrap_node / workflow_node / wrap_workflow_node` 是偏 node 语义的别名
- `prompt_traceable` 是偏 prompt 语义的别名
- `digest_node / wrap_digest_node` 只是历史兼容层

## 10. 一句话记忆版

```python
workflow 用 run_state_graph
函数默认优先用 @traceable_run
工厂式函数用 wrap_traceable_run
node 内关键步骤用 tracked_step
run_type 用来区分 prompt / retriever / tool / parser / embedding / llm
```
