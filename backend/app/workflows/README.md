# Workflows 说明

最后更新：2026-04-15

`backend/app/workflows/` 是后端业务编排层，负责把五大引擎组织成真正可运行的 workflow。

推荐依赖方向：

```text
api -> services -> workflows -> teaching -> shared.infra -> shared.kernel
```

边界只记三句话：

- `workflows` 决定“这条业务流程怎么跑”
- `teaching` 决定“怎么教、怎么表达”
- `shared.infra` 提供 LLM、storage、search、observability、workflow runtime 等基础能力

## 先读哪几份文档

- 总体组织规范：[ARCHITECTURE.md](./ARCHITECTURE.md)
- Digest 模块示例：[digest/README.md](./digest/README.md)
- LangSmith 接法：[LANGSMITH.md](./LANGSMITH.md)
- 前端 progress 事件：[PROGRESS.md](./PROGRESS.md)
- 本地调试方式：[DEBUGGING.md](./DEBUGGING.md)

## 当前最重要的真实主链路

当前知识文档主线是：

```text
api/knowledge_docs.py
-> services/knowledge_docs/build_planner_service.py
-> app.workflows.digest.planner
-> confirmed_plan
-> services/knowledge_docs/digest_service.py
-> app.workflows.digest.run_docgen_workflow
```

也就是：

1. `planner`
   先生成并修订 confirmed plan
2. `docgen`
   再按 confirmed plan 执行正式知识文档构建

## 当前最值得记住的组织结论

- `workflows` 下先按“模块”组织，再按“链路”组织
- `prompts` 统一放模块层
- 轻量链路用文件模式，复杂链路用文件夹模式
- 多链路模块根目录的 `graph.py / runtime.py / state.py` 只做聚合，不继续堆链路实现

具体规则见 [ARCHITECTURE.md](./ARCHITECTURE.md)。

## 一句话总结

`workflows` 是业务编排层；当前知识文档主线优先看 `digest.planner -> confirmed_plan -> digest.docgen`，后续所有模块都按统一的“模块/链路/prompts/runtime/nodes”规范继续收口。

