# Workflows 结构规范

最后更新：2026-04-15

`backend/app/workflows/` 下所有模块和链路，统一遵守本规范。

## 三层结构

```text
workflows/
  digest/                 ← 模块层（对齐五大引擎：ingest/digest/interact/examine/profile）
    planner/              ← 链路层（一条可独立跑的 graph）
    docgen/               ← 链路层
```

- **模块层**：五大引擎，一个模块 = 一个引擎
- **链路层**：模块内一条独立的 workflow graph
- **节点层**：链路里的一步 graph node

## 核心原则

1. 相同职责永远落在相同位置。
2. 没有这类职责，就不要为了对称硬造一层。
3. 链路 root 只放稳定入口和数据骨架，业务逻辑全部下沉。

---

## 模块标准模板

```text
module_name/
  __init__.py              # lazy-import 各链路对外 API
  README.md                # 模块定位 + 链路清单 + 主链路说明（≤60 行）
  lane_a/                  # 链路
  lane_b/                  # 链路
  _shared/                 # 可选：仅当 ≥2 条链路真共享时建
    <topic>.py
```

### 模块根强制约束

**只允许**：`__init__.py`、`README.md`、链路子目录、可选 `_shared/`。

**禁止**：
- ❌ `graph.py` / `state.py` / `runtime.py`（这些是链路级概念）
- ❌ `events.py` / `exports.py`（对外走 `__init__.py`，事件进链路或 `_shared/`）
- ❌ `prompts/` / `services/`（prompts 归链路；service 层属 `app/services/`）
- ❌ 散落的业务文件

### `_shared/` 的硬规则

只有**被 ≥2 条链路真用到**的代码才进 `_shared/`。只 1 条链路用就必须下沉到那条链路的 `lib/`。这是防止 `_shared/` 变成垃圾桶的唯一办法。

前缀下划线表示"模块私有"——外部不应该直接 `from digest._shared import ...`，要用就走链路对外 API。

### 跨链路共享类型

默认**不上提**。下游链路直接 `from ..producer_lane import SomeType`。更常见的情况是 service 层做胶水，两条链路互不感知。

---

## 链路标准模板

```text
lane/
  __init__.py              # 对外门面：re-export run_*、公开类型、normalize 函数
  README.md                # 链路说明（≤60 行）
  graph.py                 # build_graph + run_workflow + 路由
  state.py                 # State TypedDict + Input/Output schema + 对外 Pydantic 类型
  events.py                # 可选：链路专属 progress 事件
  nodes/                   # graph 节点实现
    <action>.py
  prompts/                 # 调 LLM 的 prompt builder / template
    <action>.py
  lib/                     # 节点调用的业务子逻辑
    <topic>.py
```

### 各文件/目录职责

| 位置 | 职责 |
|---|---|
| `__init__.py` | 对外稳定 API 的门面。re-export `run_xxx_workflow`、公开 Pydantic 类型、normalize 函数等。不写业务逻辑。 |
| `graph.py` | 定义 `StateGraph`：节点注册、边、路由、Send 编排。同时提供 `run_xxx_workflow(...)` 作为执行入口（构造 `WorkflowContext`、初始 state、调 `run_state_graph`）。 |
| `state.py` | 定义 `XxxState`（节点间流动的 TypedDict）+ `XxxInput`/`XxxOutput`（LangGraph Studio 投影）。如有对外 Pydantic 类型（service 层用）也放这里。 |
| `nodes/` | 每个 graph 节点一个文件，文件名 = graph 节点名。导出 `build_<name>_node(*, context)`。 |
| `prompts/` | 每个调 LLM 的节点一个文件，文件名和 `nodes/` 对齐。只放 prompt builder 和 template。 |
| `lib/` | 节点调用的业务子逻辑，按主题命名（`publish.py`、`writer.py`、`grounding.py`）。链路太大时 `lib/` 内可按主题再分子目录。 |
| `events.py` | 可选。链路专属的 progress 事件枚举和构造函数。 |

### 链路根强制约束

**禁止**：
- ❌ `runner.py`（执行入口收进 `graph.py`）
- ❌ `contracts.py`（对外类型收进 `state.py` + `__init__.py` re-export）
- ❌ `internal/` / `runtime/` / `services/`（业务子逻辑全进 `lib/`）
- ❌ 链路根直接挂 `publish.py` / `writer.py` / `grounding.py` 等业务文件
- ❌ `nodes/common.py` 之外的任何 `nodes/` 直接挂非 node 文件

---

## 命名硬规则

| 对象 | 规则 | 例 |
|---|---|---|
| graph 节点名 | 小写蛇形，业务动作 | `load_context`, `draft_plan` |
| node 文件 | `<节点名>.py`（不加 `_node` 后缀） | `draft_plan.py` |
| node builder | `build_<节点名>_node` | `build_draft_plan_node` |
| prompt 文件 | 和 node 文件同名 | `draft_plan.py` |
| lib 文件 | 主题名词 | `writer.py`, `publish.py` |
| 执行入口函数 | `run_<lane>_workflow` | `run_docgen_workflow` |
| 图 builder 函数 | `build_<lane>_graph` | `build_docgen_graph` |

三者（graph 节点名 / nodes 文件名 / builder 名）必须一一对应，肉眼可查。

---

## 执行入口：`run_*` 放在 `graph.py` 里

**不要**单独建 `runner.py`。执行入口函数直接放 `graph.py`，和 `build_graph` 做邻居。

```python
# graph.py
def build_planner_graph(*, context: WorkflowContext) -> StateGraph:
    ...

async def run_build_planner_workflow(*, subject, file_ids, ...) -> WorkflowResult[...]:
    context = WorkflowContext(workflow_name="digest.planner", ...)
    return await run_state_graph(
        workflow_name="digest.planner",
        graph_builder=lambda: build_planner_graph(context=context),
        initial_state=create_planner_initial_state(...),
        context=context,
    )
```

理由：两者都是"以整张图为对象的顶层操作"（定义形状 vs 触发执行），配对自然。

---

## 对外暴露：`__init__.py` 门面

链路 `__init__.py` 只做 re-export：

```python
from app.workflows.digest.planner.graph import (
    build_planner_graph,
    run_build_planner_workflow,
    get_langgraph_dev_planner_graph,
)
from app.workflows.digest.planner.state import (
    BuildPlannerDraft,
    PlannerChapterPlan,
    normalize_planner_draft,
    normalize_planner_payload,
)

__all__ = [
    "BuildPlannerDraft",
    "PlannerChapterPlan",
    "build_planner_graph",
    "get_langgraph_dev_planner_graph",
    "normalize_planner_draft",
    "normalize_planner_payload",
    "run_build_planner_workflow",
]
```

模块 `__init__.py` 再把链路 `__init__.py` 的东西 lazy re-export 一层，让上层可以：

```python
from app.workflows.digest import run_build_planner_workflow, run_docgen_workflow
```

---

## 示例：planner（小链路）

```text
planner/
  __init__.py
  README.md
  graph.py                 # build_planner_graph + run_build_planner_workflow
  state.py                 # BuildPlannerState + Input/Output + BuildPlannerDraft + normalize_*
  nodes/
    load_context.py
    ground_concepts.py
    draft_plan.py
  prompts/
    draft_plan.py          # 只有 draft_plan 调 LLM
  lib/
    grounding.py
    plans.py
```

## 示例：docgen（中型链路）

```text
docgen/
  __init__.py
  README.md
  graph.py                 # build_docgen_graph + Send 编排 + run_docgen_workflow
  state.py                 # DocGenState
  nodes/
    load_context.py
    research_chapters.py
    merge_research.py
    finalize_titles.py
    write_chapters.py
    merge_drafts.py
    enrich_assets.py
    append_practice.py
    publish_document.py
  prompts/
    research_chapters.py
    finalize_titles.py
    write_chapters.py
  lib/
    chapter_context.py
    query_planning.py
    writer.py
    assets.py
    publish.py
```

---

## 一句话总结

`workflows/` 是"模块层 + 链路层"的两级组织。模块根只保留 `__init__.py`/`README.md`/链路/`_shared/`；链路 root 只保留 `__init__.py`/`README.md`/`graph.py`/`state.py`；业务子逻辑下沉到 `lib/`，prompt 独立 `prompts/`。相同职责永远落在相同位置，没有独立职责的层不要硬建。
