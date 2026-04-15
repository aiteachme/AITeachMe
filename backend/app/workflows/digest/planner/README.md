# Planner 链路说明

最后更新：2026-04-15

`planner/` 是知识文档主线的第一条链路，负责把用户目标、资料摘要和轻量 grounding 整理成可确认的 build plan。

## 对外入口

稳定入口：

```python
from app.workflows.digest.planner import (
    normalize_planner_payload,
    run_build_planner_workflow,
)
```

调图时再看：

- `build_planner_graph(...)`
- `get_langgraph_dev_planner_graph()`

## 当前节点

1. `load_context`
2. `ground_concepts`
3. `draft_plan`

## 目录结构

```text
planner/
  __init__.py
  README.md
  graph.py
  state.py
  nodes/
    load_context.py
    ground_concepts.py
    draft_plan.py
  prompts/
    draft_plan.py
  lib/
    grounding.py
    plans.py
```

## 规则

- 不再新增 `runner.py`
- 不再新增 `contracts.py`
- 对外 draft / normalize 能力放到 `state.py` 或 `lib/`，再由 `__init__.py` re-export
- 轻量 grounding 逻辑放 `lib/grounding.py`
- fallback plan / normalize 逻辑放 `lib/plans.py`

## 一句话总结

planner 是一条短链路，但也遵循完整模板：`graph.py + state.py + nodes/ + prompts/ + lib/`。
