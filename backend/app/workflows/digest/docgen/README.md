# DocGen 链路说明

最后更新：2026-04-15

`docgen/` 是知识文档主线的第二条链路，负责根据 confirmed plan 真正生成教学化知识文档。

## 对外入口

上层稳定入口仍然是：

```python
from app.workflows.digest import run_docgen_workflow
```

链路内部调图入口：

- `build_docgen_graph(...)`
- `create_docgen_initial_state(...)`
- `get_langgraph_dev_docgen_graph()`

## 当前节点

1. `load_context`
2. `research_chapters`
3. `merge_research`
4. `finalize_titles`
5. `write_chapters`
6. `merge_drafts`
7. `enrich_assets`
8. `append_practice`
9. `publish_document`

## 目录结构

```text
docgen/
  __init__.py
  README.md
  graph.py
  state.py
  nodes/
  prompts/
  lib/
```

当前 canonical 分层：

- `graph.py`
  只负责图结构、Send 分发、初始状态构造
- `nodes/`
  只放顶层 graph node builder
- `prompts/`
  只放 research / writer / asset 相关 prompt builder
- `lib/`
  放 chapter context、query planning、writer、assets、publish 等子逻辑

## 迁移说明

- `docgen/` 已收口为 `graph.py + state.py + nodes/ + prompts/ + lib/`
- 节点内部子逻辑统一放在 `lib/`，不再额外引入 `internal/` 夹层
- 模块级 `digest.prompts` 只作为兼容门面，不再作为 docgen 的主依赖位置

## 一句话总结

docgen 是中型链路，root 只保留稳定骨架，真正的写作与发布逻辑全部下沉到 `nodes/ + prompts/ + lib/`。
