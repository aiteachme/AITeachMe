# Planner 结构说明

最后更新：2026-04-15

`planner/` 是知识文档主链的第一段，负责把用户目标、资料和轻量 grounding 整理成可确认的 plan。

## 对外入口

上层应优先依赖：

```python
from app.workflows.digest.planner import (
    normalize_planner_payload,
    run_build_planner_workflow,
)
```

调图或本地调试时再看：

- `build_planner_graph(...)`
- `get_langgraph_dev_planner_graph()`

## 当前链路阶段

planner 当前是一个 3 步链路：

1. `load_context`
2. `ground_concepts`
3. `draft_plan`

## 目录职责

```text
planner/
  __init__.py
  README.md
  graph.py
  state.py
  runner.py
  contracts.py
  nodes/
  runtime/
    grounding.py
    plans.py
```

职责划分：

- `runner.py`
  planner 执行入口，负责 context、initial state 和 graph invoke。
- `contracts.py`
  planner 对外稳定合同，公开 draft / normalize API。
- `nodes/`
  只放顶层 graph node。
- `runtime/grounding.py`
  只放 planner 专属轻量 grounding 实现。
- `runtime/plans.py`
  只放 fallback、normalize、标题生成等 plan 内部实现。

## 为什么要这样拆

planner 虽然不大，但之前最容易让人困惑的点是：

- root 目录里既有执行入口，又有内部 helper
- `models.py` 实际上已经不只是 model
- `concept_grounding.py` 是内部实现，却和 `graph.py` 平级

现在统一后的规则是：

- root 目录只保留稳定入口和稳定合同
- 内部实现全部下沉到 `runtime/`
- graph / node / helper 三者职责明显分开

## 一句话总结

planner 是“小链路”，但也遵守统一模板：
`runner.py` 管执行，`contracts.py` 管公开合同，`nodes/` 管 graph 节点，`runtime/` 管内部实现。
