# Workflows 模块

后端新的编排主目录，负责承载五大引擎的状态流、节点拆分和 LangGraph 图入口。

## 设计目标

- `core/` 只保留基础设施，不再承担业务编排
- `services/` 只保留校验、触发、适配
- `workflows/` 成为引擎内部数据流和状态流的唯一主入口
- 统一使用 LangGraph 的 `StateGraph` 作为工作流骨架
- 通过进程内领域事件显式暴露引擎间回流

## 当前迁移状态

- `digest/`
  已完成第一批迁移，新增 `state.py`、`events.py`、`graph.py`
- `ingest/` / `interact/` / `examine/` / `profile/`
  目录已预留，后续按相同规范迁移

## 目录规范

```text
workflows/
├── common/
│   ├── context.py
│   ├── events.py
│   ├── result.py
│   ├── runtime.py
│   └── types.py
├── ingest/
├── digest/
├── interact/
├── examine/
└── profile/
```

每个引擎目录最终统一包含：

- `state.py`
  引擎状态对象
- `events.py`
  领域事件定义
- `graph.py`
  LangGraph 图装配与唯一入口
- `nodes/`
  步骤级节点实现

## 迁移原则

- 先迁移编排入口，再下沉节点实现
- 对外 API、数据库结构、运行时目录优先保持不变
- 允许短期兼容旧 `agents/` 实现，但最终目标是彻底移除 `agents/`

