# Workflows 模块

`backend/app/workflows/` 是后端新的编排中心，负责承载五大引擎的状态流、LangGraph 图定义和运行入口。

## 统一目标

- `services/` 只负责 API 触发、参数整理、持久化适配。
- `workflows/` 负责真正的业务编排、状态推进和事件回流。
- 每个引擎都尽量暴露同一套顶层骨架，降低阅读和修改成本。

## 顶层骨架约定

每个工作流模块优先保持以下顶层形状：

```text
workflows/<domain>/
├── __init__.py
├── graph.py
├── runtime.py
├── state.py
├── events.py
├── exports.py
├── prompts/
└── ...
```

含义约定：

- `graph.py`
  只放 LangGraph 图定义，或者统一 re-export 子图构建函数。
- `runtime.py`
  只放运行入口、初始状态创建、事件发布和结果封装。
- `state.py`
  放工作流状态类型；如果顶层只是组合子流程，可以做状态 re-export。
- `events.py`
  放领域事件定义。
- `exports.py`
  放工作流导出清单，供流程图脚本直接读取。
- `prompts/`
  放提示词模板。

## 允许的内部差异

顶层骨架尽量统一，但内部子目录可以按问题形状拆分，不需要强行完全一样。

### `ingest/`

`ingest` 是单主流程，内部更像一个解析管线，所以更适合按执行层拆分：

- `nodes/`: LangGraph 节点
- `parsing/`: 解析策略、分类、解析器实现

### `digest/`

`digest` 是多子流程编排，内部更像“图谱构建 + 课程派生”两个工作流组合，所以更适合按业务子流拆分：

- `kg/`: 知识图谱构建子流程
- `curriculum/`: 课程结构派生子流程

## 当前建议

- 不需要把 `ingest` 硬改成 `kg/curriculum` 风格。
- 也不需要把 `digest` 强压成 `nodes/parsing` 风格。
- 真正要统一的是顶层入口形状和命名约定，而不是抹平业务差异。



TODO 改流程代码的时候把langgraph对应图也都改一下