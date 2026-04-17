# Digest Module

`digest/` contains workflow lanes only.

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

## Notes

- `planner/` 负责生成 confirmed plan；API-facing 入口在 `planner/__init__.py`，workflow runner 在 `planner/graph.py`。
- `docgen/` 负责按 confirmed plan 生成知识文档；构建触发和后台编排在 `docgen/builds.py`。
- `kg_file_ingest/` 与 `kg_docs_sync/` 是两个独立知识图谱 workflow lane，并遵循 lane skeleton。
- 非 workflow 的知识图谱业务服务已迁到 `workflows/support/knowledge_graph/`。
- 跨链路共享代码放在 `digest/common/`，包括 events、exports、contracts、prepare、material profile、metrics、runtime config 和 pedagogy。
- 各链路自己的构建摘要放在对应链路 `lib/reporting.py`，不要新增顶层 observability 伪链路。

## Public Entrypoints

上层优先使用：

```python
from app.workflows.digest import run_docgen_workflow
from app.workflows.digest.planner import create_build_planner_session, run_build_planner_workflow
```

## Migration Rules

- 模块根只做聚合
- 新的模块级 API-facing 用例优先直接进入模块根文件或对应 lane
- 不再单独保留 `runtime.py`
- 新 prompt 放各自链路 `prompts/`
- 新 helper 放各自链路 `lib/`
- 跨链路共享能力走 `common/`
- Digest 文档教学语义走 `common/runtime_config.py` 与 `common/pedagogy/`
