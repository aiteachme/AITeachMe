# Workflows 说明

最后更新：2026-04-15

`backend/app/workflows/` 是业务编排层，负责把五大引擎组织成真正可运行的 workflow。

推荐依赖方向：

```text
api -> services -> workflows -> teaching -> shared.infra -> shared.kernel
```

## 一句话边界

- `workflows`
  决定“这条业务流程怎么跑”
- `teaching`
  决定“怎么教、怎么表达”
- `shared.infra`
  提供 LLM、search、storage、workflow runtime、observability 等基础能力

## workflow 作者现在只需要记住的入口

```python
from app.shared.infra.workflow import (
    emit_progress,
    invoke_state_graph,
    project_typed_dict_schema,
    run_state_graph,
    workflow_tracer,
)
from langsmith import traceable
```

分工：

- `run_state_graph(...)` / `invoke_state_graph(...)`
  workflow root 入口
- `workflow_tracer(...).node(handler, ...)`
  graph node 接线
- `emit_progress(...)`
  前端进度事件
- `project_typed_dict_schema(...)`
  从主 `State` 投影 LangGraph Studio 输入输出字段
- `@traceable`
  prompt / helper tracing

## 先读哪几份文档

- 总体结构规范：[STRUCTURE.md](./STRUCTURE.md)
- LangSmith 规范：[LANGSMITH.md](./LANGSMITH.md)
- Progress 规范：[PROGRESS.md](./PROGRESS.md)
- 调试指南：[DEBUGGING.md](./DEBUGGING.md)
- Digest 模块说明：[digest/README.md](./digest/README.md)
- Planner 链路说明：[digest/planner/README.md](./digest/planner/README.md)
- DocGen 链路说明：[digest/docgen/README.md](./digest/docgen/README.md)
- Ingest 模块说明：[ingest/README.md](./ingest/README.md)

## 当前最重要的主链路

知识文档主线是：

```text
api/knowledge_docs.py
-> services/knowledge_docs/build_planner_service.py
-> app.workflows.digest.planner
-> confirmed_plan
-> services/knowledge_docs/digest_service.py
-> app.workflows.digest.run_docgen_workflow
```

可以拆成两个阶段理解：

1. `planner`
   把用户目标和资料整理成 confirmed plan
2. `docgen`
   基于 confirmed plan 执行正式文档构建

## 当前最值得记住的组织结论

- 先按“模块层”组织，再按“链路层”组织
- `prompts/` 是资源层，`nodes/` 是顶层节点层，`runtime/` 是局部执行层
- 图上的业务动作名、builder 名、文件名尽量一致
- 多链路模块根目录的 `graph.py / state.py / __init__.py` 只做聚合，不继续堆链路实现

具体规则见 [STRUCTURE.md](./STRUCTURE.md)。

## 一句话总结

`workflows` 是业务编排层；当前知识文档主线优先看 `digest.planner -> confirmed_plan -> digest.docgen`，后续 `planner / docgen / ingest` 都按统一的模块层、链路层、节点层规范继续收口。

