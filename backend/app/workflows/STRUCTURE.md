# Workflows 结构规范

最后更新：2026-04-15

本文是 `backend/app/workflows/` 的唯一权威结构文档。后续所有 workflow 模块都以这里为准收口。

## 1. 目标

`workflows/` 负责组织业务编排，不负责承载 HTTP、数据库仓储、通用基础设施或教学原子能力本身。

推荐依赖方向：

```text
api -> services -> workflows -> teaching -> shared.infra -> shared.kernel
```

核心原则只有三条：

1. 同一职责永远落在同一位置。
2. 没有独立职责的层，不要为了对称硬造一层。
3. 模块根只做聚合，链路目录才是唯一执行单元。

## 2. 标准模板

### 2.1 多链路模块

适用于 `digest`、`ingest`、`examine` 这类一个模块下包含多条独立 workflow 链路的场景。

```text
workflows/<module>/
  __init__.py
  README.md
  <lane_a>/
  <lane_b>/
  _shared/                 # 仅当 >=2 条链路真实复用时才建立
```

模块根允许存在的内容：

- `__init__.py`
- `README.md`
- 各链路目录
- 可选 `_shared/`
- 兼容层文件：仅用于迁移期保留旧导入面，例如旧的 `graph.py`、`runtime.py`

模块根不再作为新增代码的落点：

- 不再新增模块级 `prompts/`
- 不再新增模块级 `nodes/`
- 不再新增模块级 `exports.py`
- 不再新增模块级 `events.py`
- 不再新增模块级 `services/`

### 2.2 单链路模块

适用于 `interact`、`profile` 这类对外看起来是一个模块，但内部只有一条真实执行链路的场景。

```text
workflows/<module>/
  __init__.py
  README.md
  <lane>/
```

当前标准：

- `interact/chat/`
- `profile/pipeline/`

## 3. 链路模板

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
  events.py                # 可选，仅当存在明确订阅方时才保留
```

### 3.1 各层职责

- `__init__.py`
  对外稳定门面，只做 re-export。
- `README.md`
  说明这条链路做什么、有哪些节点、上层该从哪里调用。
- `graph.py`
  唯一的图执行入口。负责：
  - `build_<lane>_graph(...)`
  - `create_<lane>_initial_state(...)`
  - `run_<lane>_workflow(...)`
  - 路由函数和 `Send` 编排
- `state.py`
  定义这条链路的内部 `TypedDict State`，必要时同时放 Studio 输入输出投影类型和对外公开 DTO。
- `nodes/`
  图上的顶层节点。一个节点一个文件。
- `prompts/`
  只放 prompt builder / template，不放节点逻辑。
- `lib/`
  节点内部调用的子逻辑，例如 `writer.py`、`publish.py`、`grounding.py`。
- `events.py`
  严格可选。只有存在明确消费方时才保留。

### 3.2 明确禁止

链路目录不再新增这些层：

- `runner.py`
- `contracts.py`
- `runtime/`
- `internal/`
- `services/`

含义很明确：

- 执行入口收回 `graph.py`
- 对外类型收回 `state.py`
- 业务子逻辑统一收回 `lib/`

## 4. 命名规范

### 4.1 图与节点

- graph builder：`build_<lane>_graph`
- workflow runner：`run_<lane>_workflow`
- 节点名：小写蛇形，例如 `load_context`
- node builder：`build_<node_name>_node`

### 4.2 文件名

- 节点文件名与节点名一致：`load_context.py`
- prompt 文件名与对应节点一致：`load_context.py`
- `lib/` 文件按主题命名：`publish.py`、`writer.py`、`grounding.py`

迁移期允许保留旧文件名兼容层，例如 `_node.py`、`internal/`，但新代码不再继续依赖它们。

## 5. `_shared/` 规则

只有被两条及以上链路真实复用的内容，才允许进入模块 `_shared/`。

允许进入 `_shared/` 的典型内容：

- digest 的共享 contracts / models / prepare
- ingest 的共享 parsing / recovery / logging

不应进入 `_shared/` 的内容：

- 只有一条链路使用的 helper
- 单个节点的 prompt
- 只为了“可能复用”而提前上提的代码

## 6. 事件与进度

当前默认规则：

- 前端进度展示主通路是 `emit_progress(...)`
- `events.py` 不是标准必选层
- 如果没有明确订阅方，不要为了“架构完整”额外定义事件层

## 7. 当前模块落位

### 7.1 digest

```text
digest/
  __init__.py
  README.md
  planner/
  docgen/
  knowledge_graph/
  unified/
  _shared/
```

说明：

- `planner/` 与 `docgen/` 是当前优先收口的主链路
- `knowledge_graph/` 与 `unified/` 先对齐门面与命名
- 历史 `shared/` 仍保留兼容；新代码优先走 `_shared/`

### 7.2 ingest

```text
ingest/
  __init__.py
  README.md
  fast_parse/
  deep_enhance/
  _shared/
```

说明：

- `run_parse_file_workflow(...)` 仍保留在模块层，作为跨两条链路的稳定入口
- `fast_parse/` 与 `deep_enhance/` 是真实链路
- 历史 `parsing/`、`recovery.py` 保留兼容；新代码优先走 `_shared/`

### 7.3 interact

```text
interact/
  __init__.py
  README.md
  chat/
```

说明：

- `chat/` 是 canonical lane
- 根目录旧 `graph.py / runtime.py / state.py / support/` 作为兼容层保留

### 7.4 examine

```text
examine/
  __init__.py
  README.md
  question_build/
  exam_grade/
  _shared/                 # 未来确有复用时再建立
```

说明：

- `question_build/` 和 `exam_grade/` 是两条真实链路
- 历史平铺文件先保留兼容导入面，逐步收口

### 7.5 profile

```text
profile/
  __init__.py
  README.md
  pipeline/
```

说明：

- `pipeline/` 是唯一真实链路
- 根目录旧 `graph.py / runtime.py / state.py` 保留兼容导入面

## 8. 示例

### 8.1 planner

```text
digest/planner/
  __init__.py
  README.md
  graph.py
  state.py
  nodes/
    load_context.py
    ground_concepts.py
    draft_plan.py
  prompts/
    draft_plan.py
  lib/
    grounding.py
    plans.py
```

### 8.2 docgen

```text
digest/docgen/
  __init__.py
  README.md
  graph.py
  state.py
  nodes/
    load_context.py
    research_chapters.py
    merge_research.py
    finalize_titles.py
    write_chapters.py
    merge_drafts.py
    enrich_assets.py
    append_practice.py
    publish_document.py
  prompts/
    research_chapters.py
    finalize_titles.py
    write_chapters.py
    assets.py
  lib/
    chapter_context.py
    query_planning.py
    writer.py
    assets.py
    publish.py
```

## 9. 迁移策略

当前采用渐进式兼容迁移：

1. 先建立 canonical lane 目录。
2. 模块根改为指向 canonical lane 的薄门面。
3. `langgraph.json` 切到 canonical lane 的 `graph.py`。
4. 文档改为只描述新骨架。
5. 历史文件逐步降级为兼容层，最后再清理。

## 10. 一句话总结

`workflows` 的未来结构只有一句话：模块根只聚合，链路目录才执行；链路里固定是 `graph.py + state.py + nodes/ + prompts/ + lib/`，`events.py` 仅在确实需要时才出现。
