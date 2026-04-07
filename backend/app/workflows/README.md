# Workflows 模块

`backend/app/workflows/` 是后端的核心编排层，负责承载五大 AI 教学引擎的 LangGraph 状态机定义、节点实现和运行入口。

## 架构原则

- **`services/`** 只负责 API 路由触发、参数校验、持久化适配 → 薄层
- **`workflows/`** 负责真正的业务编排、状态推进和事件回流 → 厚层
- 每个引擎保持统一的**顶层骨架**，降低跨模块阅读和修改成本

## 五大引擎一览

| 引擎 | 目录 | 职责 |
|------|------|------|
| **Ingest** 摄入引擎 | `ingest/` | 文件解析 → 归一化文本块 → 深度 OCR 增强 |
| **Digest** 消化引擎 | `digest/` | 知识图谱构建 · 教案文档生成 · 课程大纲推导 |
| **Interact** 伴读引擎 | `interact/` | 个性化教学对话（检索增强 + 策略选择 + 流式回答） |
| **Examine** 诊断引擎 | `examine/` | 智能出卷 → AI 判卷 → 错因归类 → 复习调度 |
| **Profile** 显影引擎 | `profile/` | 掌握度计算 → 遗忘曲线排期 → 弱势排行 → 学习报告 |

## 目录骨架约定

每个引擎模块**必须**遵循以下顶层结构：

```
workflows/<engine>/
├── __init__.py          # 模块入口
├── graph.py             # LangGraph 图定义（或 re-export 子图构建函数）
├── state.py             # TypedDict 状态类型定义
├── runtime.py           # 运行入口：初始状态 → 编译 → 执行 → 事件发布
├── exports.py           # 导出清单，供架构图脚本读取
├── events.py            # 领域事件定义（可选）
├── prompts/             # 提示词模板
│   ├── __init__.py
│   └── prompts.py       # 必须导出 PROMPTS: dict[str, str]
└── nodes/               # 节点实现（可选，按需拆分）
```

### 各文件职责说明

| 文件 | 放什么 | 不放什么 |
|------|--------|----------|
| `graph.py` | `build_xxx_graph() -> StateGraph` 纯图定义 | 运行逻辑、持久化 |
| `state.py` | `TypedDict` 状态类型 | 业务逻辑 |
| `runtime.py` | `run_xxx_workflow()` 入口、初始状态创建、结果封装 | 图结构定义 |
| `exports.py` | `WORKFLOW_EXPORTS` 元组，供 `generate_workflow_diagrams.py` 消费 | 运行时逻辑 |
| `prompts/prompts.py` | 提示词常量 + `PROMPTS` 字典 | 节点逻辑 |

## 允许的内部差异

顶层骨架统一，但**内部子目录按问题形状拆分**，不强行一致：

- **`ingest/`** — 单主流程，按执行层拆：`nodes/`（节点）、`parsing/`（解析策略）
- **`digest/`** — 多子流程编排，按业务线拆：`kg/`（图谱）、`docs/`（教案）、`curriculum/`（大纲）、`unified/`（统一编排）
- **`examine/`** — 出卷和判卷两条独立流水线，各自在顶层文件中定义

## 新增 Prompt 规范

所有 `prompts/prompts.py` 必须导出一个 `PROMPTS: dict[str, str]` 字典，key 为 prompt 名称，value 为完整模板字符串。这样架构图脚本可以自动收集并展示在生成的文档中。

```python
# prompts/prompts.py 示例
SYSTEM_PROMPT_FOO = """..."""
SYSTEM_PROMPT_BAR = """..."""

PROMPTS: dict[str, str] = {
    "foo": SYSTEM_PROMPT_FOO,
    "bar": SYSTEM_PROMPT_BAR,
}
```

## 架构图自动生成

运行以下命令可从编译后的 LangGraph 拓扑自动生成各引擎的 Mermaid 架构图：

```bash
conda run -n atm python scripts/generate_workflow_diagrams.py
```

生成结果位于 `scripts/.generated_workflow_diagrams/`，每个引擎一个 `.md` 文件。

## 调试与观测规范

为了保证“写完 workflow 就能直接看过程”，新的 workflow 默认必须接入统一的 LangGraph 调试与 tracing 约定，而不是各自手写一套日志逻辑。

### 1. 统一运行入口

- 优先通过 `app.workflows.common.runtime.run_state_graph()` 执行 LangGraph。
- 这样可以自动获得：
  - `structlog` 的 workflow 开始/结束/失败日志
  - 统一的 `llm_trace_scope`
  - LangSmith tracing 上下文
- 如果某个 workflow 因为流式输出或历史包袱不能直接走 `run_state_graph()`，优先复用 `app.workflows.common.runtime.invoke_state_graph()` 这类共享薄包装，而不是在模块里重复手写 `compile().ainvoke()` + tracing。

### 2. 统一 LLM 调用入口

- 所有节点内的模型调用统一走 `app.shared.infra.llm`。
- 不要在 workflow 节点里直接调用 `litellm`、`instructor` 或其他 SDK。
- 这样可以自动获得：
  - 模型路由
  - 重试/超时控制
  - 现有的 token 统计
  - LangSmith LLM trace

### 3. 统一 Graph 暴露方式

- 每个 workflow 至少暴露一个 `build_xxx_graph() -> StateGraph`。
- 需要给 `langgraph dev` 提供默认 `WorkflowContext` 的模块，可以额外暴露 `get_langgraph_dev_xxx_graph()` 这种零参数工厂函数。
- `backend/langgraph.json` 只引用 graph 对象或零参数工厂函数，不再额外维护一份复制业务逻辑的调试实现。

### 4. 上下文元数据约定

- `WorkflowContext.metadata` 中如果存在稳定的运行标识，优先使用 `build_session_id`。
- 如果没有 `build_session_id`，可以退化为 `job_id` 的字符串形式。
- 这些字段用于把 LangSmith trace、结构化日志、业务事件串起来，所以新增 workflow 时要尽量补齐。

## LangGraph Dev 与 LangSmith

推荐的最小接入方式如下：

```env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_xxx
LANGSMITH_PROJECT=AITeachMe
```

配合：

- `backend/langgraph.json`
- `langgraph dev --config langgraph.json`

即可在 Studio 中查看 graph、state、节点执行过程；如果 workflow 和 LLM 调用都遵循上面的统一约定，就不需要为每个模块再单独写一遍 tracing 代码。
