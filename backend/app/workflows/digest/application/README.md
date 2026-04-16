# Digest Application 说明

最后更新：2026-04-16

`digest/application/` 是 Digest 模块根下的应用用例层。

## 职责

- 承接原 `app.services.knowledge_docs.*`、`app.services.knowledge_graph.*` 中面向 API 的业务用例
- 组合 planner / docgen / knowledge_graph 等独立链路
- 处理 build lock、SSE、background task、结果装配等模块级协调逻辑

## 非职责

- 不定义 graph node
- 不直接承载 prompt 模板
- 不替代 `repositories/`
- 不把长链路实现塞回单文件 service

## 迁移目标

- `build_plans.py`
- `builds.py`
- `overview.py`
- `cleanup.py`
- `knowledge_graph.py`

## 当前 canonical 入口

- `runtime.py`
  - `run_docgen_workflow`
  - `run_graph_digest_workflow`
  - `create_docgen_initial_state`
  - `create_graph_digest_initial_state`
- `events.py`
  - Digest / DocGen 模块级领域事件
- `exports.py`
  - `WORKFLOW_EXPORTS`

模块根的 `runtime.py`、`events.py`、`exports.py` 现在只保留兼容导入面。
