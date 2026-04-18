# Migration Plan — 当前状态

> 最后更新：2026-04-14

## 阶段状态总表

| Phase | 目标 | 状态 |
| --- | --- | --- |
| Phase 0 | 冻结边界与术语 | ✅ 已完成 |
| Phase 1 | 移除独立 prompt 扩展层，策略回收到 workflow | ✅ 已完成 |
| Phase 2 | toolpack 变成真实扩展点 | ✅ 已完成 |
| Phase 3 | DocGen runtime 回归 workflows | ✅ 已完成 |
| Phase 4 | DocGen 质量增强 | ⚠️ 进行中 |
| Phase 5 | 跨引擎合同收敛 | ❌ 未开始 |

## Phase 4 — 已完成 vs 未完成

### 已完成

- chapter research 进入 micro-loop
- `requested_profile / applied_profile / research_rounds / source_class_breakdown` 进入 summary/trace
- retriever / reader / compression 接入最小 runtime cache
- Mermaid / image / interactive HTML 进入最小 asset sidecar 主线
- mode-aware practice layer 接入文档构建链
- workflow tracing 收敛到 4 入口

### 未完成

- 学科化 retrieval weighting / source class 调权
- 持久化检索缓存策略
- richer interactive/image sidecar
- animation 真正执行链
- 更细颗粒度的章节质量合同与教学块（错因卡、公式卡、变式题）
- 章节质量自动评分与 repair gate

## Phase 5 — 跨引擎合同收敛（待启动）

- Interact 复用 Digest 的课程合同、Planner 上下文和章节上下文
- Examine 共享 Digest 章节研究上下文与教学动作信息
- Profile 统一消费课程产物、练习结果和交互行为作为画像输入

## 开发优先级

1. retrieval quality（profile 调权、持久化 cache、micro-loop stop 调优）
2. content quality（teaching blocks、repair gate、mode-specific contract）
3. rich media（interactive/image 做深、animation 准入标准）
4. cross-engine convergence（Interact / Examine / Profile 共享 Digest 合同）
