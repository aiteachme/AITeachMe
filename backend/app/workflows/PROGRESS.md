# Progress 规范

这份文档只讲前端进度事件。

它和 LangSmith trace 是两回事：

- LangSmith trace 给研发排障
- `progress` 给前端展示

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

## 事件 payload

统一只保留 4 个字段：

- `stage`
- `detail`
- `step`
- `elapsed_ms`

其中：

- `stage`
  给前端判断当前阶段
- `detail`
  给用户看的自然语言提示
- `step`
  可选，用于关联当前顶层 node
- `elapsed_ms`
  可选，通常用于完成态摘要

## 设计原则

### 1. 只发用户看得懂的阶段

应该发：

- “正在读取用户目标和已上传资料...”
- “正在快速检索基础概念与知识框架...”
- “方案已整理完成，准备返回前端。”

不应该发：

- 内部 helper 名
- LLM / retriever 技术细节
- tracing 私有概念

### 2. 不维护 step 生命周期框架

现在没有通用的：

- `tracked_step`
- `record_step_start`
- `record_step_end`
- `runtime_steps`

也不再推荐为每个小步骤都发成对的 running / completed 事件。

只在对前端真正有意义时发事件。

### 3. planner 的 runtime_stats 只是兼容摘要

当前 planner 仍保留一个弱兼容返回：

- `runtime_stats.elapsed_ms`
- `runtime_stats.generation_mode`
- `runtime_stats.steps`

但 `steps` 只允许是顶层 node 摘要：

- `load_context`
- `ground_concepts`
- `draft_plan`

它不是第二套 trace，只是兼容给前端显示“最多 3 个顶层节点耗时”。

## 前端约定

planner SSE `status` 事件只依赖：

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
- `step` 和 `runtime_stats.steps` 都只是增强信息

## 推荐心智模型

```text
LangSmith trace = 给研发排障
progress event  = 给前端展示
runtime_stats   = 少量兼容摘要，不是 tracing 系统
```
