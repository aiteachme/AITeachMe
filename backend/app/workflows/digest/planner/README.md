# Planner 结构说明

最后更新：2026-04-15

`planner/` 是知识文档主链的第一段。

它负责把：

- 用户目标
- 已上传资料
- 轻量 grounding 结果

整理成一个可确认的构建方案，再交给后续 `docgen` 消费。

## 标准入口

推荐上层只依赖：

```python
from app.workflows.digest.planner import (
    normalize_planner_payload,
    run_build_planner_workflow,
)
```

如果是调图或本地调试，再看：

- `build_planner_graph(...)`
- `get_langgraph_dev_planner_graph()`

## 当前链路阶段

planner 当前就是一条很小的三段式链路：

1. `load_context`
   读取用户目标、文件、shared inputs
2. `ground_concepts`
   做轻量概念 grounding，补充事实锚点
3. `draft_plan`
   流式生成研究任务草案并规范化为 plan

## 目录职责

| 文件 | 作用 |
| --- | --- |
| `__init__.py` | 对外稳定入口 |
| `runtime.py` | workflow root 入口 |
| `graph.py` | planner graph 与 node builder |
| `state.py` | 主 state 与 Studio schema 投影 |
| `models.py` | planner draft / normalize / fallback 合同 |
| `concept_grounding.py` | planner 专属轻量 grounding |

## 为什么 planner 目前没有 `nodes/`

因为它现在只有 3 个顶层节点，而且 `graph.py` 仍然能读。

当前这属于可接受状态。

如果未来出现下面任一情况，建议再拆 `nodes/`：

- 顶层 node 增加到 4 个以上
- 单个 node 的实现明显膨胀
- graph 文件开始同时承担太多 prompt / helper / node 细节

## state 约束

planner 现在采用：

- `BuildPlannerState`
  作为唯一主 state
- `project_typed_dict_schema(...)`
  投影出 LangGraph Studio 的精简输入输出 schema

这意味着：

- 不再维护三份重复类型
- Studio 看到的只是调试真正需要的字段

## 一句话总结

planner 是一个“小而明确”的 workflow：先取上下文，再补 grounding，最后产出 plan。当前重点是保持它入口稳定、链路短、合同清晰，不要过早拆成过多层级。
