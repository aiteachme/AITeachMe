# Interact Agent Modes — 待扩展部分

> 最后更新：2026-04-14
>
> 已落地：`single_pass` / `plan_execute` 双模式最小版本，`search_kb` 工具白名单。

---

## 当前两种模式

| 模式 | 适用场景 | 行为 |
| --- | --- | --- |
| `single_pass` | 上下文明确、直接讲解 | 沿现有 prompt → stream 路径 |
| `plan_execute` | 需要补证据的引导式问题 | 受控 agent loop，先工具调用再回答 |

## 待推进

1. 把 `execution_mode` 暴露到 trace summary
2. 给 `plan_execute` 扩展 tool whitelist（不只 `search_kb`）
3. 让 Interact 复用 Digest 的 `selected_skillpacks` 和章节上下文
4. 评估是否需要 query rewrite / hybrid retrieval / LlamaIndex adapter

## LlamaIndex 态度

- 可做局部实验（`shared/infra/search` 下做 adapter）
- 不做全盘迁移
- 通过实验结果决定是否扩展
