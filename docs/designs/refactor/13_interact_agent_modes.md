# 13. Interact Agent Modes

最后更新：2026-04-13

## 目标

让 `interact` 不再只是一条固定的：

`history -> retrieval -> strategy -> prompt -> answer`

而是能根据问题类型切到不同执行模式，同时保持：

- workflow 主入口仍在 `workflows/interact`
- tools 仍通过 canonical tool registry 暴露
- LangSmith 仍沿现有 workflow/node/llm/tool 边界观测

## 当前落地的最小版本

本轮先引入两个 execution mode：

- `single_pass`
  保持当前单次 prompt + 单次回答路径
- `plan_execute`
  在回答前允许进入受控的 agent loop，先做必要工具调用，再基于证据回答

当前 `plan_execute` 只开放：

- `search_kb`

并且由 workflow 自动注入当前 `subject`，避免把学科上下文交给模型自己拼。

## 为什么先做 execution mode，而不是先迁 LlamaIndex

短结论：

不是不能用，而是现在不该把它当主线。

原因有 4 个：

1. 当前主要短板是 `interact` 缺 execution mode，不是缺一个新的 RAG 容器。
2. 项目已经把业务 runtime、state、LangSmith、subject contract 固定在自有 workflow 上，整迁外部框架的收益不够直接。
3. 现在最需要的是把 `Digest -> Interact -> Examine` 的合同打通，而不是再引入一层新的 orchestration 抽象。
4. LlamaIndex 更适合作为局部 adapter/实验层，而不是当前 canonical retrieval runtime。

## 对 LlamaIndex 的推荐态度

当前建议：

- 可以做局部实验
- 不做全盘迁移

更合理的试法是：

1. 在 `shared/infra/search` 下做 adapter
2. 只替换某一段 retrieval / rerank / query transform
3. 比较质量、时延、trace 可读性
4. 通过实验结果决定是否扩展

不建议现在做的事：

- 直接把 `search/knowledge.py`、`interact/support/retrieval.py`、`digest` research runtime 整体改写成 LlamaIndex 风格

## 当前 execution mode 的边界

### `single_pass`

- 适合：已有明确上下文、问题边界清晰、直接讲解即可
- 行为：沿现有 `build_chat_messages -> acompletion_stream` 路径执行

### `plan_execute`

- 适合：规划类、拆解类、需要补证据的引导式问题
- 行为：
  - 先构建 prompt
  - 再进入受控 `agent_loop`
  - 工具白名单当前只给 `search_kb`
  - `max_iterations` 和 `max_tool_calls_per_turn` 保持较小

## 下一批建议

1. 把 `execution_mode` 暴露到 trace summary
2. 给 `plan_execute` 增加更细的 tool whitelist
3. 让 Interact 复用 Digest 的 `selected_skillpacks` 和章节上下文
4. 再决定是否需要引入 query rewrite / hybrid retrieval / LlamaIndex adapter

## 一句话结论

`interact` 当前最值得推进的是 mode-aware execution，而不是整体迁移 RAG 框架。  
LlamaIndex 可以试，但应该先作为局部能力实验，而不是现在就成为新的主干架构。
