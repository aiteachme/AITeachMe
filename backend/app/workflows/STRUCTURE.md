# Workflows 结构规范

最后更新：2026-04-15

这份文档只回答一件事：
`backend/app/workflows/` 下的模块和链路，应该怎样按职责统一分层。

## 核心原则

统一不是“每个链路必须长得一模一样”，而是：

1. 同一种职责，永远放在同一种位置。
2. 没有这类职责，就不要为了对称硬造一层。
3. 链路 root 只保留稳定入口，不裸放内部实现文件。

## 三层结构

推荐把 `workflows/` 理解成三层：

```text
workflows/
  digest/                 # 模块层
    planner/              # 链路层
    docgen/               # 链路层
      nodes/              # 实现层
      runtime/            # 实现层
```

判断规则：

- `digest`、`ingest`、`interact`、`examine`、`profile` 是模块层。
- `planner`、`docgen`、`fast_parse`、`deep_enhance` 是链路层。
- `nodes/`、`runtime/`、`prompts/`、`services/` 是实现层。

## 链路 root 标准模板

```text
lane/
  __init__.py
  README.md
  graph.py
  state.py
  runner.py              # 可选
  contracts.py           # 可选
  nodes/                 # 可选
  runtime/               # 可选
  prompts/               # 可选
  services/              # 可选
  events.py              # 可选
```

各位置职责：

- `__init__.py`
  对外稳定导出，只暴露上层真正该依赖的入口。
- `README.md`
  说明链路职责、阶段和分层约定。
- `graph.py`
  只定义 graph、节点注册、路由和 LangGraph dev 入口。
- `state.py`
  只定义主 State 和必要的 schema projection。
- `runner.py`
  只有当这个链路本身承担执行边界时才保留。
- `contracts.py`
  只有当这个链路需要公开 typed contract / normalize API 时才保留。

## `graph.py` 和 `runner.py` 的边界

这是最容易混的地方。

### `graph.py`

回答的是：

- 这张图有哪些节点
- 节点之间怎么连
- 什么时候路由
- 初始 state 长什么样

### `runner.py`

回答的是：

- 这张图怎么真正跑起来
- `WorkflowContext` 怎么构造
- 初始输入怎么装配
- `run_state_graph(...)` 怎么调用

所以：

- 如果 `runner.py` 只是单纯转发到另一个函数，没有自己的执行职责，那它不该存在。
- 如果链路真正对外承担执行入口，`runner.py` 就有意义。

## root 目录严格约束

链路 root 目录只能放两类东西：

1. 稳定入口
2. 稳定合同

下面这些内容不应该直接挂在链路 root：

- 某个 node 专用 helper
- grounding 逻辑
- publish / staging / manifest 实现
- fallback 生成逻辑
- 大段 normalize / materialize / repair 细节

这些都应该下沉到实现层目录。

## 实现层怎么分

### `nodes/`

适合放：

- 单个 graph node 的 handler
- node builder
- 顶层节点编排逻辑

### `runtime/`

适合放：

- workflow-local helper
- 会被多个 node 复用，但不该下沉到 `shared.infra`
- 链路内的特殊用途实现文件

典型例子：

- `runtime/chapter_context.py`
- `runtime/query_planning.py`
- `runtime/writer.py`
- `runtime/assets.py`
- `runtime/publish.py`
- `runtime/grounding.py`
- `runtime/plans.py`

这次统一后的硬规则就是：
如果某个文件不是稳定入口，也不是 node 本身，那优先放进 `runtime/`。

### `prompts/`

适合放：

- prompt builder
- prompt template
- messages 组装 helper

### `services/`

只在下面场景使用：

- 链路内部确实存在少量局部领域服务
- 这部分逻辑既不是 graph wiring，也不适合归入 `runtime/`

## `contracts.py` 的意义

推荐在链路 root 使用 `contracts.py`，而不是继续让一个越来越胖的 `models.py` 同时承担：

- model
- normalize
- fallback
- synthesis

推荐写法：

```text
planner/
  contracts.py          # 对外稳定接口
  runtime/
    plans.py            # 真正实现 normalize / fallback / synthesis
```

也就是说：

- `contracts.py` 负责“公开什么”
- `runtime/*.py` 负责“具体怎么做”

## 推荐示例

### 小型链路：`planner`

```text
planner/
  __init__.py
  README.md
  graph.py
  state.py
  runner.py
  contracts.py
  nodes/
  runtime/
```

适合：

- 链路自身对外承担执行入口
- 顶层节点不多
- 但仍要保持 root 清爽

### 中大型子链路：`docgen`

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

适合：

- 节点较多
- 存在 fan-out / fan-in
- 真正执行入口已经收口在模块层
- 链路内部有多种专项实现

### 多链路模块：`ingest`

```text
ingest/
  __init__.py
  README.md
  graph.py
  state.py
  runtime/               # 模块层聚合执行入口
  fast_parse/
  deep_enhance/
```

模块层和链路层可以不对称，但职责映射必须一致：

- 模块 root 做聚合
- 链路 root 做稳定入口
- 内部实现全部下沉

## 命名规范

### graph 节点名

统一用业务动作名：

- `load_context`
- `ground_concepts`
- `research_chapters`
- `merge_research`
- `write_chapters`
- `publish_document`

### node builder 名

和 graph 节点名对齐：

```python
build_research_chapters_node(...)
build_merge_research_node(...)
build_publish_document_node(...)
```

### node 文件名

也和 graph 节点名对齐：

```text
nodes/research_chapters_node.py
nodes/merge_research_node.py
nodes/publish_document_node.py
```

## 对外暴露规则

`__init__.py` 建议只暴露：

- `run_xxx_workflow`
- `normalize_xxx_payload`
- `build_xxx_graph`，如果上层确实需要
- 稳定 contract

不建议默认暴露：

- node builder
- runtime helper
- 内部 publish / grounding / planning helper

## 一句话总结

真正的统一标准不是“每个链路文件列表完全一样”，而是“相同职责永远落在相同位置”；没有独立职责的层，就不要为了对称硬保留。
