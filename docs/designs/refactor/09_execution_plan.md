# Execution Plan — 待办批次

> 最后更新：2026-04-14
>
> 已落地的关键结果见 `02_landed_decisions.md`。本文档只保留待办批次。

---

## 批次 A：retrieval quality

- 学科化 retrieval profile 参数表
- source class 调权（数学偏学术、考研偏题解等）
- 持久化检索缓存策略与隔离
- coverage / stop 条件调优
- micro-loop round 收益分析

## 批次 B：content quality

- richer teaching blocks（错因卡、公式解释卡、推导卡、变式题、迁移题）
- 更细 chapter execution contract（章节字数硬约束、必备区块校验）
- repair / quality gate 强化（自动评分 + 低分章节重审）
- mode-specific 质量分析（sprint vs systematic 分层评分）

## 批次 C：rich media

- richer interactive templates（超越最小 `<details>` 模板）
- image sidecar 真正内容化（不再只是占位式建议块）
- animation 进入首轮执行链的准入条件
- asset planning 与 chapter contract 对齐

## 批次 D：cross-engine convergence

- Interact 共享课程合同、Planner 上下文和章节上下文
- Examine 共享 Digest 章节研究上下文
- Profile 对齐 Digest / Examine / Interact 的关键合同字段
- 统一学习画像输入（课程产物 + 练习结果 + 交互行为）

## 验证要求

- toolpack 合同测试继续稳定
- workflow runtime trace 测试覆盖关键路径
- docgen research / writer / asset / practice 回归测试存在
- 非 Digest 引擎行为不被破坏
