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
- `app/services` 源层已移除，不再作为代码落点或兼容入口
- `app/teaching` 源层已移除，教学语义分别归位到 `digest/common`、具体 workflow lane 或 `shared.infra.tools`

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
  events.py                 # 可选，模块级事件
  exports.py                # 可选，LangGraph dev/export 入口
  <use_case_a>.py           # 可选，模块级聚合用例
  <lane_a>/
  <lane_b>/
  common/                  # 仅当 >=2 条链路真实复用时才建立
  application/             # 仅迁移兼容时保留
```

模块根用例文件 / `events.py` / `exports.py` 的职责：

- 承接模块级 API-facing 用例
- 组合多条链路
- 处理 build lock、background task、SSE 事件装配、状态汇总与结果返回等模块级协调

`application/` 的职责现在只剩两种：

- 历史迁移兼容
- 把旧导入路径转发到新的 canonical 模块根或 lane 文件

模块根禁止新增：

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

各层职责：

- `graph.py` 是唯一图执行入口，负责 graph builder、初始状态构造、路由函数和 `Send` 编排
- `state.py` 定义内部 `TypedDict State`，必要时同时放输入输出投影类型
- `nodes/` 放图上的顶层节点，一个节点一个文件
- `prompts/` 放 prompt builder / template，不放节点逻辑
- `lib/` 放节点内部调用的子逻辑，例如 `writer.py`、`publish.py`、`grounding.py`
- `events.py` 严格可选，只有存在明确订阅方时才保留

链路目录明确禁止：

- `runner.py`
- `contracts.py`
- `runtime/`
- `internal/`
- `services/`

## 5. Support 模块模板

`workflows/support/*` 不强制采用 graph/lane 结构，默认模板是：

```text
workflows/support/<module>/
  __init__.py
  README.md
  <use_case_a>.py
  <use_case_b>.py
  streams.py               # 可选
  lib/                     # 可选
```

适用模块包括：

- `auth`
- `files`
- `subjects`
- `system`
- `export_import`

规则：

- support 模块默认不用 LangGraph
- 如果需要长链 AI 流程，只调用已有 engine 链路
- 不在 support 里平行复制五大引擎的能力
- 新代码优先按用例命名文件，例如 `catalog.py`、`uploads.py`、`deletion.py`
- 不保留无调用方的旧兼容壳；如确需兼容，必须先有真实外部调用方

## 6. Teaching Tool 规则

teaching tool 不是新的独立教学层。当前通用实现是内置 tool，不单独占用 `workflows/support/teaching_tools` 模块。

- 教学工具注册、枚举、执行、registry sync 属于基础设施，放在 `app.shared.infra.tools.teaching_registry`
- 通用内置教学工具实现放在 `app.shared.infra.tools.builtin.teaching_tools`
- 只服务单条链路的教学逻辑，放在对应 lane 的 `nodes/` 或 `lib/`
- 只服务 Digest 文档生成的教学表达块，放在 `workflows/digest/common/pedagogy`
- 禁止为了“教学语义”重新创建 `app/teaching` 层

## 7. 模块级 `common/` 规则

只有被两条及以上链路真实复用的内容，才允许进入模块级 `common/`。

允许进入模块级 `common/` 的典型内容：

- Digest 的共享 contracts / models / prepare
- Digest 的跨链路 metrics 基础模型与 token / slow-item 汇总
- Ingest 的共享 parsing / recovery / logging

不应进入模块级 `common/` 的内容：

- 只有一条链路使用的 helper
- 单个节点的 prompt
- 只为了“可能复用”而提前上提的代码
- 链路自己的 reporting / summary builder，这类应放回对应链路 `lib/`

注意：`workflows/<module>/common/` 是模块内共享层；真正的全局共享层仍然只有 `app.shared.*`。

## 8. 命名与进度规则

- graph builder：`build_<lane>_graph`
- workflow runner：`run_<lane>_workflow`
- application 文件：按 use case 命名，例如 `build_plans.py`、`builds.py`
- 节点名与节点文件名使用小写蛇形，例如 `load_context.py`
- prompt 文件名使用业务主题，例如 `write_chapters.py`
- `lib/` 文件按主题命名，例如 `publish.py`、`writer.py`、`grounding.py`
- planner SSE 进度主通路是 `emit_progress(...)`
- 知识构建等待页主通路是 `update_knowledge_build_status(...)` 产生的轮询状态
- reporting / metrics 只负责构建诊断摘要，不作为前端进度事件层
- `events.py` 不是标准必选层；如果没有明确订阅方，不要为了“架构完整”额外定义事件层

## 9. 当前模块落位

### 9.1 digest

```text
digest/
  __init__.py
  README.md
  events.py
  exports.py
  overview.py
  study_plan.py
  planner/
  docgen/
  knowledge_graph/
  common/
```

说明：

- `events.py`、`exports.py` 是 Digest 模块根入口
- `docgen/__init__.py`、`knowledge_graph/__init__.py` 提供 workflow runner 入口
- `overview.py`、`study_plan.py` 是 Digest 跨 lane 聚合用例
- `planner/` 与 `docgen/` 是当前优先维护的主链路
- `knowledge_graph/` 是独立图谱构建链路
- `common/` 是当前真实跨链路共享层，承载 contracts / models / prepare / material_profile / metrics / runtime_config / pedagogy 等复用能力


### 9.2 ingest

```text
ingest/
  __init__.py
  README.md
  events.py
  exports.py
  parse_files.py
  recovery.py
  fast_parse/
  deep_enhance/
  common/
    parsing/
```

说明：

- `parse_files.py`、`recovery.py`、`events.py`、`exports.py` 是 ingest 模块根用例和模块级入口
- `fast_parse/` 与 `deep_enhance/` 是真实链路
- `common/parsing/` 是当前两条链路共享的解析实现

### 9.3 interact

```text
interact/
  __init__.py
  README.md
  application/
  chat/
```

说明：

- `chat/` 是唯一真实链路，真实实现已收口到 `chat/`
- `application/` 承接聊天列表、历史记录、SSE streaming 外壳等 API-facing 用例
- 根目录旧 `graph.py / runtime.py / state.py / nodes/ / prompts/ / support/` 作为兼容层保留

### 9.4 examine

```text
examine/
  __init__.py
  README.md
  application/
  question_build/
  exam_grade/
  common/                  # 未来确有复用时再建立
```

### 9.5 profile

```text
profile/
  __init__.py
  README.md
  application/
  pipeline/
```

### 9.6 support

```text
support/
  __init__.py
  README.md
  auth/
  export_import/
  files/
  system/
  subjects/
```

## 10. 当前最重要的兼容规则

- `workflows` 业务链路与 application 新代码不再直接 import `app.services.*`
- `workflows` 业务链路与 application 新代码不再直接 import `app.teaching.*`
- 旧 `services/` 源层已删除，不再补旧路径 shim
- `teaching/` 源层已删除，任何新代码不得恢复该目录或导入面
- 如果新业务代码仍然跨回旧层，视为结构违规

## 11. 一句话总结

- 五大引擎：`module root use cases + lanes + common`
- Digest 教学语义：`common/runtime_config.py + common/pedagogy/`
- 支撑业务：`support/<module> = use-case files (+ streams/lib)`
