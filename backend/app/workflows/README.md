# Workflows 说明

最后更新：2026-04-15

`backend/app/workflows/` 是业务编排层，负责把教学语义和基础设施能力组织成真正可运行的五大引擎流程。

推荐依赖方向：

```text
api -> services -> workflows -> teaching -> shared.infra -> shared.kernel
```

## 当前边界

- `workflows` 决定“这条业务流程怎么跑”
- `teaching` 决定“怎么教、怎么表达”
- `shared.infra` 提供搜索、工具、LLM、workflow runtime、observability 等基础能力

不要在 `workflows` 里再复制一套：

- tracing 系统
- tool registry
- 存储接入
- 通用 execution 框架

## 当前知识文档主链路

对当前产品最重要的主链路是：

```text
api/knowledge_docs.py
-> services/knowledge_docs/build_planner_service.py
-> app.workflows.digest.planner
-> confirmed_plan
-> services/knowledge_docs/digest_service.py
-> app.workflows.digest.run_docgen_workflow
```

可以分成两个阶段理解：

1. `planner`
   生成并修订构建方案
2. `docgen`
   基于 confirmed plan 执行正式知识文档构建

## workflow 观测层现在怎么用

workflow 作者只保留 3 个公开入口：

```python
from app.shared.infra.workflow import (
    emit_progress,
    invoke_state_graph,
    run_state_graph,
    workflow_tracer,
)
from langsmith import traceable
```

分工如下：

- `run_state_graph(...)` / `invoke_state_graph(...)`
  workflow root 入口
- `workflow_tracer(...).node(handler, ...)`
  node 接线的唯一规范
- `emit_progress(...)`
  前端进度事件
- `@traceable`
  prompt / helper tracing

进一步说明：

- trace 规范看 [LANGSMITH.md](./LANGSMITH.md)
- progress 规范看 [PROGRESS.md](./PROGRESS.md)

## `digest.planner` 怎么看

稳定入口：

```python
from app.workflows.digest.planner import (
    normalize_planner_payload,
    run_build_planner_workflow,
)
```

当前 `planner/` 目录大致分工：

| 文件 | 作用 |
| --- | --- |
| `__init__.py` | planner 对外公共入口 |
| `runtime.py` | planner workflow 运行入口 |
| `graph.py` | planner graph 定义 |
| `models.py` | planner draft / payload 规范化 |
| `concept_grounding.py` | 规划前的轻量 grounding |
| `state.py` | planner graph 状态 |

planner 当前输出的核心合同包括：

- `chapter_plan`
- `research_queries`
- `media_plan`
- `build_constraints`
- `plan_summary`

这些内容在 session 确认后沉淀成 confirmed plan，供 docgen 消费。

## `digest.docgen` 怎么看

当前稳定入口仍然是：

```python
from app.workflows.digest import run_docgen_workflow
```

`docgen/` 本身主要属于实现目录，而不是推荐给服务层直接依赖的外部接口面。

当前目录大致分工：

| 目录或文件 | 作用 |
| --- | --- |
| `graph.py` | docgen graph 定义 |
| `state.py` | docgen graph 状态 |
| `nodes/` | research、writer、assemble、practice 等节点 |
| `runtime/` | chapter context、query planning、writer、assets 等 workflow-local runtime |
| `services/` | docgen lane 内部服务辅助 |
| `publish.py` | 构建产物收口与发布辅助 |

## workflow 公共支撑放哪里

workflow 公共能力统一放在 `app.shared.infra.workflow`。

当前推荐导入面：

```python
from app.shared.infra.workflow import (
    WorkflowContext,
    WorkflowGraphExport,
    emit_progress,
    invoke_state_graph,
    run_state_graph,
    workflow_tracer,
)
```

## 什么不该放进 Workflows

下面这些内容不要继续回流到 `workflows`：

- 底层数据库、存储、LLM、retriever、reader 接入
- 通用 tool registry / skillpack registry
- LangSmith 私有 helper
- 第二套 progress / tracing 框架
- teaching 表达本身

判断方法：

- 在决定“这条流程怎么跑”，放 `workflows`
- 在决定“怎么教”，放 `teaching`
- 在决定“能力怎么接”，放 `shared.infra`

## 阅读顺序

第一次读当前知识文档主链，建议按下面顺序：

1. `backend/app/api/knowledge_docs.py`
2. `backend/app/services/knowledge_docs/build_planner_service.py`
3. `backend/app/workflows/digest/planner/__init__.py`
4. `backend/app/workflows/digest/planner/runtime.py`
5. `backend/app/services/knowledge_docs/digest_service.py`
6. `backend/app/workflows/digest/__init__.py`
7. `backend/app/workflows/digest/runtime.py`
8. `backend/app/workflows/digest/docgen/graph.py`

## 一句话总结

`workflows` 是业务编排层。对当前知识文档主线来说，planner 负责把用户目标和资料整理成 confirmed plan，docgen 负责按这个契约执行正式构建；观测层已经收口成两件事：LangSmith trace 给研发排障，progress 给前端展示。
