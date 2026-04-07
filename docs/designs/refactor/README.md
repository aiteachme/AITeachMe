# AITeachMe × GPT-Researcher 深度融合重构白皮书

> **文档定位**：本文档是执行层面的顶层设计。在写任何一行代码之前，必须就本文所有章节达成共识。  
> **涵盖范围**：① 工具体系重构（Skills / Actions / Retrievers） ② Digest DocGen 流程重建 ③ 富媒体文档生成策略 ④ LangSmith 全链路可观测性  
> **核心原则**：抽取 gpt-researcher 的灵魂（Plan-Execute-Write 范式、三级 LLM、Skill 组合、上下文压缩），融入我们已有的 LangGraph + LiteLLM + Instructor 技术栈，绝不照搬皮囊。

---

## 文档索引

| 序号 | 文件 | 内容 |
|:---|:---|:---|
| 1 | [01_architecture_alignment.md](01_architecture_alignment.md) | 两个项目的架构对齐 — 能力矩阵对照、移植清单 |
| 2 | [02_llm_tier_strategy.md](02_llm_tier_strategy.md) | 三级模型策略 — LLMTier 设计、模型映射、降级容错链 |
| 3 | [03_tools_refactor.md](03_tools_refactor.md) | 工具体系重构 — Skills + Actions + Retrievers + Scraper |
| 4 | [04_docgen_pipeline.md](04_docgen_pipeline.md) | Digest DocGen 流程全链路重建 — 新版 LangGraph 拓扑 |
| 5 | [05_document_modes.md](05_document_modes.md) | 速成课 vs 系统课 — 双模式文档生成策略 |
| 6 | [06_retrieval_strategy.md](06_retrieval_strategy.md) | 检索策略与教育资源库 |
| 7 | [07_teaching_tools.md](07_teaching_tools.md) | 教育工具集成与 Teaching Skills |
| 8 | [08_migration_plan.md](08_migration_plan.md) | 废弃文件清单 + 新增文件清单 |
| 9 | [09_execution_plan.md](09_execution_plan.md) | 分阶段重构执行计划 |
| 10 | [10_langsmith_observability.md](10_langsmith_observability.md) | LangSmith 全链路可观测性设计 |
| 11 | [11_open_questions.md](11_open_questions.md) | 开放问题（需要确认） |
| 12 | [12_appendix.md](12_appendix.md) | 附录 — 数据结构、Prompt 索引、环境变量 |
