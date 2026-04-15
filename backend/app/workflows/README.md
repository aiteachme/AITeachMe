# Workflows 分层说明

最后更新：2026-04-15

`backend/app/workflows/` 是业务编排层。它负责把 `teaching` 的教学语义、`shared.infra` 的基础能力和数据库状态组织成真正可运行的流程。

一句话理解：
> `workflows` 负责“这条业务流程怎么跑”。

## 1. 当前边界

推荐依赖方向：

```text
api -> services -> workflows -> teaching -> shared.infra -> shared.kernel
```

这意味着：

- `workflows` 可以依赖 `teaching` 和 `shared.infra`
- workflow 公共 authoring/runtime 支撑统一放在 `app.shared.infra.workflow`
- `workflows` 不应该自己再复制一套 tracing、tool registry 或存储接入

## 2. 这份 README 当前只展开什么

这轮只把 `digest` 里的两块写清楚：

- `planner`
- `docgen`

`digest` 里的 `kg / curriculum / unified / build` 仍在演进，本 README 不把它们写成当前批次的权威结构说明；如果需要追具体细节，以代码和 `docs/designs/refactor/*` 为准。

## 3. 当前知识文档主线

对当前产品而言，最重要的主链是：

```text
api/knowledge_docs.py
-> services/knowledge_docs/build_planner_service.py
-> app.workflows.digest.planner
-> confirmed_plan
-> services/knowledge_docs/digest_service.py
-> app.workflows.digest.run_docgen_workflow
```

这条链要分成两个阶段理解：

1. `planner`
   生成和修订构建方案
2. `docgen`
   基于 confirmed plan 执行知识文档构建

## 4. `digest.planner` 怎么看

### 4.1 稳定导入面

当前 planner 的稳定导入面是：

```python
from app.workflows.digest.planner import (
    normalize_planner_payload,
    run_build_planner_workflow,
)
```

服务层应该依赖这个包级入口，而不是直接 import `planner.models` 或 `planner.runtime`。

### 4.2 目录内部分工

`planner/` 目前可以这样理解：

| 文件 | 作用 |
| --- | --- |
| `__init__.py` | planner 对外公共入口 |
| `runtime.py` | 构建 planner workflow 的运行入口 |
| `graph.py` | planner graph 定义 |
| `models.py` | planner draft / payload 规范化与模型 |
| `concept_grounding.py` | 规划前的轻量概念锚点检索 |
| `state.py` | planner graph 状态 |

planner 当前输出的核心合同包括：

- `chapter_plan`
- `research_queries`
- `media_plan`
- `build_constraints`
- `plan_summary`

这些内容在 session 确认后沉淀成 confirmed plan，供 docgen 消费。

## 5. `digest.docgen` 怎么看

### 5.1 当前对外运行入口

这轮不新增独立的 docgen 公共 runtime 包入口。

当前对外仍以：

```python
from app.workflows.digest import run_docgen_workflow
```

作为稳定运行入口。

### 5.2 `docgen/` 内部结构

`docgen/` 本身属于实现目录，不是当前推荐的对外导入面。

当前目录大致分工：

| 目录或文件 | 作用 |
| --- | --- |
| `graph.py` | docgen graph 定义 |
| `state.py` | docgen graph 状态 |
| `nodes/` | research、writer、assemble、practice 等节点 |
| `runtime/` | chapter context、query planning、writer、assets 等 workflow-local runtime |
| `services/` | docgen lane 内部服务辅助 |
| `publish.py` | 构建产物收口与发布辅助 |

结论是：

- `docgen/graph.py`、`nodes/`、`runtime/` 是内部实现
- 外部服务层以 `app.workflows.digest.run_docgen_workflow` 为准

## 6. workflow 公共支撑放哪里

workflow 公共能力统一放在 `app.shared.infra.workflow`，不是 `workflows/common`。

当前推荐入口：

```python
from app.shared.infra.workflow import (
    WorkflowContext,
    WorkflowGraphExport,
    invoke_state_graph,
    run_state_graph,
    tracked_step,
    traceable_run,
    workflow_tracer,
)
```

其中：

- `run_state_graph(...)` / `invoke_state_graph(...)` 负责 graph 执行入口
- `tracked_step(...)` 负责 step 级 tracing / runtime stats
- `workflow_tracer(...)` / `traceable_run(...)` 负责 workflow 级 trace authoring

## 7. Planner / DocGen 和 Teaching / Infra 的关系

可以把这两层的职责分开看：

- `planner / docgen`
  决定流程节点、阶段切换、失败路径和最终收口
- `teaching`
  提供教学默认值、文档脚手架、教学表达
- `shared.infra`
  提供检索、工具、技能、存储、workflow authoring、trace / execution

尤其对 docgen 来说：

- 标题、导学、recap 等教学表达来自 `app.teaching.documents`
- 搜索、检索和向量 gating 来自 `app.shared.infra.search` / `app.shared.infra.subject`
- docgen 自己只负责“这些能力什么时候被调用”

## 8. 什么不该放进 Workflows

下面这些内容不要继续回流到 `workflows`：

- 底层数据库、存储、LLM、retriever、reader 接入
- 通用 tool registry / skillpack registry
- teaching 表达本身
- 可以脱离当前 workflow 独立存在的共享基础能力

判断方法：

- 在决定“这轮流程怎么跑”，放 `workflows`
- 在决定“怎么教”，放 `teaching`
- 在决定“能力怎么接”，放 `shared.infra`

## 9. 阅读顺序

第一次读当前知识文档主线，建议顺序如下：

1. `backend/app/api/knowledge_docs.py`
2. `backend/app/services/knowledge_docs/build_planner_service.py`
3. `backend/app/workflows/digest/planner/__init__.py`
4. `backend/app/workflows/digest/planner/runtime.py`
5. `backend/app/services/knowledge_docs/digest_service.py`
6. `backend/app/workflows/digest/__init__.py`
7. `backend/app/workflows/digest/runtime.py`
8. `backend/app/workflows/digest/docgen/graph.py`

## 10. 一句话总结

`workflows` 是业务编排层。
对当前知识文档主线来说，planner 负责把构建方案做成 confirmed plan，docgen 负责基于这个合同去执行文档构建；公共运行支撑来自 `shared.infra.workflow`，教学表达来自 `teaching`。
