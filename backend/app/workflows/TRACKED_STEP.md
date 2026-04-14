# tracked_step 规范

这份文档只讲一件事：

`tracked_step(...)` 在 workflow 里应该怎么用，尤其是 kind 和 LangSmith run_type 到底怎么区分。

## 一句话定义

`tracked_step(...)` 是 workflow 作者写“节点内部关键边界”的统一接口。

它同时负责：

1. runtime step 计时
2. 前端 progress 事件
3. LangSmith 子 span

## 最常见写法

```python
from app.shared.infra.workflow import tracked_step


async with tracked_step(
    state,
    name="prepare_shared_inputs",
    kind="substep",
    phase="planner",
    running_message="正在读取资料...",
    completed_message="资料读取完成。",
) as step:
    shared_inputs = await prepare_shared_inputs(...)
    step.set_outputs(source_packet_count=len(shared_inputs.source_packets))
```

## 1. `kind` 和 `trace_run_type` 不是一回事

### `kind`

`kind` 是项目内部 runtime stats 的分类。

当前支持：

- `node`
- `tool`
- `substep`
- `llm`

它主要影响：

- `runtime_steps` 里怎么记
- 前端构建态怎么看步骤

### `trace_run_type`

`trace_run_type` 是 LangSmith 的 run 类型。

当前我们统一支持：

- `chain`
- `tool`
- `llm`
- `retriever`
- `embedding`
- `prompt`
- `parser`

它主要影响：

- LangSmith 图上的节点类型
- LangSmith 里按 run type 过滤和排查问题

所以一个步骤完全可能是：

- `kind="substep"`
- `trace_run_type="prompt"`

这很正常，因为它在我们的 runtime 里是一个子步骤，但在 LangSmith 语义里它是一个 prompt run。

## 2. 默认值怎么理解

```python
async with tracked_step(
    state,
    name="some_step",
    kind="substep",
):
    ...
```

默认等价于：

```python
async with tracked_step(
    state,
    name="some_step",
    kind="substep",
    trace_run_type="tool",
):
    ...
```

也就是说：

- `tracked_step` 默认把子步骤当 `tool`
- 如果这是 prompt / retriever / embedding / parser，就应该显式改掉

## 3. 我们的推荐映射

| 业务语义 | 推荐 kind | 推荐 trace_run_type |
| --- | --- | --- |
| node 内普通业务小步骤 | `substep` | `tool` |
| prompt 构建 | `substep` | `prompt` |
| 本地 / 外部检索 | `substep` | `retriever` |
| embedding 批处理 | `substep` | `embedding` |
| parser / 提取 / 结构化整理 | `substep` | `parser` |
| 明确包出来的 llm 步骤 | `llm` 或 `substep` | `llm` |

## 4. prompt 步骤怎么写

```python
async with tracked_step(
    state,
    name="plan_prompt_build",
    kind="substep",
    trace_run_type="prompt",
    trace_inputs={"message_count": len(history)},
) as step:
    prompt = build_prompt(...)
    step.set_outputs(prompt_chars=len(prompt))
```

建议：

- `trace_inputs` 放 prompt 相关计数，比如 `message_count`
- `set_outputs` 放 `prompt_chars`、`message_count`、`template_kind`
- 不要在这里塞整份大 state

## 5. retriever 步骤怎么写

```python
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

建议：

- `query_count`
- `result_count`
- `retriever`
- `read_url_count`

## 6. parser / embedding 步骤怎么写

### parser

```python
async with tracked_step(
    state,
    name="outline_parse",
    kind="substep",
    trace_run_type="parser",
) as step:
    outline = parse_outline(...)
    step.set_outputs(section_count=len(outline))
```

### embedding

```python
async with tracked_step(
    state,
    name="chunk_embedding",
    kind="substep",
    trace_run_type="embedding",
) as step:
    vectors = await embed_chunks(...)
    step.set_outputs(chunk_count=len(vectors))
```

## 7. 什么信息适合放进 trace

适合放：

- 各类计数
- 状态
- 简短标签
- 少量摘要

例如：

- `query_count`
- `result_count`
- `prompt_chars`
- `source_packet_count`
- `fallback_used`
- `template_kind`

不适合放：

- 完整 state
- 很长的大段正文
- 一整份巨大的 research material
- 无边界的大对象

## 8. 什么时候不要用 tracked_step

不要给特别碎的 helper 全部包一层。  
团队希望 LangSmith 图保持“少但清楚”，而不是每个小函数都炸开。

优先给这些边界建 step：

- prompt build
- retrieval
- planner / writer 的关键转换点
- fallback 分支
- parser / embedding 这种排障价值高的步骤

## 9. 如果没有 state 还能不能用

可以。

像检索规划、query planning、纯 runtime helper，有时没有可写 state，也可以传 `None`：

```python
async with tracked_step(
    None,
    name="local_retrieval",
    kind="substep",
    trace_run_type="retriever",
):
    ...
```

这时：

- 不会写 runtime_steps
- 也不会发 progress
- 但仍然会创建 LangSmith 子 span

## 10. 和 `@traceable_run` 怎么分工

### `tracked_step`

适合：

- node 内临时的 prompt build 步骤
- 需要顺便记录 progress/runtime stats

### `@traceable_run`

适合：

- 稳定的 prompt builder 函数
- workflow / teaching 层可复用的 message builder

二者可以同时存在，不冲突：

- node 内用 `tracked_step(..., trace_run_type="prompt")`
- prompt builder 函数本身用 `@traceable_run(..., run_type="prompt")`

这样在 LangSmith 里既能看到“这个 node 里发生了 prompt build”，也能看到“具体是哪一个 prompt builder 产出的内容”。
