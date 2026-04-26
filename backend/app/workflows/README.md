# Workflows 说明

最后更新：2026-04-19

`backend/app/workflows/` 是 AITeachMe 后端当前唯一的业务层。这里承接五大引擎的 workflow 编排，也承接直接面向 API 的业务用例。

这份文档是 workflow 层的硬约束。新增或重构 workflow 时，先按这里判断文件该放哪里，再看具体 lane 的 README。

## 先看什么

- 调试方式：[DEBUGGING.md](./DEBUGGING.md)
- 进度事件约定：[PROGRESS.md](./PROGRESS.md)

## 当前分区

### 五大引擎

- `ingest`
- `digest`
- `interact`
- `examine`
- `profile`

### 支撑业务

- `support`

`support/` 承接不属于五大引擎、但仍属于后端业务层的模块，例如 `system`、`auth`、`subjects`、`export_import`。

## 模块根目录规则

五大引擎模块根目录只允许做“稳定导入面 + README + lane/明确共享包聚合”：

```text
workflows/<module>/
  __init__.py
  README.md
  <lane_a>/
  <lane_b>/
  common/                  # 仅当 >=2 条链路真实复用且没有更明确命名时才建立
```

模块根 `__init__.py`：

- 只提供稳定导入面。
- 可以懒加载并转发到真实 lane 或明确共享包。
- 不承载业务实现。
- 不创建 workflow context。
- 不跑图。
- 不读写数据库。

模块根禁止新增：

- 模块级 `services/`
- 模块级 `application/`
- 模块级 `prompts/`
- 模块级 `nodes/`
- 模块级 `runtime/`
- 模块级 `internal/`
- 模块级 `events.py`
- 模块级 `exports.py`
- 模块级 use-case `.py`

所有业务用例、事件、workflow export 均必须进入对应 lane 或模块级 `common/`。

## Canonical 链路

当前稳定链路如下：

- `ingest/intake`
- `ingest/fast_parse`
- `digest/planner`
- `digest/docgen`
- `digest/kg_doc_sync`
- `interact/chat`
- `examine/question_build`
- `examine/exam_grade`
- `profile/pipeline`

如果新增链路，必须先判断它属于现有引擎子 lane，还是属于 `support/` 的 API-facing 用例。不要为了一个函数新增顶层目录。

## 标准 Lane 结构

除非已有 lane 有明确不同约定，新 workflow lane 默认采用 `digest/planner` 风格：

```text
lane_name/
  __init__.py          # 稳定导入面，只导出，不写业务运行逻辑
  graph.py             # LangGraph 定义、初始 state、路由、单次运行入口
  state.py             # TypedDict / Pydantic state 合同
  nodes/               # 顶层 LangGraph 节点
  lib/                 # 节点内部复用逻辑、运行时、模型转换、持久化辅助
  prompts/             # prompt builder / template
  README.md / FLOW_DESIGN.md   # 本 lane 的主文档
```

可选文件：

- `inputs.py`：只有当 lane 需要独立的输入解析/文件定位时才添加。
- `workflow.py`：默认不添加。只有非 LangGraph 的专用封装、且放进 `graph.py` 会明显破坏可读性时才允许。
- `runtime.py`：默认不添加。优先放 `lib/<明确职责>.py`。
- `reporting.py`：只放该 lane 的摘要和指标收口。

## 文件职责硬约束

### `__init__.py`

只做稳定导出面：

- 可以导出 `build_*_graph`、`run_*_workflow`、API 需要的稳定函数、少量核心类型。
- 不写业务流程、不创建 context、不跑图、不读写数据库。
- 不导出一整个 `lib/` 的大杂烩。
- 不为了保留历史路径写空壳函数。

### `graph.py`

承接 LangGraph 主结构：

- 定义节点常量、`build_*_graph`、`create_*_initial_state`。
- 定义条件路由和 `Send` fan-out / fan-in。
- 默认承接单次 `run_*_workflow` 入口，对齐 `digest/planner`。
- 可以写 `get_langgraph_dev_*_graph()`，仅用于 `langgraph dev` / 图可视化调试。
- 不写 API 参数选择、构建锁、后台任务调度、文件上传逻辑。

### `state.py`

只描述图内 state 合同：

- 写清 graph input、工作中间产物、fan-out 临时字段、reducer 聚合字段、最终 output。
- 不写 HTTP schema。
- 不写 DB model。
- 不放业务函数。

### `nodes/`

只放 LangGraph 顶层节点：

- 一个文件对应一个节点或一组强相关节点。
- 节点负责组装 state、调用 `lib/`、写进度事件、返回 state patch。
- 节点里不要堆复杂算法、prompt 拼接、数据库查询细节。
- 节点名要能直接映射 README / FLOW_DESIGN 里的流程名。

### `lib/`

放节点内部复用逻辑：

- 适合放运行时、模型转换、质量评估、发布辅助、持久化辅助、状态摘要。
- 小而同责的文件要合并，不要每个小函数都单独成文件。
- 大文件必须有清晰单一职责，文件头写清“谁调用它、它负责什么、不负责什么”。
- 不要把 `lib/__init__.py` 做成全量导出聚合，只导出常用稳定 facade。

### `prompts/`

只放 prompt builder：

- prompt builder 只拼 messages / prompt，不直接调 LLM。
- prompt builder 要保留输入摘要和输出 trace，方便 LangSmith 里检查提示词。
- 大段 prompt 要有预算常量，避免调用点散落魔法数字。
- 多个文件只是 re-export 时要合并，避免 `write_chapters.py` 这种只转发的空层。

### 主文档 / 设计文档

每个核心 lane 必须至少保留一份主文档。默认是 `README.md`；复杂 lane 也可以直接用 `FLOW_DESIGN.md` 兼任入口说明和流程权威文档：

- 主文档写当前真实主线、目录边界、公开入口和阅读顺序。
- 如果存在独立流程设计文档，它负责短流程和长合同。
- 如果 `FLOW_DESIGN.md` 已经兼任主文档，就不要再维护第二份平行 README。
- 改 graph 时同步改 lane 的主文档。
- 文档不得描述已经移除的主线为当前实现。

## Support 模块结构

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
- `subjects`
- `system`
- `export_import`

规则：

- support 模块默认不用 LangGraph。
- 如果需要长链 AI 流程，只调用已有 engine lane。
- 不在 support 里平行复制五大引擎的能力。
- 新代码优先按 use case 命名文件，例如 `catalog.py`、`sessions.py`、`settings.py`、`deletion.py`。
- 不保留无调用方的旧壳；如确需兼容，必须先有真实外部调用方。

## 模块级 `common/` 规则

只有被两条及以上链路真实复用的内容，才允许进入模块级 `common/`。

允许进入模块级 `common/` 的典型内容：

- Digest 的共享 contracts / models / prepare。
- Digest 的跨链路 metrics 基础模型与 token / slow-item 汇总。
- Ingest 的解析适配优先放明确包名 `parsing/`；只有多类共享能力混在一起时才建立 `common/`。

不应进入模块级 `common/` 的内容：

- 只有一条链路使用的 helper。
- 单个节点的 prompt。
- 只为了“可能复用”而提前上提的代码。
- 链路自己的 reporting / summary builder，这类应放回对应链路 `lib/`。

注意：`workflows/<module>/common/` 是模块内共享层；真正的全局共享层仍然只有 `app.shared.*`。

## Teaching Tool 规则

teaching tool 不是新的独立教学层。当前通用实现是内置 tool，不单独占用 `workflows/support/teaching_tools` 模块。

- 教学工具注册、枚举、执行、registry sync 属于基础设施，放在 `app.shared.infra.tools.teaching_registry`。
- 通用内置教学工具实现放在 `app.shared.infra.tools.builtin.teaching_tools`。
- 只服务单条链路的教学逻辑，放在对应 lane 的 `nodes/` 或 `lib/`。
- 只服务 Digest 文档生成的教学表达块，放在 `workflows/digest/common/pedagogy.py`。
- 禁止为了“教学语义”重新创建 `app/teaching` 层。

## 文件头说明

`workflows/` 下新增 Python 文件必须有模块 docstring，第一行就说明这个文件的作用。

推荐写法：

```python
"""DocGen graph definition and runtime entrypoint.

这里定义 LangGraph 节点、fan-out/fan-in 路由和单次运行入口。
构建锁、后台任务和 API 参数选择不在这里处理。
"""
```

最低要求：

- 文件做什么。
- 谁调用它或它服务哪个流程。
- 它不负责什么，尤其是容易被误塞进来的职责。

不接受：

- 没有文件头。
- 只有 `"""Helpers."""` 这种无信息量描述。
- 文件名和文件头表达的职责不一致。

## 公开入口

上层依赖模块级稳定入口：

```python
from app.workflows.ingest import run_parse_file_workflow
from app.workflows.digest import run_docgen_workflow
from app.workflows.digest.planner import run_build_planner_workflow
from app.workflows.interact import stream_chat_workflow
```

如果要看图结构，再进入各链路目录看 `graph.py`。API 层不要绕过稳定入口直接拼节点。

## 命名与可观测性

- LangGraph 节点 id 优先英文 snake_case 或稳定常量，便于定位、统计和事件映射。
- LangSmith 展示名、前端阶段文案、文档可用中文。
- 条件路由函数如果要展示中文名，用明确 helper 命名，不要散落改 `__name__` / `__qualname__`。
- 需要并行展示的阶段必须使用 LangGraph `Send` fan-out，不要只在单个节点里 `asyncio.gather`。
- Prompt builder 应在 LangSmith 中以 `run_type="prompt"` 记录，LLM 调用本身继续以 `run_type="llm"` 记录。
- 长链路必须有 timing/token summary，失败路径也要输出摘要。

## LangSmith 规范

LangSmith 是研发排障的唯一 trace 真相源。progress 只给前端展示，不是第二套 trace。LangGraph 已经负责 root / node span，我们只补上下文。

Workflow 作者只需要记住 3 个入口：

```python
from app.shared.infra.workflow import (
    invoke_state_graph,
    run_state_graph,
    workflow_tracer,
)
from langsmith import traceable
```

对应关系：

1. workflow root：用 `run_state_graph(...)` 或 `invoke_state_graph(...)`。
2. graph node：用 `workflow_tracer(...).node(handler, ...)`。
3. prompt / helper：用官方 `@traceable`，或 lane 内统一 prompt tracing helper。

标准 root 写法：

```python
result = await run_state_graph(
    workflow_name="digest.planner",
    graph_builder=lambda: build_planner_graph(context=context),
    initial_state=initial_state,
    context=context,
)
```

标准 node 写法：

```python
trace = workflow_tracer(context=context, lane="planner")

workflow.add_node(
    "load_context",
    trace.node(
        build_load_context_node(context=context),
        name="load_context",
        timing_field="load_ms",
    ),
)
```

标准 prompt 写法：

```python
@traceable(name="digest.planner.build_prompt", run_type="prompt")
def build_planner_prompt(...):
    ...
```

不要在 workflow 作者代码里直接使用：

- `traceable_run`
- `tracked_step`
- `annotate_traceable`
- `build_langsmith_extra`
- `trace_substep`
- 手写 `langsmith_trace(...)`
- 手写 `tracing_context(...)`
- 直接调用 `llm_trace_scope(...)`

这些能力如果还需要，应该留在 `shared/infra/**` 的 infra-private 边界。

推荐心智模型：

```text
workflow root   -> run_state_graph / invoke_state_graph
workflow node   -> workflow_tracer().node(handler, ...)
prompt/helper   -> @traceable / lane prompt tracing helper
frontend 进度   -> 看 PROGRESS.md
```

## 依赖方向

推荐依赖方向：

```text
api -> workflows -> repositories / shared.infra / models / schemas
```

约束：

- `workflows` 可以调用 repositories、models、schemas、shared.infra。
- repositories 不反向依赖 workflows。
- shared.infra 不依赖具体 workflow lane。
- workflow lane 之间不要互相深层 import；跨 lane 共用能力放对应 `common/`。
- `app/services` 和 `app/teaching` 不是代码落点。

## 兼容规则

- `workflows` 业务链路与 application 新代码不再直接 import `app.services.*`。
- `workflows` 业务链路与 application 新代码不再直接 import `app.teaching.*`。
- `services/` 源层已删除，不补旧路径 shim。
- `teaching/` 源层已删除，任何新代码不得恢复该目录或导入面。
- 如果新业务代码仍然跨回已删除源层，视为结构违规。

## Digest 特别约束

`digest/` 当前主线是：

```text
planner -> docgen -> kg_doc_sync
```

旧 `digest/kg_file_ingest` 历史调试包已删除；图谱构建只保留 `digest/kg_doc_sync`，
抽取、候选合并、增量入图、查询、总览和清理实现都位于 `digest/kg_doc_sync/`。

`digest/planner` 是组织样板：

- `graph.py` 定义图和 `run_build_planner_workflow`。
- `__init__.py` 只导出稳定入口。
- `state.py` 保持小而清楚。
- `nodes/` 只放 LangGraph 节点。
- `lib/store.py` 承接 Planner 持久化，不在节点里铺数据库细节。

`digest/docgen` 必须对齐：

- `graph.py` 定义图、Send 分发、单次 `run_docgen_workflow`。
- `lib/build_lifecycle.py` 只处理 API 触发后的构建锁、后台任务、状态和结果组装。
- `__init__.py` 只导出稳定入口。
- `FLOW_DESIGN.md` 是 DocGen 当前唯一文档文件，兼任入口说明和流程权威文档。
- 不新增 `workflow.py` 作为默认入口。
- 复杂质量逻辑优先收口到同责文件，例如 `lib/quality.py`。

## 当前已落地的单层化示例

- `ingest/__init__.py`、`digest/__init__.py`
  引擎模块根只保留稳定导入面，不承载业务实现
- `digest/planner/graph.py`
  Planner 图定义和单次运行入口
- `digest/docgen/graph.py`
  DocGen 图定义、章节生成/复核 fan-out 和单次运行入口
- `digest/docgen/lib/build_lifecycle.py`
  DocGen 构建触发、状态装配与后台编排入口
- `digest/docgen/lib/quality.py`
  DocGen evidence / claim / conflict / review report 质量收口
- `digest/common/events.py`、`digest/common/exports.py`
  Digest 跨链路事件与 workflow export 落点
- `digest/common/runtime_config.py`
  Digest 教学运行时配置 facade
- `digest/common/pedagogy.py`
  Digest 文档教学语义 helper
- `digest/kg_doc_sync/lib/overview.py`
  基于知识图谱的总览用例
- `support/system/init.py`、`support/system/settings.py`
  系统初始化与设置总览位置
- `ingest/intake/catalog.py`、`ingest/intake/uploads.py`、`ingest/intake/parse_dispatch.py`、`ingest/intake/deletion.py`
  文件模块按用例拆分后的位置
- `profile/pipeline/lib/`
  Profile 的掌握度、复习调度、画像摘要与报告建议 helper 落点
- `interact/chat/use_cases.py`
  Interact 面向 API 的聊天会话、历史记录与 SSE streaming 外壳落点
- `support/auth/identity.py`、`support/auth/sessions.py`、`support/auth/smtp.py`
  鉴权模块按身份、会话、邮件通道拆分后的位置
- `support/export_import/exports.py`、`support/export_import/imports.py`、`support/export_import/courses.py`
  学科级课程包导入导出模块按用例拆分后的位置

## 新增或重构前检查

动手前先回答：

1. 这是五大引擎 lane，还是 `support/` 用例？
2. 是否已有 lane 能承接，还是确实需要新目录？
3. 运行入口是否应该在 `graph.py`？
4. `__init__.py` 是否只是导出？
5. 复杂逻辑是否已经从 node 下沉到 `lib/`？
6. prompt 是否只在 `prompts/`，且有 trace？
7. 是否需要 `Send` fan-out 才能在 LangSmith 看到并行？
8. lane 主文档 / FLOW_DESIGN 是否同步更新？
9. 新文件是否有清晰文件头说明？

这份 README 是 workflow 层唯一结构规范入口；不要再把结构或 LangSmith 规则拆到新文档里。
