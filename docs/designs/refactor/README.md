# Workflows 单层化重构总览

> 最后更新：2026-04-16

本目录现在同时承担两件事：

1. 记录 Digest 主线重构
2. 记录以 Digest 为第一落点的 workflows 单层化重构

当前最新边界决策不再是旧的 `services -> workflows -> teaching`，而是：

```text
api -> workflows -> repositories / shared.infra / models / schemas
```

## 文档索引

| 文件 | 内容 |
| --- | --- |
| `18_workflows_layer_consolidation.md` | Workflows 单层化边界收敛 — 为什么收缩 `services` / `teaching`，以及总映射表 |
| `19_workflows_structure_spec.md` | Workflows 结构规范 — engine/support 模板、命名规则、Digest 示例 |
| `20_workflows_migration_plan.md` | Workflows 单层化迁移计划 — 分阶段执行顺序、模块映射、风险与验收 |
| `21_planner_deep_research_flow.md` | Planner Deep Research 风格改造计划 — 草稿流、意图识别、概念增强、最终合成与前端可视化 |
| `22_planner_v4_research_surface_plan.md` | Planner V4 改造计划 — 对齐 OpenAI / Gemini Deep Research 的研究面板、概念增强、证据开读与前端可视化 |
| `21_ingest_deepdoc_comparison.md` | Ingest v2 全流程设计 — Provider 优先级、转换层、质量仲裁、多格式支持与教学证据层 |
| `24_ingest_deepdoc_simple_review.md` | Ingest 与 DeepDoc 简版对比 — 当前结构问题、`common` 取舍和小步收口顺序 |
| `02_landed_decisions.md` | 已落地的关键决策（架构边界、扩展模型、LLM 策略、DocGen 骨架、tracing） |
| `05_document_modes.md` | 知识文档模式契约 — 待完成的章节结构、资产配额、质量门槛、交互内容 |
| `06_retrieval_strategy.md` | 检索策略 — 待完成的学科化 profile、持久化缓存、本地语料库 |
| `08_migration_plan.md` | 迁移计划 — Phase 0-5 状态总表与开发优先级 |
| `09_execution_plan.md` | 执行计划 — 待办批次 A-D |
| `10_langsmith_observability.md` | LangSmith 可观测性 — trace 与 progress 的极简分层 |
| `13_interact_agent_modes.md` | Interact 执行模式 — 待扩展的 agent mode 和工具白名单 |
| `14_llamaindex_migration.md` | LlamaIndex 渐进式迁移方案 — adapter 层设计、分阶段实施计划 |

代码侧实现文档：

- `backend/app/workflows/LANGSMITH.md` — LangSmith 代码级规范
- `backend/app/workflows/PROGRESS.md` — workflow 前端进度规范
- `backend/app/workflows/STRUCTURE.md` — workflows 代码侧权威结构规范
- `backend/app/shared/infra/workflow/__init__.py` — workflow 共用公共入口
- `backend/app/workflows/README.md` — workflows 层总览
- `backend/app/workflows/support/README.md` — support 模块说明
- `backend/app/shared/infra/tools/builtin/teaching_tools.py` — 通用内置教学工具实现

## 开放问题

以下问题仍待拍板，但不阻塞当前开发：

1. **前端暴露粒度**：`course_type` / `retrieval_profile` 前端要暴露到多细？当前推荐由 planner 推断，前端只做简单模式切换。
2. **research cache 持久化**：缓存放置层、过期策略和跨用户隔离粒度待定。当前先保持 runtime 内存缓存。
3. **interactive_html 渲染契约**：前端最终支持"简单 HTML 模板"还是"更强交互组件协议"？当前保持 backend-first 最小模板。
4. **跨引擎策略复用**：Interact / Examine 复用 confirmed plan、Planner 上下文和章节产物，不再通过独立 prompt 扩展层传递策略。
5. **animation 准入标准**：教育价值验收标准和首批适用学科待定。当前保持 contract/trace 预留位。
6. **本地教育语料库**：第一批学科和语料生产/审核流程待定。

## 需要持续验证的方向

- 不同学科下 `coverage_score` 阈值设定
- `sprint / systematic` 的 research round cap 是否需按学科细分
- `SourceCurator` 来源分类与教育权重稳定性
- `interactive_html` 对时延和学习价值的真实收益
- `practice layer` 哪类题目最能提升课程质量
- Interact 长对话压缩策略

## 当前阅读顺序

如果你现在是第一次接这轮重构，建议按下面顺序读：

1. `18_workflows_layer_consolidation.md`
2. `19_workflows_structure_spec.md`
3. `20_workflows_migration_plan.md`
4. `backend/app/workflows/digest/planner/DOCGEN_ARCHITECTURE_REVIEW.md`
5. `backend/app/workflows/STRUCTURE.md`
6. 再回头读 Digest 的历史设计文档

## 权威性说明

如果设计文档与当前代码冲突，优先以当前代码和 `backend/app/workflows/*.md` 为准。
