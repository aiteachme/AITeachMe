# Workflows 模块说明

`backend/app/workflows/` 是后端的业务编排层，负责承载五大教学引擎对应的 LangGraph 图、节点执行顺序、运行入口和图导出能力。

这里的原则很明确：
- `services/` 负责接口触发、参数校验、持久化适配。
- `workflows/` 负责真正的业务编排与状态推进。
- `shared/infra/` 只放通用能力。
- `teaching/` 只放教学专属能力。

## 五大引擎

| 引擎 | 目录 | 主要职责 |
|------|------|----------|
| `ingest` | `workflows/ingest/` | 文件解析、分类、结构化抽取、深度增强 |
| `digest` | `workflows/digest/` | 构建方案规划、知识文档生成、知识图谱构建、课程派生 |
| `interact` | `workflows/interact/` | 教学对话、上下文检索、教学策略选择、流式回答 |
| `examine` | `workflows/examine/` | 出题、组卷、判卷、复盘 |
| `profile` | `workflows/profile/` | 掌握度更新、复习调度、薄弱点分析、画像刷新 |

## 目录约定

每个 workflow 模块尽量保持下面这套顶层结构：

```text
workflows/<engine>/
├── __init__.py
├── graph.py
├── state.py
├── runtime.py
├── exports.py
├── prompts/
│   ├── __init__.py
│   └── prompts.py
└── nodes/
```

说明：
- `graph.py`：只定义 LangGraph 拓扑，不写重业务逻辑。
- `state.py`：定义状态类型。
- `runtime.py`：定义运行入口，负责创建 context、调用 `run_state_graph()`。
- `exports.py`：暴露流程图导出入口，供 `backend/scripts/generate_workflow_diagrams.py` 使用。
- `prompts/`：统一放提示词；Digest 相关提示词继续集中在 `backend/app/workflows/digest/prompts/`。

## Digest 的层次

`digest` 下面现在有多条业务 lane：
- `planner`
- `docgen`
- `kg`
- `curriculum`

另外还有一个 `unified`。

`unified` 不是额外的第六条业务流程，它只是一个薄的 orchestrator，用来做三件事：
- 准备共享输入，避免多个 lane 重复读文件和重复切块。
- 在一次完整构建里协调 `docgen / kg / curriculum` 的运行顺序和并行关系。
- 在结束时统一汇总状态、发布结果、记录 timing/token summary。

所以：
- 业务生成逻辑应该写在各自 lane 里。
- `unified` 只允许保留“总调度 / 总装配”职责，不要继续往里面塞业务细节。

## Graph 暴露约定

每个模块至少暴露一个真实可编译的 graph 构建函数：

```python
def build_xxx_graph(...) -> StateGraph:
    ...
```

如果需要兼容 `langgraph dev` 的零参数入口，再额外暴露：

```python
def get_langgraph_dev_xxx_graph() -> StateGraph:
    ...
```

约定：
- `backend/langgraph.json` 里只注册真实可调试 graph。
- 不要为了导出、预览、调试分别再复制一套图。
- 如果某个 graph 需要默认 `WorkflowContext`，优先用 `get_langgraph_dev_xxx_graph()` 提供零参数入口。

## 流程图导出约定

自动流程图脚本：

```bash
conda run -n atm python backend/scripts/generate_workflow_diagrams.py
```

输出目录：

```text
backend/scripts/.generated_workflow_diagrams/
```

要求：
- `exports.py` 里的 `WORKFLOW_EXPORTS` 必须优先暴露真实执行图。
- 概览图可以保留，但应排在执行图后面。
- `planner`、`docgen`、`unified` 这类主链路图必须可单独导出。

## LangSmith 兼容规范

这是后续改其他模块时必须遵守的固定规范。

### 1. Workflow 入口

所有可执行 workflow 默认通过下面两个入口之一运行：
- `app.workflows.common.runtime.run_state_graph()`
- `app.workflows.common.runtime.invoke_state_graph()`

不要在业务代码里散落手写的：
- `graph.compile().ainvoke(...)`
- 自己拼 `llm_trace_scope`
- 自己拼一套 LangSmith 根 span

原因：
- 这样可以统一 workflow 级 trace。
- 可以稳定继承 `subject / build_session_id / workflow / lane`。
- 可以减少每个模块各写一套 tracing 的重复代码。

### 2. Node 入口

所有重要节点默认通过统一 wrapper 接入 LangSmith：

```python
from app.workflows.common.observability import wrap_workflow_node
```

先说明这个 wrapper 的定位：
- 它不是业务适配层，也不是新的中台。
- 它只是把“打开 node span + 继承 `llm_trace_scope` + 记录少量输入输出”这段重复样板收成一行。
- 保留它的目的，是避免 `ingest / interact / examine / profile / digest` 各自手写一套 tracing 入口。

为什么这里要有它，而 `gpt-researcher` 没有：
- `gpt-researcher` 的主干更多是 `agent -> skills/actions` 的直接调用，不是大量 LangGraph node 的编排树。
- AITeachMe 明确要求每个 workflow 后面都能方便接 LangSmith，并且在 Studio 里能细看到 node 级过程。
- 在这个前提下，如果没有统一 node 入口，重复代码会分散到每个 graph 里，反而更重。

推荐写法：

```python
workflow.add_node(
    "generate_templates",
    wrap_workflow_node(
        build_generate_templates_node(...),
        workflow_name="examine.question_build",
        lane="question_build",
        node_name="generate_templates",
    ),
)
```

约定：
- 一个节点只需要一个轻量 wrapper。
- wrapper 只负责 span、metadata、inputs、outputs、耗时。
- 不要再为每个模块额外造一层 tracing adapter。
- 只要某个节点是“真实业务节点”，默认就应该接它。
- 路由函数、纯状态判断函数、简单常量返回节点，可以不接。
- 如果某个模块确实不想直接写 `wrap_workflow_node(...)`，也只能在本 graph 文件里再包一个很薄的本地 `_wrap_node(...)`，不能扩散成新的通用框架。

Digest 内部如果仍使用 `wrap_digest_node()`，也应保持它只是对通用 wrapper 的薄封装，而不是另一套完全独立机制。

### 3. LLM 调用入口

所有模型调用统一走：
- `app.shared.infra.llm`
- `app.shared.infra.llm_support`

不要在 workflow 节点里直接调用底层 SDK。

这样可以自动获得：
- 模型路由
- fallback
- token 统计
- LangSmith LLM span

### 4. 稳定 metadata 字段

新增或重构 workflow 时，优先补齐这些稳定字段：
- `subject`
- `build_session_id`
- `workflow`
- `lane`
- `node`
- `planner_session_id`
- `confirmed_plan_id`
- `digest_mode`
- `chapter_index`
- `session_id`
- `job_id`
- `file_id`
- `exam_paper_id`

不是每个流程都需要所有字段，但能提供的要尽量提供。

### 5. 推荐 outputs

节点 trace 的 outputs 至少应包含：
- `elapsed_ms`
- `status`
- `error`（如果失败）
- `output_keys`

如果节点有明显的业务计数，再补：
- `file_count`
- `unit_count`
- `chapter_count`
- `source_count`
- `doc_count`
- `review_task_count`
- `weakness_count`
- `word_count`
- `placeholder_count`

原则：
- 只记录对调试有价值的结果。
- 不要把 tracing wrapper 做成复杂报表引擎。

### 6. LangGraph Dev / Studio 可调试性

一个模块要算“接好了 LangSmith + LangGraph Dev”，至少要满足：
- `langgraph.json` 中有真实 graph 入口。
- graph 能 compile。
- Studio 中能看到 workflow 根 span。
- 重要节点有 node span。
- 节点里的 LLM 调用有 LLM span。
- 工具调用如果走 retriever / scraper / skill，也能继续向下钻。

## 新模块接入检查清单

后续新增或重构 workflow 时，提交前至少自查下面几项：

- 是否通过 `run_state_graph()` 或 `invoke_state_graph()` 运行。
- 是否给关键节点接了 `wrap_workflow_node()`。
- 是否所有 LLM 调用都走统一 LLM 层。
- 是否在 `langgraph.json` 注册了真实 graph。
- 是否在 `exports.py` 里暴露了流程图导出入口。
- 是否优先导出真实执行图而不是概览图。
- 是否补齐了稳定 metadata。
- 是否至少有一个 compile smoke test。

## 当前实现风格

后续继续按更轻量的方式推进，尽量接近 `gpt-researcher` 的风格：
- `graph` 只编排业务节点。
- `skills/tools` 直接承载业务动作。
- tracing 只保留一层统一接入。
- 不要扩散 `adapter / bridge / compat` 这类中间层。

目标不是“框架更重”，而是：
- 读 graph 就能看懂流程。
- 读 skill 就能看懂动作。
- LangSmith 自动跟着流程走。
