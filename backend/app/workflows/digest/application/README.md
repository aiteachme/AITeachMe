# Digest Application 说明

最后更新：2026-04-16

`digest/application/` 现在只保留为兼容层。

## 职责

- 为旧导入路径提供稳定 shim
- 把历史 `digest/application/*` 导入转发到 `digest` 根、`planner/`、`docgen/`、`knowledge_graph/` 的新 canonical 位置

## 非职责

- 不再承载真实业务实现
- 不作为新代码落点

## 迁移目标

- `planner/sessions.py`
- `docgen/builds.py`
- `docgen/cleanup.py`
- `overview.py`
- `study_plan.py`
- `knowledge_graph/{build.py,builds.py,module.py,query.py}`

## 当前 canonical 入口

- `digest/docgen/__init__.py`
- `digest/knowledge_graph/__init__.py`
- `digest/events.py`
- `digest/exports.py`

本目录下同名文件现在只做兼容转发，不再是 canonical 入口。
