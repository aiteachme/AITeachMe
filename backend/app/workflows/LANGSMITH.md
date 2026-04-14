# LangSmith 接入说明

这份文档只回答一件事：

如何让 `workflows/` 里的 LangSmith 追踪足够简单，后续改动时不需要在大量节点和 infra helper 之间来回同步。

---

## 核心原则

**LangGraph 自动追踪 node** — 我们不再手动创建 node span。

当 `LANGSMITH_TRACING=true` 时，LangGraph 编译后的 graph 会自动为每个 node 创建 LangSmith span。
我们只需要做两件事：

1. 通过 `config=` 传递 metadata/tags 给 `graph.ainvoke()`，让 LangGraph root span 带上业务上下文
2. 通过 `llm_trace_scope()` 设置 ambient context，让 infra 层 LLM 调用自动继承当前 workflow/lane/node 信息

### 为什么不手动创建 node span？

之前的做法是在 `trace.node()` 内部用 `annotate_traceable` + `build_langsmith_extra` 再包一层，
导致每个 node 在 LangSmith 上出现**两个 span**（LangGraph 自动的 + 我们手动的）。
去掉手动 span 后，trace 层级更干净，代码也少了约 300 行。

---

## 4 个核心入口

```python
from app.shared.infra.workflow import (
    run_state_graph,     # workflow 入口
    workflow_tracer,     # node 接线
    traceable_run,       # prompt/helper 装饰器
    tracked_step,        # node 内关键步骤
)
```

| 你在写什么 | 推荐接口 | 创建 LangSmith span？ | 备注 |
| --- | --- | --- | --- |
| 整条 workflow 执行 | `run_state_graph(...)` | 否（LangGraph 自动创建 root span） | 传 `config=` 给 `ainvoke()` |
| graph 里的 node 接线 | `trace = workflow_tracer(...); trace.node(...)` | 否（LangGraph 自动创建 node span） | 只设 ambient context |
| 稳定 prompt builder | `@traceable_run(..., run_type="prompt")` | 是（创建子 span） | 等价于 `@langsmith.traceable(...)` |
| node 内关键步骤 | `tracked_step(...)` | 是（当 `kind != "node"` 时创建子 span） | 同时管理 runtime stats + progress |

---

## 当前落地状态

当前仓库的主执行 workflow 已经**大体统一到这 4 个入口**，但还不是每个文件都 100% 完全一致。

### 已基本对齐的主线

- `digest.planner`
- `digest.docgen`
- `digest.unified`
- `digest.graph`
- `interact.chat`
- `ingest.fast_parse / ingest.deep_enhance`
- `examine.question_build / examine.exam_grade`
- `profile.pipeline`

这些主线至少满足：

- workflow root 通过 `run_state_graph(...)` 或 `invoke_state_graph(...)` 进入
- graph node 通过 `workflow_tracer(...).node(...)` 接线
- prompt builder 通过 `@traceable_run(...)`
- node 内关键子步骤优先通过 `tracked_step(...)`

### 仍存在的历史差异

- 少数“概览图 / 非主执行图”仍是轻量 StateGraph，没有完整 tracing 包装；这类图主要用于展示结构，不作为 tracing 规范样板。
- 少数旧节点内部仍会直接使用 `llm_trace_scope(...)` 做上下文桥接；这属于兼容保留，不应继续扩散为新写法。

结论：

- **把当前主执行 workflow 视为“基本统一”是合理的**
- **把 `LANGSMITH.md` 视为后续新增代码的唯一规范来源更重要**

---

## 详细用法

### 1. workflow 入口 — `run_state_graph`

```python
from app.shared.infra.workflow import run_state_graph

result = await run_state_graph(
    workflow_name="digest.planner",
    graph_builder=lambda: build_planner_graph(context=context),
    initial_state=initial_state,
    context=context,
)
```

**内部做了什么：**

1. `_build_graph_config()` — 构建 LangGraph invoke config:
   ```python
   config = {
       "run_name": "digest.planner",
       "tags": ["aiteachme", "workflow:digest.planner"],
       "metadata": {
           "app": "aiteachme-backend",
           "workflow": "digest.planner",
           "subject": "线性代数",
           "build_session_id": "build-abc123",
       },
   }
   ```
2. `llm_trace_scope(...)` — 设置 ambient context
3. `compiled.ainvoke(initial_state, config=config)` — LangGraph 自动创建 root span
4. 异常捕获 → 返回 `WorkflowResult`

### 2. node 接线 — `workflow_tracer().node()`

```python
from app.shared.infra.workflow import workflow_tracer

def build_docgen_graph(*, context: WorkflowContext) -> StateGraph:
    workflow = StateGraph(DocGenState)
    trace = workflow_tracer(context=context, lane="docgen")

    workflow.add_node(
        "load_context",
        trace.node(
            build_load_context_node(context=context),
            name="load_context",
            timing_field="load_ms",  # 可选：自动计时并注入到 node 返回值
        ),
    )
    workflow.add_node(
        "finalize_assemble",
        trace.node(
            build_finalize_assemble_node(context=context),
            name="finalize_assemble",
        ),
    )

    workflow.add_edge("load_context", "finalize_assemble")
    workflow.set_entry_point("load_context")
    return workflow
```

**`trace.node(handler, name=...)` 内部做了什么：**

1. 从 `state` 中提取 `subject`、`build_session_id`
2. `tracing_context(metadata=..., tags=...)` — 丰富 LangGraph 自动 span 的上下文
   ```python
   # 自动注入到 LangGraph node span 的 metadata:
   metadata = {
       "workflow": "digest.docgen",
       "lane": "docgen",
       "node": "load_context",
       "subject": "线性代数",
       "build_session_id": "build-abc123",
   }
   # tags:
   tags = ["workflow:digest.docgen", "node:docgen.load_context", "lane:docgen"]
   ```
3. `llm_trace_scope(...)` — 设置 ambient context，让嵌套的 infra LLM 调用知道当前在哪个 node
4. 如果设了 `timing_field`，自动计时并注入到返回的 dict 中

**它不创建额外的 LangSmith span**，避免了双重 span 问题。

#### 装饰器写法（工厂函数内）

```python
def build_load_context_node(*, context: WorkflowContext):
    trace = workflow_tracer(context=context, lane="planner")

    @trace.node(name="load_context", timing_field="load_ms")
    async def load_context_node(state):
        # 这里写 node 逻辑
        return {"loaded_data": data}

    return load_context_node
```

两种写法（传 handler vs 装饰器）完全等价，选择你觉得更清晰的写法即可。

### 3. prompt builder — `@traceable_run`

```python
from app.shared.infra.workflow import traceable_run

@traceable_run(name="digest.docgen.writer_prompt", run_type="prompt")
def build_writer_messages(*, subject: str, tone: str) -> list[dict]:
    return [
        {"role": "system", "content": f"你是一位教学文档作者，用{tone}语气写作。"},
        {"role": "user", "content": f"请为「{subject}」撰写章节内容。"},
    ]
```

`traceable_run` 就是 `langsmith.traceable` 的薄别名。你也可以直接用：

```python
from langsmith import traceable

@traceable(name="digest.docgen.writer_prompt", run_type="prompt")
def build_writer_messages(*, subject: str, tone: str) -> list[dict]:
    ...
```

两种写法完全等价。`traceable_run` 的好处是签名里保留了 `workflow`, `lane` 等参数
（内部会忽略），方便搜索和理解。

#### 常用 `run_type`

| run_type | 用于 |
| --- | --- |
| `"prompt"` | prompt builder / message 构造 |
| `"chain"` | 多步组合逻辑 |
| `"retriever"` | 检索/搜索函数 |
| `"tool"` | 工具函数（默认值） |

### 4. node 内关键步骤 — `tracked_step`

```python
from app.shared.infra.workflow import tracked_step

async with tracked_step(
    state,
    name="web_retrieval",
    kind="substep",                 # runtime stats 分类
    phase="planner",                # 进度事件的 phase
    running_message="正在搜索资料...",
    completed_message="搜索完成。",
    failed_message="搜索失败。",
    trace_run_type="retriever",     # LangSmith span 类型
    trace_inputs={"query_count": len(queries)},
    trace_metadata={"source": "web"},
) as step:
    hits = await search_web(queries)
    step.set_outputs(result_count=len(hits))
```

**`tracked_step` 同时管理三件事：**

1. **runtime stats** — 自动记录 `record_step_start` / `record_step_end`
2. **进度事件** — 如果设了 `phase` + message 参数，自动通过 `progress_callback` 推送进度
3. **LangSmith 子 span** — 当 `kind != "node"` 时，创建一个 `langsmith_trace` 子 span

`kind` 和 `trace_run_type` **不是一回事**：
- `kind` 是项目内部 runtime stats 的分类
- `trace_run_type` 决定 LangSmith 上这个 span 显示为什么类型

详见 [TRACKED_STEP.md](./TRACKED_STEP.md)。

---

## `run_state_graph` vs `invoke_state_graph`

| 函数 | 用途 | 入参 | 异常处理 |
| --- | --- | --- | --- |
| `run_state_graph(...)` | 主 workflow 入口 | 需要 `WorkflowContext` | 自动捕获异常并返回 `WorkflowResult` |
| `invoke_state_graph(...)` | 子 graph 调用 | 直接传 `subject`、`build_session_id` 等 | 异常直接抛出 |

两者都自动传 LangGraph config 和设置 `llm_trace_scope`。

**什么时候用 `invoke_state_graph`：**
- examine 模块的题目构建、评分等子 graph
- 不需要 `WorkflowContext` 的独立 graph 调用

---

## infra 层保留哪些 trace

默认只保留这几类共享边界：

1. **LLM 调用包装** — `app/shared/infra/llm_support/` 中的 `acompletion` / `acompletion_structured`
2. **Tool registry** — `ToolRegistry.execute()` 自动创建 tool span
3. **retriever / reader** — 共享 IO 边界
4. **`BaseTracedExecution`** — 长运行共享执行单元（如 DocGenWriterRuntime）

普通 infra helper 默认不要为了 LangSmith 再单独加一层 decorator。
如果需要在 infra 层新增 trace，先确认它属于上述 4 种共享边界之一。

---

## LangSmith trace 层级

```text
graph_run: "digest.docgen" (LangGraph 自动创建, config 传入 metadata/tags)
  ├─ node: "load_context" (LangGraph 自动创建 + tracing_context 注入额外 metadata)
  │    ├─ tracked_step: "web_retrieval" (kind=substep, trace_run_type=retriever)
  │    └─ infra: acompletion (自动继承 ambient context: workflow/lane/node)
  ├─ node: "plan_chapters" (LangGraph 自动创建)
  │    ├─ tracked_step: "build_outline"
  │    └─ infra: acompletion_structured
  └─ node: "finalize_assemble" (LangGraph 自动创建)
       └─ infra: acompletion
```

这正好满足"workflow 层统一收口，infra 层自动继承"的目标。

---

## 向后兼容

### `trace.node(...)` 签名保留

以下参数保留在签名中但已不再使用，可以安全删除：
- `input_keys` — 以前用于过滤 state 中传给 LangSmith 的输入字段
- `output_keys` — 以前用于过滤 state 中传给 LangSmith 的输出字段

### `traceable_run(...)` 签名保留

以下参数保留在签名中但内部忽略：
- `workflow` / `workflow_name` / `context` / `lane`
- `input_keys` / `output_keys` / `timing_field`

保留它们是为了避免已有调用方需要改代码。

---

## 环境变量

| 变量 | 必须 | 说明 |
| --- | --- | --- |
| `LANGSMITH_TRACING=true` | 是 | 启用 LangSmith 追踪 |
| `LANGSMITH_API_KEY` | 是 | LangSmith API 密钥 |
| `LANGSMITH_PROJECT` | 否 | 项目名（默认 `AITeachMe`） |
| `LANGSMITH_CAPTURE_INPUTS` | 否 | 是否记录 trace 输入预览；本地默认开启，云端默认关闭，只在你想覆盖默认策略时设置 |
| `LANGSMITH_CAPTURE_OUTPUTS` | 否 | 是否记录 trace 输出预览；LLM / retriever / reader / tool / runtime 共用这套策略 |
| `LANGSMITH_MAX_TEXT_CHARS` | 否 | 单个文本字段最大长度，超出会截断（默认 2000） |

补充说明：

- 本地开发如果 `APP_MODE=local`，trace 输入输出预览默认开启；显式写环境变量只是覆盖默认值，不是必须每次都配。
- `pytest` 默认不应把测试 trace 上传到正式 LangSmith project；仓库里的测试夹具会主动关闭这一点。
- 输入输出预览遵循“关键事实优先”原则：保留 query、url、title、关键 snippet、研究轮次等诊断必需信息；不默认上传整页正文、通用 tool 大结果或运行时长文本正文。

---

## 迁移纪律

以后新增或重构 workflow tracing 时，按下面的优先级判断用哪个接口：

1. **这是 workflow root 吗？**
   → 用 `run_state_graph(...)` 或 `invoke_state_graph(...)`

2. **这是 graph node 吗？**
   → 用 `trace = workflow_tracer(...); trace.node(...)`

3. **这是稳定 prompt / helper 函数吗？**
   → 用 `@traceable_run(...)` 或 `@traceable(...)`

4. **这是 node 内关键步骤吗？**
   → 用 `tracked_step(...)`

5. **这是 infra 共享执行边界吗？**
   → 才考虑在 infra 层保留或新增 trace

**关键约束：不要在 workflow 层手动调用 `langsmith_trace()`、`annotate_traceable()`、
`build_langsmith_extra()` 等底层函数。** 所有 workflow 追踪都应该通过上面 4 个入口完成。

进一步约束：

- 新增 workflow graph 时，`workflow.add_node(...)` 默认都应包在 `trace.node(...)` 外层。
- 新增 workflow runtime 入口时，默认走 `run_state_graph(...)` / `invoke_state_graph(...)`，不要自己直接 `graph.compile().ainvoke(...)`。
- 新增 prompt builder 时，默认加 `@traceable_run(..., run_type="prompt")`，不要裸写成无名 helper。
- 新增 node 内多步逻辑时，优先用 `tracked_step(...)` 表达关键边界，不要在 node 里零散手写 LangSmith span。
- **不要在新的 workflow 业务代码里直接调用 `llm_trace_scope(...)`。**
  这个接口只应该留在 `shared/infra/workflow`、共享 runtime 桥接层或少数历史兼容代码里。

你可以把它理解成一条 code review 红线：

- 如果在 `app/workflows/**` 新代码里看到了 `langsmith_trace(...)`
- 或 `annotate_traceable(...)`
- 或 `build_langsmith_extra(...)`
- 或直接手写 `tracing_context(...)`
- 或直接手写 `llm_trace_scope(...)`

那通常说明这段代码没有按规范接入，应该优先重写成 4 个统一入口之一。

---

## 新 Workflow 模板

新增 workflow 时，推荐直接按下面这个骨架起手：

```python
from langgraph.graph import END, StateGraph

from app.shared.infra.workflow import run_state_graph, tracked_step, workflow_tracer
from app.shared.infra.workflow.context import WorkflowContext


def build_demo_graph(*, context: WorkflowContext) -> StateGraph:
    workflow = StateGraph(DemoState)
    trace = workflow_tracer(context=context, lane="demo")

    @trace.node(name="load_context")
    async def load_context_node(state: DemoState) -> dict:
        async with tracked_step(
            state,
            name="prepare_inputs",
            kind="substep",
            trace_run_type="tool",
        ) as step:
            payload = await prepare_inputs(...)
            step.set_outputs(item_count=len(payload))
        return {"payload": payload}

    @trace.node(name="finalize")
    async def finalize_node(state: DemoState) -> dict:
        return {"done": True}

    workflow.add_node("load_context", load_context_node)
    workflow.add_node("finalize", finalize_node)
    workflow.set_entry_point("load_context")
    workflow.add_edge("load_context", "finalize")
    workflow.add_edge("finalize", END)
    return workflow


async def run_demo_workflow(*, context: WorkflowContext, initial_state: DemoState):
    return await run_state_graph(
        workflow_name="demo.workflow",
        graph_builder=lambda: build_demo_graph(context=context),
        initial_state=initial_state,
        context=context,
    )
```

只要新代码大体长这样，trace 风格通常就不会跑偏。

---

## 一句话版本

```
workflow root  → run_state_graph（传 LangGraph config）
workflow node  → workflow_tracer().node()（只设 ambient context）
prompt/helper  → @traceable_run 或 @traceable
node 内关键步骤 → tracked_step
infra 层       → 只在共享执行边界保留 trace
LangGraph 自动追踪每个 node — 不需要手动再创建 node span
```
