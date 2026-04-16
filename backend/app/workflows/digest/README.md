# Digest 模块说明

最后更新：2026-04-16

`digest/` 负责把资料从“可检索内容”进一步编排成 confirmed plan、知识文档和知识图谱。它也是本轮 workflows 单层化重构的第一落地区域。

## 当前 canonical 结构

```text
digest/
  __init__.py
  README.md
  application/
  planner/
  docgen/
  knowledge_graph/
  unified/
  common/
```

说明：

- `planner/` 负责生成 confirmed plan
- `docgen/` 负责按 confirmed plan 生成知识文档
- `knowledge_graph/` 负责知识图谱链路
- `unified/` 负责编排共享准备、docgen、kg 等组合流程
- `application/` 是 Digest 模块级 API-facing 用例落点
- `application/runtime.py`、`application/events.py`、`application/exports.py` 是模块级 canonical 入口
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
- 模块级 API-facing 用例进入 `application/`
- 模块根 `runtime.py`、`events.py`、`exports.py` 仅保留兼容 shim
- 新 prompt 放各自链路 `prompts/`
- 新 helper 放各自链路 `lib/`
- 跨链路共享能力走 `common/`
- Digest 文档教学语义走 `common/runtime_config.py` 与 `common/pedagogy/`
- 旧模块级兼容文件暂时保留，但新代码优先走各链路目录

