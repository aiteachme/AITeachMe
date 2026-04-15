# Digest 模块说明

最后更新：2026-04-16

`digest/` 负责把资料从“可检索内容”进一步编排成 confirmed plan、知识文档和知识图谱。

## 当前 canonical 结构

```text
digest/
  __init__.py
  README.md
  planner/
  docgen/
  knowledge_graph/
  unified/
  shared/
```

说明：

- `planner/` 负责生成 confirmed plan
- `docgen/` 负责按 confirmed plan 生成知识文档
- `knowledge_graph/` 负责知识图谱链路
- `unified/` 负责编排共享准备、docgen、kg 等组合流程
- `shared/` 是跨链路共用的 contracts / models / prepare / primitives / metrics 实现层
- 各链路自己的构建摘要放在对应链路 `lib/reporting.py`，不要再新增顶层 observability 伪链路

## 对外入口

上层优先使用：

```python
from app.workflows.digest import run_docgen_workflow, run_graph_digest_workflow
from app.workflows.digest.planner import run_build_planner_workflow
```

## 迁移约定

- 模块根只做聚合
- 新 prompt 放各自链路 `prompts/`
- 新 helper 放各自链路 `lib/`
- 跨链路共享能力走 `shared/`；不要再新增只做转发的 `_shared/` 空门面
- 旧模块级兼容文件暂时保留，但新代码优先走各链路目录
