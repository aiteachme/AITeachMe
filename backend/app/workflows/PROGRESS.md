# Progress 规范

这份文档只讲前端进度事件。

它和 LangSmith trace 是两回事：

- LangSmith trace
  给研发排障
- `progress`
  给前端展示

不要再把 `progress` 理解成第二套 tracing / step 生命周期。

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

## 标准 payload

统一只保留 4 个字段：

- `stage`
- `detail`
- `step`
- `elapsed_ms`

字段含义：

- `stage`
  前端判断当前处于哪个业务阶段
- `detail`
  给用户看的自然语言说明
- `step`
  可选，通常与当前顶层 node 对齐
- `elapsed_ms`
  可选，通常用于完成态摘要

## 设计原则

### 1. 只发用户真正看得懂的阶段

应该发：

- “正在读取用户目标和已上传资料...”
- “正在快速检索基础概念与知识框架，补充事实锚点...”
- “方案已整理完成，准备返回前端。”

不应该发：

- helper 函数名
- retriever / tool / tracing 私有术语
- 只有研发才能看懂的技术细节

### 2. 不维护通用 step 生命周期

现在没有，也不应该恢复这些概念：

- `tracked_step`
- `record_step_start`
- `record_step_end`
- `runtime_steps`

不要再为每个小步骤发一对 `running/completed` 事件。

只在对前端真的有意义时发事件。

### 3. `progress` 不负责替代 LangSmith

不要让 progress 承担这些职责：

- span 树
- trace 层级
- 全量 timing
- 开发排障细节

这些都应该交给 LangSmith。

### 4. `elapsed_ms` 只保留少量摘要价值

`elapsed_ms` 可以发，但用途要收敛：

- 顶层阶段完成摘要
- 前端展示总耗时或少量关键阶段耗时

不要把它扩张成全流程本地 timing 系统。

## planner 的兼容策略

当前 planner 仍保留一个弱兼容的 `runtime_stats` 概要返回：

- `runtime_stats.elapsed_ms`
- `runtime_stats.generation_mode`
- `runtime_stats.steps`

但要注意：

- `steps` 只允许是顶层 node 摘要
- 不再包含内部子步骤
- 它只是接口兼容层，不是 tracing 系统

当前 planner 顶层摘要最多对应：

- `load_context`
- `ground_concepts`
- `draft_plan`

## 前端约定

planner SSE `status` 事件现在只应该依赖：

- `stage`
- `detail`
- `step`
- `elapsed_ms`

前端必须接受这些情况：

1. 只有 `detail`
2. 只有 `step`
3. `runtime_stats.steps` 为空

也就是说：

- `detail` 是核心
- `step` 是增强信息
- `runtime_stats.steps` 是可选摘要，不是流程主依赖

## 推荐心智模型

```text
LangSmith trace = 给研发排障
progress event  = 给前端展示
runtime_stats   = 少量兼容摘要，不是 tracing 系统
```

## 一句话结论

progress 负责“告诉用户现在做到哪了”，不要再让它承担“复刻一套 trace 系统”的职责。
