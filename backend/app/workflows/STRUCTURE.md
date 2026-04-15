# Workflows 结构规范

最后更新：2026-04-16

本文是 `backend/app/workflows/` 的代码侧唯一权威结构文档。后续所有 workflow 相关新增代码都必须以这里为准。

## 1. 目标

`workflows/` 现在是后端唯一业务层。

推荐依赖方向：

```text
api -> workflows -> repositories / shared.infra / models / schemas
```

这意味着：

- `api/` 只接 HTTP、依赖注入、请求响应转换、SSE Response 包装
- `workflows/` 负责业务用例、图编排、模块级协调
- `shared.infra/` 只负责基础设施
- `app/services` 只保留迁移期兼容，不再作为新增代码的正式落点
- `app/teaching` 源层已移除，教学语义分别归位到 `digest/_shared`、`support/teaching_tools` 与 `shared.infra.tools`

## 2. 顶层分区

`workflows/` 顶层分成两类模块：

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

## 3. Engine 模块模板

每个引擎模块根目录允许存在：

```text
workflows/<module>/
  __init__.py
  README.md
  application/
  <lane_a>/
  <lane_b>/
  _shared/                 # 可选，仅在真实跨链路复用时建立
```

### 3.1 `application/` 的职责

- 承接原 `app.services` 中面向 API 的业务用例
- 负责组合多条链路
- 负责模块级协调逻辑，例如：
  - build lock
  - background task
  - SSE 事件装配
  - 状态汇总与结果返回

明确禁止：

- 不在 `application/` 里写 graph node
- 不在 `application/` 里放 prompt 模板
- 不在 `application/` 里直接堆基础设施实现

### 3.2 模块根禁止新增

- 模块级 `services/`
- 模块级 `prompts/`
- 模块级 `nodes/`
- 模块级 `runtime/`
- 模块级 `internal/`

迁移期兼容文件可以保留，但只能作为 shim，不能再作为新代码的 canonical 落点。

## 4. Engine 链路模板

每条链路目录都遵循同一骨架：

```text
workflows/<module>/<lane>/
  __init__.py
  README.md
  graph.py
  state.py
  nodes/
  prompts/
  lib/
  events.py                # 可选，仅当存在明确订阅方时保留
```

### 4.1 各层职责

- `graph.py`
  唯一图执行入口。负责：
  - `build_<lane>_graph(...)`
  - `create_<lane>_initial_state(...)`
  - `run_<lane>_workflow(...)`
  - 路由函数和 `Send` 编排
- `state.py`
  定义内部 `TypedDict State`，必要时同时放输入输出投影类型
- `nodes/`
  图上的顶层节点。一个节点一个文件
- `prompts/`
  prompt builder / template，不放节点逻辑
- `lib/`
  节点内部调用的子逻辑，例如 `writer.py`、`publish.py`、`grounding.py`
- `events.py`
  严格可选，只有存在明确订阅方时才保留

### 4.2 链路目录明确禁止

- `runner.py`
- `contracts.py`
- `runtime/`
- `internal/`
- `services/`

含义：

- 对外入口收口到 `graph.py`
- 业务子逻辑统一收口到 `lib/`
- 不再堆叠多层近义目录

## 5. Support 模块模板

`workflows/support/*` 不强制采用 graph/lane 结构，默认模板是：

```text
workflows/support/<module>/
  __init__.py
  README.md
  commands.py
  queries.py
  streams.py               # 可选
  lib/                     # 可选
```

适用模块包括：

- `auth`
- `files`
- `subjects`
- `system`
- `export_import`
- `teaching_tools`

规则：

- support 模块默认不用 LangGraph
- 如果需要长链 AI 流程，只调用已有 engine 链路
- 不在 support 里平行复制五大引擎的能力

### 5.1 `teaching_tools` 分类规则

`teaching_tools` 不是新的独立教学层，而是跨引擎复用的业务工具集合。

- 教学工具注册、枚举、执行、registry sync 属于基础设施，放在 `app.shared.infra.tools.teaching_registry`
- 需要暴露给 agent registry、且可被多个引擎复用的教学原子函数，放在 `workflows/support/teaching_tools`
- 只服务单条链路的教学逻辑，放在对应 lane 的 `nodes/` 或 `lib/`
- 只服务 Digest 文档生成的教学表达块，放在 `workflows/digest/_shared/pedagogy`
- 禁止为了“教学语义”重新创建 `app/teaching` 层

## 6. `_shared/` 规则

只有被两条及以上链路真实复用的内容，才允许进入模块 `_shared/`

允许进入 `_shared/` 的典型内容：

- Digest 的 contracts / models / prepare / pedagogy facade
- Ingest 的 parsing / recovery / logging

不应进入 `_shared/` 的内容：

- 只有一条链路使用的 helper
- 单个节点的 prompt
- 只为了“可能复用”而提前上提的代码

## 7. 命名规范

### 7.1 图与用例

- graph builder：`build_<lane>_graph`
- workflow runner：`run_<lane>_workflow`
- application 文件：按 use case 命名，例如 `build_plans.py`、`builds.py`

### 7.2 节点与文件

- 节点名：小写蛇形，例如 `load_context`
- node builder：`build_<node_name>_node`
- 节点文件名：`load_context.py`
- prompt 文件名：`load_context.py`、`write_chapters.py`
- `lib/` 文件按主题命名：`publish.py`、`writer.py`、`grounding.py`

迁移期允许保留旧文件名兼容层，例如 `_node.py`、`internal/`，但新代码不再继续依赖这些命名。

## 8. 当前模块落位

### 8.1 digest

```text
digest/
  __init__.py
  README.md
  application/
  planner/
  docgen/
  knowledge_graph/
  unified/
  _shared/
```

说明：

- `planner/` 与 `docgen/` 是当前优先收口的主链路
- `application/` 是 Digest 未来承接 planner/docgen API-facing 用例的位置
- `_shared/` 目前除了 contracts/models/prepare，还承接 runtime_config 与 pedagogy facade

### 8.2 ingest

```text
ingest/
  __init__.py
  README.md
  fast_parse/
  deep_enhance/
  _shared/
```

说明：

- `fast_parse/` 与 `deep_enhance/` 是真实链路
- 模块根旧 `graph.py / runtime / state.py` 仍作为兼容层保留

### 8.3 interact

```text
interact/
  __init__.py
  README.md
  chat/
```

说明：

- `chat/` 是 canonical lane
- 后续 API-facing 用例进入 `interact/application/`

### 8.4 examine

```text
examine/
  __init__.py
  README.md
  question_build/
  exam_grade/
  _shared/                 # 未来确有复用时再建立
```

### 8.5 profile

```text
profile/
  __init__.py
  README.md
  application/
  pipeline/
```

### 8.6 support

```text
  support/
    __init__.py
    README.md
    files/
    system/
    teaching_tools/
```

说明：

- `support/` 是新正式分区
- 当前已落地 `files/`、`system/` 与 `teaching_tools/` 作为 support 模块模板示例

## 9. 当前最重要的兼容规则

- `workflows` 业务链路与 application 新代码不再直接 import `app.services.*`
- `workflows` 业务链路与 application 新代码不再直接 import `app.teaching.*`
- `digest/_shared/runtime_config.py` 与 `digest/_shared/pedagogy/` 是真实实现落点，不再委托 `app.teaching`
- 旧 `services/` 只保迁移期 shim；已迁移且确认无调用的小 service 直接删除，不再补旧路径 shim
- `teaching/` 源层已删除，任何新代码不得恢复该目录或导入面
- 如果新业务代码仍然跨回旧层，视为结构违规

## 10. 一句话总结

`workflows` 的未来结构可以压缩成一句话：

- 五大引擎：`application + lanes + _shared`
- 支撑业务：`support/<module> = commands + queries (+ streams/lib)`
