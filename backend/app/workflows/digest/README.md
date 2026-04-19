# Digest 模块说明

最后更新：2026-04-17

`digest/` 负责把原始学习材料组织成可教学、可生成、可追踪的知识产物。

## 当前目录

```text
digest/
  __init__.py
  README.md
  common/
  planner/
  docgen/
  kg_file_ingest/
  kg_docs_sync/
  knowledge_graph/
```

## 各目录做什么

- `planner/`
  负责根据文件内容和历史对话生成 confirmed plan
- `docgen/`
  负责根据 confirmed plan 生成知识文档
- `kg_file_ingest/`
  负责知识图谱文件入图链路
- `kg_docs_sync/`
  负责知识文档和知识图谱的同步链路
- `common/`
  放跨 lane 共用能力，例如 events、exports、contracts、prepare、material profile、metrics、runtime config、pedagogy
  以及 subject 级知识产物清理 `cleanup.py`
- `knowledge_graph/`
  当前仓库里仍保留的历史目录；不是新的 canonical lane 入口，后续以 `kg_file_ingest/` 和 `kg_docs_sync/` 为主

## 当前公开入口

上层优先使用稳定导入面，不直接从深层文件拼装：

```python
from app.workflows.digest import run_docgen_workflow
from app.workflows.digest import run_graph_docs_sync_workflow
from app.workflows.digest import run_graph_file_ingest_workflow
from app.workflows.digest.planner import (
    create_build_planner_session,
    run_build_planner_workflow,
)
```

## 目录约束

- 模块根只做聚合，不承载业务实现
- 新的 API-facing 用例必须进入具体 lane 或 `common/`
- 新 prompt 放各自链路 `prompts/`
- 新 helper 放各自链路 `lib/`
- 跨链路共享能力统一放 `common/`
- 各链路自己的构建摘要放在对应链路 `lib/reporting.py`
- 不要再新增顶层伪链路，例如 `runtime.py`、`observability.py`

## 当前理解

当前 digest 的 canonical 主线是：

- `planner -> docgen`
- `kg_file_ingest`
- `kg_docs_sync`

如果要看具体编排，优先进入各链路下的 `graph.py`、`builds.py`、`state.py`
