# Teaching 分层说明

`app.teaching` 负责教学语义，不负责底层基础设施，也不负责 workflow 编排。

## 长期定位

- `teaching` 回答“怎么教”。
- `infra` 回答“底层能力怎么接”。
- `workflows` 回答“这一轮流程怎么跑”。

## 这一层应该放什么

- 章节教学结构与文档脚手架。
- 速成课 / 系统课的章节块设计。
- 错因翻译、反馈语言、练习编排、教学上下文组织。
- teaching-owned 原子函数。
- 需要明确教学语义的文档 overview、章节标题解析、导读和总结模板。

## 这一层不应该放什么

- 第二套 memory store、checker engine、tool registry。
- retriever / scraper / LLM provider / tracing helper。
- workflow graph/state/router。
- DocGen 的业务运行循环本身。

## Teaching Tool 的定义

- teaching tool 仍然是 canonical tool registry 里的 `tool`。
- 它只是由 teaching 层拥有语义和实现，不是第二套 registry。
- `app.teaching.tools` 负责注册 teaching-owned 原子函数。
- workflow 或 agent 最终调用的仍然是 `app.shared.infra.tools` 里的 canonical registry。

## 目录语义

```text
teaching/
├── documents/      # 章节教学脚手架、overview、title resolver
├── tools.py        # teaching-owned callable tools
├── teaching.py     # teaching tool catalog / facade
├── checker.py      # 教学语义包装，不复制 checker engine
└── ...             # 类比解释、练习编排、错因翻译等教学模块
```

## 与 Skillpack 的关系

- skillpack 不是 teaching tool。
- skillpack 只给 planner/docgen/interact 注入策略与偏好。
- teaching tool 是实际可执行的原子函数。
- skillpack 可以推荐 tool tags，但不能替代 tool registry。

## 当前纪律

- `teaching` 可以直接调用 `infra`，但不能复制 `infra`。
- `teaching` 可以被 workflow runtime 调用，但不接管 graph。
- `PedagogyWriter` 这类 DocGen 业务 runtime 不再待在 teaching，也不再待在 infra，而是回到 workflow-local runtime。
