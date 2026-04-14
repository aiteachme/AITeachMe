# Digest Refactor 总览

> 最后更新：2026-04-14

本目录是 Digest refactor 的设计入口。本轮 refactor 已完成"边界收敛 + 主链路打通 + 最小可观测性统一"，后续重点是质量做深和跨引擎协同。

## 文档索引

| 文件 | 内容 |
| --- | --- |
| `02_landed_decisions.md` | 已落地的关键决策（架构边界、扩展模型、LLM 策略、DocGen 骨架、tracing） |
| `05_document_modes.md` | 知识文档模式契约 — 待完成的章节结构、资产配额、质量门槛、交互内容 |
| `06_retrieval_strategy.md` | 检索策略 — 待完成的学科化 profile、持久化缓存、本地语料库 |
| `08_migration_plan.md` | 迁移计划 — Phase 0-5 状态总表与开发优先级 |
| `09_execution_plan.md` | 执行计划 — 待办批次 A-D |
| `10_langsmith_observability.md` | LangSmith 可观测性 — 待建设的 dashboard 和观测点 |
| `13_interact_agent_modes.md` | Interact 执行模式 — 待扩展的 agent mode 和工具白名单 |
| `14_llamaindex_migration.md` | LlamaIndex 渐进式迁移方案 — adapter 层设计、分阶段实施计划 |

代码侧实现文档：

- `backend/app/workflows/LANGSMITH.md` — LangSmith 代码级规范
- `backend/app/workflows/TRACKED_STEP.md` — workflow step 规范
- `backend/app/workflows/common/__init__.py` — workflow authoring 入口
- `backend/app/workflows/README.md` — workflows 层总览
- `backend/app/teaching/README.md` — teaching 层总览

## 开放问题

以下问题仍待拍板，但不阻塞当前开发：

1. **前端暴露粒度**：`course_type` / `retrieval_profile` 前端要暴露到多细？当前推荐由 planner 推断，前端只做简单模式切换。
2. **research cache 持久化**：缓存放置层、过期策略和跨用户隔离粒度待定。当前先保持 runtime 内存缓存。
3. **interactive_html 渲染契约**：前端最终支持"简单 HTML 模板"还是"更强交互组件协议"？当前保持 backend-first 最小模板。
4. **skillpack 扩展到 Interact / Examine**：先接哪个引擎？最小共享字段范围？当前先把 Digest 合同做稳。
5. **animation 准入标准**：教育价值验收标准和首批适用学科待定。当前保持 contract/trace 预留位。
6. **本地教育语料库**：第一批学科和语料生产/审核流程待定。

## 需要持续验证的方向

- 不同学科下 `coverage_score` 阈值设定
- `sprint / systematic` 的 research round cap 是否需按学科细分
- `SourceCurator` 来源分类与教育权重稳定性
- `interactive_html` 对时延和学习价值的真实收益
- `practice layer` 哪类题目最能提升课程质量
- Interact 长对话压缩策略

## 权威性说明

如果设计文档与当前代码冲突，优先以当前代码和 `backend/app/workflows/*.md` 为准。
