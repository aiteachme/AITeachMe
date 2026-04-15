# Workflows 结构规范

最后更新：2026-04-15

这份文档只讲一件事：

`backend/app/workflows/` 下一个 workflow 模块，推荐长成什么样，哪些文件是标准链路，哪些只是可选扩展。

## 一句话目标

目录结构要做到三件事：

1. 第一次看目录就知道主链路从哪进
2. graph 节点名、文件名、builder 名尽量一致
3. 不把“可选辅助文件”伪装成“标准必需文件”

## 标准 workflow 最小模板

一个正常的 workflow 包，最少推荐包含：

```text
module/
├── __init__.py
├── state.py
├── graph.py
└── runtime.py
```

职责：

- `__init__.py`
  对外稳定入口，只暴露真正要给上层依赖的 API
- `state.py`
  graph state 定义
- `graph.py`
  LangGraph 图定义、node 接线、路由拼装
- `runtime.py`
  workflow root 运行入口，负责 `run_state_graph(...)` 和初始 state

如果一个 workflow 连这四个文件都没有，就很难称为“结构清晰的独立 workflow 模块”。

## 常见扩展目录

### `prompts/`

适合放：

- prompt builder
- prompt 模板
- messages 组织 helper

不适合放：

- graph 路由
- node 副作用
- DB / 检索 / 文件系统调用

### `nodes/`

适合放：

- node builder
- 单个 graph node 的 handler
- 节点级业务编排逻辑

推荐在这些场景拆 `nodes/`：

- 顶层 node 数量 >= 4
- 单个 `graph.py` 变得拥挤
- 多个 node 已经明显有独立职责

### `runtime/`

适合放：

- workflow-local runtime helper
- 会被多个 node 复用，但又不应该下沉到 `shared.infra` 的逻辑

例子：

- chapter context 组织
- query planning
- writer runtime
- assets runtime

### `services/`

只在下面这类情况使用：

- 某个 workflow 内部有少量局部领域服务
- 这些逻辑不属于 graph 本身，也不适合扔进 `runtime/`

不建议：

- 把 `services/` 当成万能杂物间
- 仅仅因为“文件大了”就把所有东西都丢进 `services/`

### `models.py`

适合放：

- payload contract
- normalize / coerce / merge helper
- draft / response / typed payload model

如果 state 本身已经很简单，不一定需要单独 `models.py`。

### `routes.py` / `routers.py`

只在路由逻辑很复杂时再拆。

如果只是一个简单的 `route_after_step(...)`，直接放 `graph.py` 即可。

### `exports.py`

这是可选文件，不是标准链路。

只在下面这类需求存在时保留：

- 你们要生成离线 Mermaid / Markdown 架构图
- 你们希望给静态导出补标题、描述、prompt 指纹、动态边覆盖

如果平时只用 `langgraph dev` / Studio 看图，可以没有 `exports.py`。

## 推荐目录示例

### 小型 workflow

```text
planner/
├── __init__.py
├── graph.py
├── models.py
├── runtime.py
└── state.py
```

适合：

- 顶层 node 不多
- 局部 helper 数量有限
- graph 仍然容易读

当前典型样例：

- `digest/planner/`

### 中大型 workflow

```text
docgen/
├── __init__.py
├── graph.py
├── publish.py
├── runtime.py
├── state.py
├── nodes/
├── prompts/
├── runtime/
└── services/
```

适合：

- 顶层 node 较多
- node 内部逻辑明显分工
- 有 workflow-local runtime / service 复用

当前典型样例：

- `digest/docgen/`

## 模块层与链路层

不要把“模块”和“链路”混成一层。

推荐把结构理解成：

```text
workflows/
├── 模块层
│   ├── digest/
│   ├── ingest/
│   ├── interact/
│   ├── examine/
│   └── profile/
│
└── 链路层
    └── 例如 digest/ 下继续拆：
        ├── planner/
        ├── docgen/
        ├── kg/
        ├── curriculum/
        └── unified/
```

判断方法：

- `digest` 是模块层
- `planner` / `docgen` 是链路层
- `nodes/` / `prompts/` / `runtime/` 是实现层

## 命名规范

### graph 节点名

推荐使用业务动作名，而不是历史实现名：

- `load_context`
- `ground_concepts`
- `research_chapters`
- `merge_research`
- `write_chapters`
- `publish_document`

### node builder 名

推荐直接和 graph 节点名对齐：

```python
build_research_chapters_node(...)
build_merge_research_node(...)
build_publish_document_node(...)
```

### node 文件名

推荐也和 graph 节点名对齐：

```text
nodes/research_chapters_node.py
nodes/merge_research_node.py
nodes/publish_document_node.py
```

## 不推荐的命名状态

下面这种情况会越来越难维护：

```text
graph node: research_chapters
builder: build_targeted_research_node
file: targeted_research_node.py
```

原因是：

- 图上看到的是一套名字
- 目录里看到的是另一套名字
- 新人很难快速建立映射

短期可以兼容，长期应该收敛。

## `graph.py` 里应该保留什么

`graph.py` 应该聚焦这些事情：

- 声明 graph state
- 注册 node
- 组织边和条件路由
- 提供 `get_langgraph_dev_*_graph()`

不建议在 `graph.py` 塞太多：

- 大段 prompt 构造
- 大量模型 normalize 逻辑
- 复杂检索 / 写作 helper
- 大量与单个 node 强绑定的实现细节

## `runtime.py` 里应该保留什么

`runtime.py` 应该聚焦：

- `WorkflowContext` 构造
- `run_state_graph(...)`
- 初始 state 构造
- 对外稳定执行入口

不要把大量节点内部逻辑堆到 `runtime.py`。

## `__init__.py` 应该暴露什么

只暴露上层真正应该依赖的稳定接口。

推荐暴露：

- `run_xxx_workflow`
- `normalize_xxx_payload`
- `build_xxx_graph`，如果确实需要给外部复用

不推荐默认暴露：

- 所有 node builder
- 所有局部 helper
- `WORKFLOW_EXPORTS`

`WORKFLOW_EXPORTS` 属于可选离线导出能力，不应被当成 workflow 标准公开面。

## LangGraph Studio 相关约束

如果需要给 Studio 收口输入输出：

- 用一个主 `State` 做唯一真相源
- 用 `project_typed_dict_schema(...)` 投影出精简 schema
- 不要为了 Studio 手写三份重复类型

## 一句话总结

workflow 目录结构的目标不是“把文件分得越多越高级”，而是让主链路、节点职责、可选辅助能力一眼就能看清楚。
