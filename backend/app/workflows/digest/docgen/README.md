# DocGen 结构说明

最后更新：2026-04-15

`docgen/` 是知识文档主链的第二段，负责根据 confirmed plan 真正生成知识文档。

## 对外入口

模块层稳定入口仍然是：

```python
from app.workflows.digest import run_docgen_workflow
```

如果只在 `docgen/` 包内部调图或调试，主要入口是：

- `build_docgen_graph(...)`
- `create_docgen_initial_state(...)`
- `get_langgraph_dev_docgen_graph()`

## 当前链路阶段

docgen 当前主链路按阶段可以理解为：

1. `load_context`
2. `research_chapters`
3. `merge_research`
4. `finalize_titles`
5. `write_chapters`
6. `merge_drafts`
7. `enrich_assets`
8. `append_practice`
9. `publish_document`

## 目录职责

```text
docgen/
  __init__.py
  README.md
  graph.py
  state.py
  nodes/
  runtime/
    chapter_context.py
    query_planning.py
    writer.py
    assets.py
    publish.py
```

职责划分：

- `graph.py`
  只保留 graph wiring、Send 路由和 initial state。
- `state.py`
  只保留 DocGenState。
- `nodes/`
  只保留顶层 node builder。
- `runtime/`
  放 docgen 内部专项实现。

## 为什么 docgen 没有 `runner.py`

这是刻意设计，不是缺失。

原因很简单：

- docgen 的真实执行入口已经收口在模块层 `digest/runtime.py`
- `docgen/` 自己主要承担的是“链路定义”和“链路内部实现”
- 如果再硬放一个只会转发的 `runner.py`，职责反而会变糊

所以 docgen 这里的统一方式不是“为了对称也补一个 runner”，而是：

- 有独立执行职责，才有 `runner.py`
- 没有独立执行职责，就只保留 `graph.py + state.py + nodes/ + runtime/`

## 为什么 `publish.py` 放进 `runtime/`

`publish.py` 并不是 root 稳定入口，它本质上是一组 docgen 内部发布实现：

- merged markdown 组装
- staging outputs
- manifest 写入
- 最终 publish / persistence

这类文件如果直接挂在链路根目录，会让 root 目录变成“公开接口 + 内部实现”的混合层。

现在统一后的约定是：

- 链路 root 只放稳定入口
- 特殊用途实现统一下沉到 `runtime/`

所以现在的阅读方式是：

- 看 `graph.py` 了解链路结构
- 看 `nodes/` 了解顶层职责
- 看 `runtime/` 了解专项实现

## 一句话总结

docgen 是中大型子链路，应该坚持“薄 root、薄 graph、清晰 node、专项 runtime”的组织方式；没有独立职责的层不要为了对称硬保留。
