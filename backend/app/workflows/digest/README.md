# Digest 模块说明

最后更新：2026-04-16

`digest/` 负责把资料从“可检索内容”进一步编排成 confirmed plan、知识文档和知识图谱。它也是本轮 workflows 单层化重构的第一落地区域。

## 当前 canonical 结构

```text
digest/
  __init__.py
  README.md
  events.py
  exports.py
  overview.py
  study_plan.py
  planner/
  docgen/
  knowledge_graph/
  common/
```

说明：

- `planner/` 负责生成 confirmed plan
- `docgen/` 负责按 confirmed plan 生成知识文档
- `knowledge_graph/` 负责独立知识图谱链路
- `events.py`、`exports.py` 是 Digest 模块根的 canonical 入口
- `docgen/__init__.py`、`knowledge_graph/__init__.py` 提供 workflow runner 入口
- `overview.py`、`study_plan.py` 是跨 lane 的聚合用例
- `planner/sessions.py`、`docgen/builds.py`、`docgen/cleanup.py`、`knowledge_graph/{build.py,builds.py,module.py,query.py}` 是当前 digest 业务用例主落点
- `common/` 是跨链路共用的 contracts / models / prepare / material_profile / metrics / runtime_config / pedagogy 实现层
- 各链路自己的构建摘要放在对应链路 `lib/reporting.py`，不要再新增顶层 observability 伪链路

## 对外入口

上层优先使用：

```python
from app.workflows.digest import run_docgen_workflow, run_graph_digest_workflow
from app.workflows.digest.planner import run_build_planner_workflow
```

## 迁移约定

- 模块根只做聚合
- 新的模块级 API-facing 用例优先直接进入模块根文件或对应 lane
- 不再单独保留 `runtime.py`
- 新 prompt 放各自链路 `prompts/`
- 新 helper 放各自链路 `lib/`
- 跨链路共享能力走 `common/`
- Digest 文档教学语义走 `common/runtime_config.py` 与 `common/pedagogy/`
