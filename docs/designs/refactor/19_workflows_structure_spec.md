# 19. Workflows 结构规范

最后更新：2026-04-16

这份文档是设计侧的 workflows 权威结构规范。代码侧同步权威文件是：

- `backend/app/workflows/STRUCTURE.md`

两者必须保持一致；如果发现冲突，应以当前代码和 `backend/app/workflows/STRUCTURE.md` 为准，并同步修正文档。

## 1. 顶层结构

`backend/app/workflows/` 现在分成两类模块：

```text
workflows/
  ingest/
  digest/
  interact/
  examine/
  profile/
  support/
```

- `ingest / digest / interact / examine / profile`
  五大 AI 引擎模块
- `support/`
  非引擎业务模块区

## 2. Engine 模块模板

每个引擎模块根目录允许：

```text
workflows/<module>/
  __init__.py
  README.md
  application/
  <lane_a>/
  <lane_b>/
  _shared/          # 可选，仅在真实跨链路复用时建立
```

### 2.1 `application/` 的职责

- 承接面向 API 的业务用例
- 组合多条链路
- 处理 build lock、background task、SSE、状态装配等模块级协调

明确禁止：

- 不把 graph node 放进 `application/`
- 不把 prompt 模板放进 `application/`
- 不把底层数据库能力直接下沉成 infra 杂项

### 2.2 模块根不再新增

- 模块级 `services/`
- 模块级 `prompts/`
- 模块级 `nodes/`
- 模块级 `runtime/`
- 模块级 `internal/`

迁移期兼容文件可以保留，但不能作为新代码落点。

## 3. Engine 链路模板

每条链路固定模板：

```text
workflows/<module>/<lane>/
  __init__.py
  README.md
  graph.py
  state.py
  nodes/
  prompts/
  lib/
  events.py         # 可选
```

### 3.1 各层职责

- `graph.py`
  唯一图入口，负责 graph builder、初始状态构造、路由与 `Send` 编排
- `state.py`
  链路 `TypedDict State`、输入输出投影类型
- `nodes/`
  顶层图节点，一个节点一个文件
- `prompts/`
  prompt builder / template
- `lib/`
  节点内部复用的子逻辑
- `events.py`
  仅在确有明确消费方时出现

### 3.2 链路内禁止项

- `services/`
- `internal/`
- `runtime/`
- `runner.py`
- `contracts.py`

含义：

- 对外入口收口到 `graph.py`
- 子逻辑统一收口到 `lib/`
- 不再为“架构对称”额外堆一层近义目录

## 4. Support 模块模板

`workflows/support/*` 不强制采用 graph/lane 模型，默认模板是：

```text
workflows/support/<module>/
  __init__.py
  README.md
  commands.py
  queries.py
  streams.py        # 可选
  lib/              # 可选
```

适用对象：

- `auth`
- `files`
- `subjects`
- `system`
- `export_import`
- `teaching_tools`

原则：

- support 模块默认不用 LangGraph
- 如果需要长链 AI 流程，直接调用已有 engine 链路
- 不在 support 里平行造一套“伪引擎”

## 5. `_shared/` 规则

只有真实被两条及以上链路复用的内容，才允许进入模块 `_shared/`

允许的典型内容：

- Digest 的 contracts / models / prepare / pedagogy facade
- Ingest 的 parsing / logging / recovery facade

不允许：

- 只给单条链路用的 helper
- 单个节点专属 prompt
- 只是“以后可能复用”的预抽象

## 6. 命名规则

### 6.1 图与用例

- graph builder：`build_<lane>_graph`
- workflow runner：`run_<lane>_workflow`
- application command/query 文件名：按 use case 命名，例如 `build_plans.py`、`builds.py`

### 6.2 节点与文件

- 节点名：小写蛇形，例如 `load_context`
- 节点 builder：`build_<node_name>_node`
- 节点文件：`load_context.py`
- prompt 文件：`load_context.py`、`write_chapters.py`
- `lib/` 文件：按业务主题命名，例如 `writer.py`、`publish.py`

迁移期允许旧 `_node.py`、`internal/`、`runtime/` 存在，但新代码不继续依赖这些命名。

## 7. Digest 标准示例

### 7.1 planner

```text
digest/
  application/
  planner/
    graph.py
    state.py
    nodes/
    prompts/
    lib/
  _shared/
```

- `planner/` 只承接图和链路内部逻辑
- planner session create / append / confirm 进入 `digest/application/build_plans.py`

### 7.2 docgen

```text
digest/
  application/
  docgen/
    graph.py
    state.py
    nodes/
    prompts/
    lib/
  _shared/
    runtime_config.py
    pedagogy/
```

- `docgen/` 只承接 research / writer / publish 等链路内部逻辑
- build trigger / result / cleanup / overview 进入 `digest/application/*`
- 教学语义统一从 `_shared/runtime_config.py` 与 `_shared/pedagogy/` 进入

## 8. 兼容策略

- 模块根 `__init__.py` 继续提供稳定导入面
- 历史 `services/` 仅保留迁移期 shim
- 历史 `teaching/` 源层已删除，不再作为兼容入口恢复
- 历史链路兼容文件允许存在，但必须在 README 与结构规范里明确标注为 compatibility-only

## 9. 一句话总结

新的 workflows 结构只有两个关键词：

- 五大引擎：`application + lanes + _shared`
- 支撑模块：`commands + queries (+ streams/lib)`
