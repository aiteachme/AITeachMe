# Workflows 分层说明

`backend/app/workflows/` 是业务编排层。
这里承载 LangGraph 的 graph/state/router，也承载各工作流自己的 workflow-local runtime 与必要的 subgraph。

## 长期定位

- `workflows` 负责“这轮流程怎么跑”。
- `workflows/.../runtime` 负责 workflow 专属的多步执行单元。
- `runtime` 这个命名只保留给 workflow 业务运行单元，不再回流到 `shared/infra` 根目录。
- 需要独立状态、可视化、可中断、可持久化的内部流程，优先做成 subgraph。

## 这一层应该放什么

- graph / state / router / fan-out / fan-in。
- workflow-local runtime。
- workflow-local prompt assembly。
- workflow 级 LangSmith / LangGraph 观测结构。
- 业务专属的多步执行单元。
- prompt 文本本身；如需模板变量渲染，可调用 `shared/infra/prompt_loader.py` 这类基础 helper。

## 这一层不应该放什么

- provider 接入、底层 retriever、底层 storage、canonical registry。
- teaching 章节脚手架本体。
- 第二套基础设施 helper。

## Digest 当前骨架

DocGen 顶层主链保持清晰稳定：

```text
load_context
-> targeted_research
-> resolve_titles
-> pedagogy_craft
-> enrich_document
-> inject_examine
-> finalize
```

其中：

- `workflows/digest/docgen/runtime/chapter_context.py`
- `workflows/digest/docgen/runtime/writer.py`
- `workflows/digest/docgen/runtime/assets.py`

都是 Digest DocGen 的 workflow-local runtime，不应再回流到 `infra` 或 `teaching`。

## LangSmith / LangGraph 纪律

- workflow node 名称必须直接表达业务语义。
- workflow-local runtime 的 trace 命名必须落在 `workflow_runtime.*`，不要伪装成 infra orchestration。
- trace 中必须能看见 planner session、confirmed plan、digest mode、retrieval profile、teaching action。
- graph 拓扑要让后续优化人员一眼看懂主骨架和章节并发骨架。

更具体的现行约定见 [`LANGSMITH.md`](d:/Project0GIT/aiteachme/AiTeachMe-main/backend/app/workflows/LANGSMITH.md)。

协同开发时可以直接记住这 3 个入口：

- LangGraph 节点: `@traced_workflow_node(...)` / `@traced_digest_node(...)`
- 节点内部关键步骤: `async with tracked_step(...)`
- 独立工具或 service: `@traceable`

## 判断标准

- 如果逻辑离开当前 workflow 仍然成立，优先回 `infra`。
- 如果逻辑是“这轮流程里的多步业务执行单元”，放 `workflows/.../runtime`。
- 如果逻辑是“这一批提示词文本和组装规则”，放 `workflows/.../prompts`。
- 如果逻辑需要独立图结构和状态可视化，升级成 subgraph。
