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