# AITeachMe × GPT-Researcher 深度融合重构白皮书

> **文档定位**：本文档是执行层面的顶层设计，同时作为实施进度的实时追踪。  
> **涵盖范围**：① 工具体系重构（Skills / Actions / Retrievers） ② Digest DocGen 流程重建 ③ 富媒体文档生成策略 ④ LangSmith 全链路可观测性  
> **核心原则**：抽取 gpt-researcher 的灵魂（Plan-Execute-Write 范式、三级 LLM、Skill 组合、上下文压缩），融入我们已有的 LangGraph + LiteLLM + Instructor 技术栈，绝不照搬皮囊。  
> **最后更新**：2026-04-08

---

## 整体进度

| 阶段 | 状态 | 说明 |
|:---|:---|:---|
| Phase 0：基础设施层 | ✅ 已完成 | fallback.py + 检索器工厂 + Scraper |
| Phase 1：Skills + Actions | ✅ 已完成 | 6 个业务 Skill + 7 个 builtin Action |
| Phase 2：DocGen 流程重建 | ✅ 已完成 | 8 节点 LangGraph 新拓扑 |
| Phase 3：富媒体增强 | 🟡 部分完成 | MermaidGenerator ✅ / ImageGenerator 框架就绪 / 前端待实现 |
| Phase 4：教育资源库 | ⬜ 未开始 | 本地语料库 + Teaching Skills |
| Phase 5：质量调优 | ⬜ 未开始 | Prompt 精调 + 端到端验证 + LangSmith Dashboard |

---

## 文档索引

| 序号 | 文件 | 内容 | 更新状态 |
|:---|:---|:---|:---|
| 1 | [01_architecture_alignment.md](01_architecture_alignment.md) | 架构对齐 — 能力矩阵（已反映实际实现） | ✅ 已更新 |
| 2 | [02_llm_tier_strategy.md](02_llm_tier_strategy.md) | 三级模型策略 — 降级容错链 | — |
| 3 | [03_tools_refactor.md](03_tools_refactor.md) | 工具体系 — Skills + Actions + Retrievers + Scraper（已反映实际实现） | ✅ 已更新 |
| 4 | [04_docgen_pipeline.md](04_docgen_pipeline.md) | DocGen 流程 — 8 节点 LangGraph 拓扑（已反映实际实现） | ✅ 已更新 |
| 5 | [05_document_modes.md](05_document_modes.md) | 速成课 vs 系统课 — 双模式策略 | — |
| 6 | [06_retrieval_strategy.md](06_retrieval_strategy.md) | 检索策略与教育资源库 | — |
| 7 | [07_teaching_tools.md](07_teaching_tools.md) | 教育工具集成与 Teaching Skills | — |
| 8 | [08_migration_plan.md](08_migration_plan.md) | 文件清单（已反映实际迁移状态） | ✅ 已更新 |
| 9 | [09_execution_plan.md](09_execution_plan.md) | 执行计划（已标记各 Phase 完成状态） | ✅ 已更新 |
| 10 | [10_langsmith_observability.md](10_langsmith_observability.md) | LangSmith 可观测性（已反映 SkillContext.trace_metadata 落地） | ✅ 已更新 |
| 11 | [11_open_questions.md](11_open_questions.md) | 开放问题（已标记已解决项 + 新增 5 个实现中发现的问题） | ✅ 已更新 |
| 12 | [12_appendix.md](12_appendix.md) | 附录 — 数据结构、Prompt 索引、环境变量 | — |
