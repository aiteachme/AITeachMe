# Workflows 分层说明

`backend/app/workflows/` 是业务编排层。

这里既放 LangGraph graph/state/router，也放业务专属的 workflow-local runtime 或 subgraph。长期不再把这类逻辑塞回 `shared/infra` 根目录。

## 长期定位

- `workflows` 负责“这轮流程怎么跑”。
- `workflows/.../runtime` 负责 workflow 专属多步逻辑。
- `runtime` 这个命名保留给 workflow 业务运行单元，不在 `shared/infra` 里再建同名总入口。
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

## Digest 的当前基线

DocGen 顶层骨架保持不变：

```text
load_context
-> research
-> write
-> enrich
-> examine
-> finalize
```

但 ownership 已经调整：

- `workflows/digest/docgen/runtime/research.py`
- `workflows/digest/docgen/runtime/writer.py`
- `workflows/digest/docgen/runtime/assets.py`

这些是 Digest DocGen 专属 runtime。

## LangSmith / LangGraph 约束

- workflow node 名称必须直接表达业务语义。
- workflow-local runtime 的 trace 命名必须落在 `workflow_runtime.*`，不要继续伪装成 infra orchestration。
- trace 里必须能看见 planner session、confirmed plan、digest mode、retrieval profile、teaching action。
- graph 结构要让后续优化人员一眼看懂“主骨架”和“章节并发骨架”。

## 判断标准

- 如果逻辑离开当前 workflow 仍然合理，优先回 `infra`。
- 如果逻辑是“这轮流程的多步运行单元”，放 `workflows/.../runtime`。
- 如果逻辑是“这一批提示词文本和组装规则”，放 `workflows/.../prompts`。
- 如果逻辑需要单独图结构和状态可视化，升级成 subgraph。
