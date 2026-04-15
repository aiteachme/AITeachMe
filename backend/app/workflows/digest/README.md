# Digest 模块说明

最后更新：2026-04-15

`digest` 是当前 `workflows` 里最典型的多链路模块，负责把 ingest 产出的材料加工成结构化知识资产。

## 当前主链路

知识文档主线是：

```text
api/knowledge_docs.py
-> services/knowledge_docs/build_planner_service.py
-> app.workflows.digest.planner
-> confirmed_plan
-> services/knowledge_docs/digest_service.py
-> app.workflows.digest.run_docgen_workflow
```

也就是两段：

1. `planner`
   先把目标和资料收口成 confirmed plan。
2. `docgen`
   再按 confirmed plan 生成正式知识文档。

## 模块层结构

```text
digest/
  __init__.py
  README.md
  graph.py
  runtime.py
  state.py
  events.py
  exports.py
  prompts/
  shared/
  planner/
  docgen/
  kg/
  curriculum/
  unified/
  build/
  observability/
```

模块层约束：

- `graph.py / runtime.py / state.py` 是聚合层
- `prompts/`、`shared/`、`observability/` 是模块共享层
- 真正链路实现放到 `planner/`、`docgen/`、`kg/`、`curriculum/`

## 当前统一规范

`digest` 下的链路统一遵守两条硬规则：

1. 相同职责，永远落在相同位置。
2. 没有这类职责，就不要为了对称硬造一层。

落到当前代码上就是：

- `planner/`
  自己承担执行边界，所以保留 `runner.py + contracts.py + nodes/ + runtime/`
- `docgen/`
  执行边界已经在模块层，所以只保留 `graph.py + state.py + nodes/ + runtime/`
- `publish.py`、`grounding.py`、`plans.py` 这类专项实现都不再直接挂在链路 root

## prompts 放哪

模块级 prompts 继续集中在：

```text
digest/prompts/
  planner_prompts.py
  docgen_prompts.py
  kg_prompts.py
  archetype_prompts.py
```

原则：

- 能放模块级的 prompt，就不要散落进 node 文件
- prompt builder 和 prompt template 放 `prompts/`
- graph / node / publish / retrieval 逻辑不要混进 prompt 文件

## 一句话总结

`digest` 是“模块层聚合 + 多条链路分治”的典型例子；真正要统一的不是文件列表，而是职责映射。
