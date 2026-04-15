# Workflows 说明

最后更新：2026-04-15

`backend/app/workflows/` 是业务编排层，负责把教学目标、领域规则和基础设施能力组织成可运行的 workflow。

推荐依赖方向：

```text
api -> services -> workflows -> teaching -> shared.infra -> shared.kernel
```

## 一句话边界

- `workflows`
  决定“这条业务流程怎么跑”
- `teaching`
  决定“怎么教、怎么表达”
- `shared.infra`
  提供 LLM、search、retriever、storage、workflow runtime、observability 等基础能力

不要在 `workflows` 里再复制一套：

- tracing 系统
- progress 生命周期框架
- tool registry
- execution 抽象框架
- 底层存储 / 搜索接入

## 当前最重要的主链路

对当前产品来说，知识文档主链路是：

```text
api/knowledge_docs.py
-> services/knowledge_docs/build_planner_service.py
-> app.workflows.digest.planner
-> confirmed_plan
-> services/knowledge_docs/digest_service.py
-> app.workflows.digest.run_docgen_workflow
```

可以拆成两个阶段理解：

1. `planner`
   把用户目标和资料整理成一个可确认的构建方案
2. `docgen`
   基于 confirmed plan 执行正式文档构建

## workflow 作者现在只需要记住的入口

```python
from app.shared.infra.workflow import (
    emit_progress,
    invoke_state_graph,
    project_typed_dict_schema,
    run_state_graph,
    workflow_tracer,
)
from langsmith import traceable
```

对应分工：

- `run_state_graph(...)` / `invoke_state_graph(...)`
  workflow root 入口
- `workflow_tracer(...).node(handler, ...)`
  graph node 的统一接线方式
- `emit_progress(...)`
  前端进度事件
- `project_typed_dict_schema(...)`
  从主 `State` 投影出精简的 LangGraph Studio input/output schema
- `@traceable`
  prompt / helper / 小范围子逻辑 tracing

进一步说明：

- LangSmith 规范看 [LANGSMITH.md](./LANGSMITH.md)
- 前端进度规范看 [PROGRESS.md](./PROGRESS.md)
- 本地调试方式看 [DEBUGGING.md](./DEBUGGING.md)
- 目录结构规范看 [STRUCTURE.md](./STRUCTURE.md)
- planner 包内规范看 [digest/planner/README.md](./digest/planner/README.md)
- docgen 包内规范看 [digest/docgen/README.md](./digest/docgen/README.md)

## 现在的观测层原则

仓库已经收口成两层语义：

- `LangSmith trace`
  给研发排障
- `progress`
  给前端展示

不要再引入第三套“本地 step trace / track 生命周期”。

尤其注意：

- LangSmith / LangGraph 原生已经会记录 span 层级和执行时间
- 我们不应该再在 workflow 层重复维护一套 node/span 计时语义
- 如果前端需要当前阶段，就发 `emit_progress(...)`
- 如果研发需要定位 prompt / retriever / tool 问题，就看 LangSmith

## LangGraph Studio 的约束

Studio 很适合做 graph 调试，但不要把整个内部 state 都暴露给它。

当前推荐模式是：

1. workflow 内部维护一个完整 `State`
2. 如果需要给 Studio 收口表单，再从主 `State` 投影出精简的 `input_schema` / `output_schema`
3. 不要为了 Studio 手写三份重复类型

典型写法：

```python
class ExampleState(TypedDict, total=False):
    subject: str
    file_ids: list[int]
    plan: dict[str, Any]
    error: str | None


ExampleGraphInput = project_typed_dict_schema(
    ExampleState,
    name="ExampleGraphInput",
    fields=["subject", "file_ids"],
)

ExampleGraphOutput = project_typed_dict_schema(
    ExampleState,
    name="ExampleGraphOutput",
    fields=["plan", "error"],
)
```

这意味着：

- `State` 仍然是唯一真相源
- graph schema 只声明“要暴露哪些字段”
- 不再重复维护第二第三份字段类型定义

## `exports.py` 现在怎么理解

如果现在主要用 `langgraph dev` / Studio 看图，那么：

- `exports.py` 不是 workflow 标准链路必需文件
- `exports.py` 也不是 `langgraph dev` 的依赖入口
- 真正的开发调试入口是 `backend/langgraph.json` 里的 graph 注册

`exports.py` 现在只保留一个可选职责：

- 给离线图文导出脚本提供补充元信息
- 例如更友好的标题、描述、prompt 指纹、动态边的显示覆盖

也就是说：

- 日常开发看图，优先 `langgraph dev`
- 只有你们明确需要生成静态 Mermaid / Markdown 架构文档时，才需要 `exports.py`

如果一个 workflow 没有静态导出需求，可以没有 `exports.py`。

## workflow 标准链路最少需要什么

对一个正常的 workflow 包，最少推荐保留这些文件：

| 文件 | 是否必需 | 作用 |
| --- | --- | --- |
| `__init__.py` | 必需 | 对外稳定入口 |
| `state.py` | 必需 | graph state 定义 |
| `graph.py` | 必需 | LangGraph 图定义 |
| `runtime.py` | 必需 | 运行入口，负责 root 调用与初始 state |

然后按复杂度再决定是否拆出：

| 目录或文件 | 是否常见 | 作用 |
| --- | --- | --- |
| `prompts/` | 常见 | workflow 专属 prompt builder / 模板 |
| `nodes/` | 中大型 workflow 强烈推荐 | 把每个 node handler 单独拆文件 |
| `runtime/` | 中大型 workflow 常见 | workflow-local runtime helper |
| `services/` | 可选 | 仅限本 workflow 内部复用的服务逻辑 |
| `routes.py` / `routers.py` | 可选 | 复杂条件路由单独抽离 |
| `models.py` | 可选 | payload / draft / normalize / contract |
| `exports.py` | 可选 | 仅给离线图文导出脚本 |

## 模块层、链路层、实现层

建议把 `workflows` 目录按三层来理解：

### 1. 模块层

模块层回答的是：

- 这是哪个引擎
- 对外稳定入口是什么
- 这个引擎下面有哪些子链路

例如：

- `digest/`
- `ingest/`
- `interact/`
- `examine/`
- `profile/`

### 2. 链路层

链路层回答的是：

- 这条 workflow 主链怎么跑
- 这条子链的 graph、state、runtime 入口在哪

例如在 `digest/` 下：

- `planner/`
- `docgen/`
- `kg/`
- `curriculum/`
- `unified/`

也就是说：

- 模块层是“哪个引擎”
- 链路层是“这个引擎下的哪条具体 workflow”

### 3. 实现层

实现层回答的是：

- 这条链路里的 node、prompt、局部 runtime、局部 service 分别在哪

常见目录就是：

- `nodes/`
- `prompts/`
- `runtime/`
- `services/`
- `models.py`

推荐理解方式：

```text
模块层    -> digest / ingest / interact / examine / profile
链路层    -> planner / docgen / kg / curriculum / unified
实现层    -> nodes / prompts / runtime / services / models
```

## `prompts/`、`nodes/`、`runtime/` 应该怎么分

### `prompts/`

放这些内容：

- prompt builder
- prompt 常量
- message 拼装 helper

不要放：

- graph 路由
- 节点副作用
- 数据库 / 检索调用

### `nodes/`

放这些内容：

- 一个 graph node 的 handler 构造函数
- 节点内的直接业务编排逻辑
- 节点级 progress 发射

推荐原则：

- graph 里的 node 名，尽量和这里的文件名 / builder 名一致
- 例如 graph 里叫 `research_chapters`，文件最好也叫 `research_chapters_node.py`

### `runtime/`

放这些内容：

- workflow-local 的执行帮助器
- 会被多个 node 复用，但又不适合沉到 `shared.infra` 的能力

例如：

- chapter context 组织
- query planning
- writer runtime
- assets runtime

### `services/`

只放：

- 这个 workflow 内部的局部领域服务

不要把 `services/` 当成“什么都能塞的杂物间”。

如果某个能力已经跨 workflow 复用，应该重新评估是否该进入 `shared.infra` 或 `teaching`。

## 文件命名规范建议

为了让目录更见名知意，推荐：

- graph 节点名使用业务动作名
- node builder 名与节点名对齐
- node 文件名也与节点名对齐

推荐例子：

```text
graph node: research_chapters
builder: build_research_chapters_node(...)
file: nodes/research_chapters_node.py
```

不推荐继续长期保留这种“图里已经改名，但文件还停留在旧实现名”的状态：

```text
graph node: research_chapters
file: nodes/targeted_research_node.py
```

这种情况短期能运行，但长期会让目录结构越来越难懂。

## `digest.planner` 怎么看

稳定入口：

```python
from app.workflows.digest.planner import (
    normalize_planner_payload,
    run_build_planner_workflow,
)
```

当前 `planner/` 目录大致分工：

| 文件 | 作用 |
| --- | --- |
| `__init__.py` | planner 对外公共入口 |
| `runtime.py` | planner workflow 运行入口 |
| `graph.py` | planner graph 定义 |
| `models.py` | planner draft / payload 规范化 |
| `concept_grounding.py` | 规划前的轻量 grounding |
| `state.py` | planner graph state 与 Studio 字段投影 |

planner 当前图比较小，只有 3 个顶层节点：

- `load_context`
- `ground_concepts`
- `draft_plan`

这也是当前最适合先调的 digest workflow。

## `digest.docgen` 怎么看

当前稳定入口仍然是：

```python
from app.workflows.digest import run_docgen_workflow
```

`docgen/` 更偏内部实现目录，不是推荐给服务层直接深依赖的“公共接口面”。

目录大致分工：

| 目录或文件 | 作用 |
| --- | --- |
| `graph.py` | docgen graph 定义 |
| `state.py` | docgen graph 状态 |
| `nodes/` | research、write、merge、publish 等节点 |
| `runtime/` | chapter context、writer、assets 等 workflow-local runtime |
| `services/` | docgen lane 内部服务辅助 |
| `publish.py` | 构建产物收口与发布辅助 |

## workflow 公共支撑放哪里

workflow 公共能力统一放在 `app.shared.infra.workflow`。

当前推荐导入面：

```python
from app.shared.infra.workflow import (
    WorkflowContext,
    emit_progress,
    invoke_state_graph,
    project_typed_dict_schema,
    run_state_graph,
    workflow_tracer,
)
```

如果真的需要离线图文导出类型，再单独从：

```python
from app.shared.infra.workflow.graph_export import WorkflowGraphExport
```

导入。

## 什么不该放进 workflows

下面这些内容不要继续回流到 `workflows`：

- 数据库、对象存储、reader、retriever、LLM 的底层接入
- 通用 tool registry / skillpack registry
- LangSmith 私有 helper
- 第二套 progress / tracing 框架
- teaching 表达本身

判断方法：

- 在决定“这条流程怎么跑”，放 `workflows`
- 在决定“怎么教”，放 `teaching`
- 在决定“能力怎么接”，放 `shared.infra`

## 推荐阅读顺序

第一次读当前知识文档主链，建议按下面顺序：

1. `backend/app/api/knowledge_docs.py`
2. `backend/app/services/knowledge_docs/build_planner_service.py`
3. `backend/app/workflows/digest/planner/__init__.py`
4. `backend/app/workflows/digest/planner/runtime.py`
5. `backend/app/workflows/digest/planner/graph.py`
6. `backend/app/services/knowledge_docs/digest_service.py`
7. `backend/app/workflows/digest/runtime.py`
8. `backend/app/workflows/digest/docgen/graph.py`

## 一句话总结

`workflows` 是业务编排层。对当前知识文档主线来说，planner 负责把用户目标和资料整理成 confirmed plan，docgen 负责按这个契约执行正式构建；观测层已经明确拆成两件事：LangSmith trace 给研发排障，progress 给前端展示。`exports.py` 已经降级为可选的离线导出附加能力，不再是 workflow 标准链路的一部分。
