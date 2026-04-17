# Digest Module

<<<<<<< HEAD
最后更新：2026-04-17
=======
`digest/` contains workflow lanes only.
>>>>>>> f022e165e2fb089f91f95f4a60321570adbf68e5

## Current Layout

```text
digest/
  __init__.py
  README.md
  planner/
  docgen/
  kg_file_ingest/
  kg_docs_sync/
  common/
  application/
  shared/
  unified/
```

<<<<<<< HEAD
说明：

- `planner/` 负责生成 confirmed plan
- `docgen/` 负责按 confirmed plan 生成知识文档
- `knowledge_graph/` 负责独立知识图谱链路，也承接知识总览与基于图谱的学习计划
- `__init__.py` 只提供稳定导入面，不承载业务实现
- `common/events.py`、`common/exports.py` 是 Digest 跨链路事件与 workflow export 入口
- `docgen/__init__.py`、`knowledge_graph/__init__.py` 提供 workflow runner 入口
- `overview.py`、`study_plan.py` 是跨 lane 的聚合用例
- `planner/__init__.py`、`planner/graph.py`、`docgen/builds.py`、`docgen/cleanup.py`、`knowledge_graph/{build.py,builds.py,module.py,query.py}` 是当前 digest 业务用例主落点
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
- 新的 API-facing 用例必须进入对应 lane 或 `common/`，不要新增模块根 `.py`
- 不再单独保留 `runtime.py`
- 新 prompt 放各自链路 `prompts/`
- 新 helper 放各自链路 `lib/`
- 跨链路共享能力走 `common/`
- Digest 文档教学语义走 `common/runtime_config.py` 与 `common/pedagogy/`
=======
## Notes
- `kg_file_ingest/` and `kg_docs_sync/` are independent workflows and follow the lane skeleton.
- Non-workflow knowledge-graph business services were moved to `workflows/support/knowledge_graph/`.
- Cross-lane shared code stays in `digest/common/`.
>>>>>>> f022e165e2fb089f91f95f4a60321570adbf68e5
