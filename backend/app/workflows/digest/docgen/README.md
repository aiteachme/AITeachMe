# DocGen 结构说明

最后更新：2026-04-15

`docgen/` 是知识文档主链的第二段。

它负责基于 confirmed plan，把规划好的章节方案真正构建成知识文档。

## 标准入口

对上层来说，稳定入口仍然是：

```python
from app.workflows.digest import run_docgen_workflow
```

如果只在 `docgen/` 包内部看图或调图，主要入口是：

- `build_docgen_graph(...)`
- `create_docgen_initial_state(...)`
- `get_langgraph_dev_docgen_graph()`

## 当前链路阶段

docgen 当前主链路可以按业务阶段理解为：

1. `load_context`
   读取 confirmed plan、shared inputs、构建上下文
2. `research_chapters`
   按章节并行研究
3. `merge_research`
   收拢章节研究结果
4. `finalize_titles`
   最终确认章节标题
5. `write_chapters`
   按章节并行写作
6. `merge_drafts`
   收拢章节草稿
7. `enrich_assets`
   补图、Mermaid、素材增强
8. `append_practice`
   追加练习内容
9. `publish_document`
   发布正式文档

## 目录职责

| 文件或目录 | 作用 |
| --- | --- |
| `__init__.py` | 包内稳定入口 |
| `graph.py` | graph 定义、send 路由、顶层 node 接线 |
| `state.py` | docgen graph state |
| `publish.py` | 文档发布收口 |
| `nodes/` | 顶层 node builder |
| `runtime/` | chapter context、writer、assets 等 workflow-local runtime |
| `services/` | docgen 内部局部服务 |

## 命名规范现状

docgen 现在已经先完成了一层规范化：

- graph 节点名是业务动作名
- graph 中调用的 builder 名也已经和业务动作名对齐

例如：

- `research_chapters`
- `build_research_chapters_node(...)`

但需要说明的是：

- 部分底层文件名仍保留历史实现名
- 例如旧的 `targeted_research_node.py`

当前做法是：

- 先通过 `nodes/__init__.py` 提供业务化 builder 别名
- 后续如果要继续收口，再单独做一次文件重命名重构

## `nodes/`、`runtime/`、`services/` 的分工

### `nodes/`

只负责顶层 graph node。

它应该回答的是：

- 这个 node 做什么
- 接收什么 state
- 返回什么 state patch

### `runtime/`

放会被多个 node 复用、但又不适合进 `shared.infra` 的 docgen 本地执行能力。

例如：

- `chapter_context.py`
- `query_planning.py`
- `writer.py`
- `assets.py`

### `services/`

只保留 docgen 内部局部服务。

如果未来某个能力已经跨 workflow 复用，就不该继续留在这里。

## 一句话总结

docgen 是一个中大型 workflow，应该坚持“graph 看阶段、nodes 看顶层职责、runtime 看局部执行能力、services 只放少量内部服务”的分层方式，不要再把命名和职责混在一起。
