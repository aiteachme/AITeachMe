# Workflows 架构规范

最后更新：2026-04-15

这份文档是 `backend/app/workflows/` 的组织规范，回答三件事：

1. `workflows` 里“模块”和“链路”到底怎么分
2. `prompts / runtime / nodes / graph / state / events` 应该放在哪一层
3. 什么时候用“文件组织”，什么时候升级成“文件夹组织”

如果旧文档和当前代码不一致，以当前代码和本规范为准；如果产品语义或外部接口要变，请先和团队确认。

## 1. 基本定义

- `module`
  指五大引擎之一，例如 `ingest / digest / interact / examine / profile`。
- `chain`
  指模块下面一条可独立理解、可独立运行、可被单独测试或调试的业务链路，例如 `digest.planner`、`digest.docgen`。
- `module shared`
  指同一模块多个链路复用的 contract、模型、helper、prompt。
- `chain runtime`
  指链路内部的运行辅助逻辑，不直接定义 graph 节点，例如 writer、query planning、asset staging。
- `node`
  指 LangGraph 中的一个执行节点；一个 node builder 对应一个明确的业务动作。

一句话心智模型：

```text
module = 引擎
chain  = 引擎里的具体链路
graph  = 链路怎么跑
node   = 链路每一步做什么
runtime= 给链路提供执行辅助
prompts= 模块统一管理的提示词资源
```

## 2. 分层边界

推荐依赖方向：

```text
api -> services -> workflows -> teaching -> shared.infra -> shared.kernel
```

`workflows` 只负责“这条业务流程怎么跑”，不要在这里再复制一套：

- tracing 框架
- tool registry
- storage 接入
- 通用 LLM/runtime 桥接
- 教学表达原子能力

判断标准：

- 决定流程编排、节点顺序、跨步骤状态：放 `workflows`
- 决定怎么教、怎么组织教学表达：放 `teaching`
- 决定能力怎么接、怎么观测、怎么存：放 `shared.infra`

## 3. 模块的标准组织

所有模块都遵循下面这个总模型：

```text
workflows/
  <module>/
    __init__.py
    README.md
    exports.py
    events.py
    graph.py
    runtime.py
    state.py
    prompts/
      __init__.py
      <chain>_prompts.py
      shared_prompts.py        # 可选
    shared/                    # 可选，跨链路共享 contract / model / helper
    <chain_a>/                 # 目录模式
    <chain_b>.py               # 文件模式（仅单链路或轻量链路）
```

说明：

- 多链路模块：
  根目录的 `graph.py / runtime.py / state.py` 只能做聚合、转发、导出，不能继续堆具体链路实现。
- 单链路模块：
  允许暂时使用“根目录紧凑模式”，直接把 `graph.py / runtime.py / state.py` 放在模块根目录。
- 一旦模块出现第二条长期维护的链路，原来根目录里的主链路应逐步下沉到命名链路目录。

## 4. 链路的两种组织模式

### 4.1 文件模式

适用于轻量链路，典型特征：

- 节点数量不超过 3 个
- 没有明显 fan-out / fan-in
- 没有 `nodes/`、`runtime/`、`services/` 的拆分需求
- 除 graph 之外，辅助文件不超过 2 到 3 个
- 维护者可以在一个屏幕内看清整条链路

推荐结构：

```text
<module>/<chain>/
  __init__.py
  runtime.py
  graph.py
  state.py
  models.py            # 可选
  contracts.py         # 可选
  helpers.py           # 可选，优先少量
```

### 4.2 文件夹模式

只要出现下面任一情况，就应升级为文件夹模式：

- 节点数 >= 4
- 使用 `Send()`、fan-out / fan-in、并行章节处理
- 存在 `nodes/`、`runtime/`、`services/` 这类明显子层
- 有 research / writer / publish / assets 这类链路内 sidecar
- 有链路级事件、链路级 contracts、链路级测试替身需求
- 单文件已经无法直观看懂职责边界

推荐结构：

```text
<module>/<chain>/
  __init__.py
  graph.py
  state.py
  runtime.py           # 对外运行入口，可选
  events.py            # 链路级事件，可选
  models.py            # 链路级数据结构，可选
  contracts.py         # 链路级合同，可选
  publish.py           # 结果收口/发布，可选
  nodes/
    __init__.py
    <node_name>_node.py
    common.py          # 仅保留 node 层小工具
  runtime/
    __init__.py
    <helper>.py
  services/
    __init__.py
    <service>.py
```

## 5. 文件与目录职责

### `__init__.py`

- 只暴露稳定公共入口
- 不放业务逻辑
- 服务层优先依赖这里，而不是深层路径

### `runtime.py`

- 对外入口，例如 `run_<chain>_workflow(...)`
- 负责创建 `WorkflowContext`
- 负责调用 `run_state_graph(...)`
- 负责 root 级结果检查、事件发布、总结日志

多链路模块根目录的 `runtime.py` 只做“跨链路聚合入口”，不写具体 node 逻辑。

### `graph.py`

- 只负责 graph 结构、路由、初始 state 组装
- 不承载大段业务算法
- node builder 在这里接线，不在这里展开实现

多链路模块根目录的 `graph.py` 只做 graph export 聚合。

### `state.py`

- 一条链路一个 state
- state 只放这条链路真正需要持有的字段
- 跨链路 contract 不放进 chain state，放到模块 `shared/`

多链路模块根目录的 `state.py` 只做 state re-export。

### `events.py`

- 模块根目录：放模块对外可见的 typed domain events
- 链路目录：只有在链路自己也需要稳定事件边界时才新增
- `progress` 不是 `events.py` 的替代品，也不要把前端展示文案塞到 domain event 里

### `nodes/`

- 一文件一个 node builder，命名 `build_<name>_node`
- 允许 `common.py`，但只放 node 层小工具
- 一旦 `common.py` 开始承担业务规则，就应迁移到 `services/` 或 `contracts.py`

### `runtime/`

- 放链路内部执行辅助，不直接承载 graph wiring
- 适合 writer、query planning、chapter context、asset helper
- 这里可以被多个 node 复用

### `services/`

- 放链路内的业务算法或较重 helper
- 不直接依赖具体 graph 节点顺序
- 适合提纯复杂逻辑，避免 `nodes/*.py` 过厚

### `publish.py`

- 专门用于产物收口、落盘、发布、manifest 生成
- 它是“链路终态 side effect”，不是通用 runtime helper
- 像 `docgen/publish.py` 这种职责清晰的文件应保留显式命名

## 6. Prompts 的统一规范

Prompts 统一放在模块层，而不是链路内部。

推荐结构：

```text
<module>/prompts/
  __init__.py
  <chain>_prompts.py
  shared_prompts.py          # 可选
```

规则：

- `prompts` 属于模块资源层，不要塞进 `nodes/`、`runtime/`、`services/`
- 一条链路一个 prompt 文件，例如：
  - `planner_prompts.py`
  - `docgen_prompts.py`
  - `kg_prompts.py`
- 多条链路共享的 prompt 片段，再提到 `shared_prompts.py`
- prompt builder 可以依赖模块级 `shared.models/contracts`
- prompt builder 不应反向依赖 node、runtime、publish

当单个链路 prompt 继续膨胀时，允许升级为模块级子目录：

```text
<module>/prompts/<chain>/
  __init__.py
  writer.py
  research.py
  repair.py
```

注意：即使升级成子目录，也仍然属于“模块级 prompts”，不是链路级实现目录。

## 7. 观测与事件的统一规范

当前 `workflows` 作者只保留 4 个公开入口：

```python
from app.shared.infra.workflow import (
    emit_progress,
    invoke_state_graph,
    run_state_graph,
    workflow_tracer,
)
from langsmith import traceable
```

分工：

- `run_state_graph(...)` / `invoke_state_graph(...)`
  workflow root 入口
- `workflow_tracer(...).node(handler, ...)`
  graph node 规范接线
- `@traceable`
  prompt / helper tracing
- `emit_progress(...)`
  前端进度事件

纪律：

- LangSmith trace 只给研发排障
- progress 只给前端展示
- typed `events.py` 只承载业务事件
- 不要在 `workflows` 里再维护第二套 tracing 或 step 生命周期

## 8. 对外导入面规范

服务层允许依赖：

- `app.workflows.<module>`
- `app.workflows.<module>.<chain>`

服务层不应长期依赖：

- `app.workflows.<module>.<chain>.nodes.*`
- `app.workflows.<module>.<chain>.runtime.*`
- `app.workflows.<module>.prompts.*`

例外：

- 测试、调试、`langgraph dev` export
- 临时迁移阶段，但应尽快收口回 `__init__.py`

## 9. 当前最明显的结构问题

这轮规范主要就是为了解决下面这些已经很明显的问题：

1. 多链路模块和单链路模块的写法并存，但之前没有“何时升级”的明确标准。
2. `prompts` 实际上已经是模块级资源，但旧文档没有把这条规则说清楚，后续很容易继续乱放。
3. 多链路模块根目录里哪些文件是“聚合层”，哪些文件是“真实实现”，之前表达不够清楚。

这些问题本身已经足够大，值得先通过文档规范统一，再做后续重构。

## 10. 迁移规则

后续新增或改造链路时，按下面顺序处理：

1. 先判断它是模块共享资源，还是链路实现
2. 先决定链路用文件模式还是文件夹模式
3. 对外入口先收口到 `__init__.py`
4. prompt 统一放模块 `prompts/`
5. 运行入口统一放 `runtime.py`
6. graph wiring 和业务算法分开

建议策略：

- 先补文档和 public surface
- 再做目录迁移
- 最后再改调用方导入路径

## 11. Digest 是当前参考实现

当前最适合拿来做规范样例的是 `digest` 模块，因为它已经同时包含：

- 文件模式链路：`planner`
- 文件夹模式链路：`docgen`
- 模块级 prompts：`digest/prompts/`
- 模块级聚合入口：`digest/__init__.py`、`digest/runtime.py`、`digest/graph.py`

具体示例见：

- [digest/README.md](./digest/README.md)

