# 07. Teaching Tools

## 1. 目标

明确 teaching tool 不是第二套工具系统，而是 canonical tool registry 中一类带教学语义的原子函数。

## 2. 定义

- teaching tool：教学层拥有语义和实现的原子 tool。
- 注册位置：`app.teaching.tools`
- 执行入口：仍然通过 `app.shared.infra.tools`

## 3. 为什么不单独做 registry

- registry 分叉会让 agent/runtime 无法统一发现工具。
- tracing、权限、扩展模型会重复一套。
- tool selection 规则会变成两份真相源。

所以教学工具必须共用 canonical registry。

## 4. 适合放进 teaching tool 的内容

- step-by-step 解题
- 相似题生成
- 概念对比
- 公式解释
- 错因翻译
- 章节内小练习组织

## 5. 不适合放进 teaching tool 的内容

- 章节 research micro-loop
- 文档写作循环
- graph 编排
- provider 适配
- tool loader / skillpack loader

这些分别属于 workflow runtime 或 infra。

## 6. 与 Skillpack 的关系

- teaching tool 是可执行函数。
- skillpack 是 prompt strategy package。
- skillpack 可以推荐 teaching tool 的标签。
- 但 skillpack 不能直接替代 teaching tool。

## 7. 当前约束

- `teaching/tools.py` 里注册的函数都必须是原子动作。
- 需要多步状态和中断能力的教学流程，应该上 workflow runtime / subgraph。
- teaching 层只定义教学语义，不接管扩展基础设施。
