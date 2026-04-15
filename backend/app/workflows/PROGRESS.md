# Progress 规范

这份文档只讲前端进度事件。

## 一句话原则

- LangSmith trace 给研发排障
- `progress` 给前端展示
- 不再维护第二套本地 step 生命周期

## 唯一公开入口

```python
from app.shared.infra.workflow import emit_progress
```

## 标准写法

```python
await emit_progress(
    state,
    stage="draft_plan",
    detail="正在流式生成研究任务草案...",
    step="draft_plan",
)
```

## 统一 payload

统一只保留 4 个字段：

- `stage`
- `detail`
- `step`
- `elapsed_ms`

含义：

- `stage`
  前端判断当前阶段
- `detail`
  给用户看的自然语言提示
- `step`
  可选，对应顶层 node
- `elapsed_ms`
  可选，用于完成态摘要

## 设计规则

1. 只发用户看得懂的阶段文案
2. 不暴露 helper 名、LLM 细节、trace 私有概念
3. 不为每个小步骤都发 running/completed 成对事件
4. `detail` 是核心，`step` 只是增强信息

## planner 的兼容口径

planner 仍可返回弱兼容的 `runtime_stats`，但它只允许保留顶层摘要：

- `elapsed_ms`
- `generation_mode`
- `steps`

其中 `steps` 只允许是顶层 node，例如：

- `load_context`
- `ground_concepts`
- `draft_plan`

它不是第二套 trace。

## 推荐心智模型

```text
LangSmith trace = 给研发排障
progress event  = 给前端展示
runtime_stats   = 少量兼容摘要
```

