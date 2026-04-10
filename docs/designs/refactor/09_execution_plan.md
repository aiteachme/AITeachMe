## 九、分阶段执行计划

> 目标：把重构拆成可以逐阶段上线、逐阶段验证、逐阶段回滚的计划，而不是一次性大改。
> 最后更新：2026-04-10

---

## 9.1 总体策略

### 先做什么

- 先冻结分层边界与观测契约
- 再升级 Docs Lane 的 research 和写作质量
- 最后再补富媒体、教学工具、教育语料库

### 明确不做什么

- 不同步重写五大引擎
- 不为了迁移 `gpt-researcher` 而复制目录树
- 不在没有 LangSmith 可视化的前提下盲改主流程

### 总原则

1. 只要一个阶段结束，就应该是”可运行、可观测、可回退”的。
2. 所有实质性行为改动优先限制在 `planner/docgen`。
3. 所有阶段都要验证不会破坏 KG Lane 和其他四个引擎。

---

## 9.2 Phase 0：边界冻结与文档对齐 ✅ 已完成

### 目标

先把未来所有改动的设计地基打稳。

### 已完成的事

- ✅ 明确 `shared/infra`、`teaching`、`workflows` 三层职责（03 文档）
- ✅ 明确 canonical memory 在 `shared/infra/memory`，`teaching/memory` 仅为过渡层
- ✅ 明确 `sprint` / `systematic` 的输出契约（05 文档）
- ✅ 明确 LangSmith 命名与 metadata 口径（10 文档）
- ✅ refactor 系列 11 份文档初版完成

### 验收结果

- 后续新代码能够根据文档直接判断放哪层
- 分层边界已在代码中初步体现（`teaching/context.py` 依赖 `shared/infra/memory`，`skills/writer.py` 调用 `teaching/documents`）

---

## 9.3 Phase 1：Build Contract 收紧与 LangSmith 契约加固

### 目标

让 Planner 输出有 schema 约束，让 DocGen 全链路在 LangSmith 里可串联、可比较。

### 具体改动清单

| 改动 | 文件 | 说明 |
|:---|:---|:---|
| 定义 `BuildContract` model | `workflows/digest/shared/contracts.py`（新增） | Pydantic model，含 `course_type` / `target_word_count` / `formula_depth` / `example_density` / `chapter_contracts` 等 |
| `load_context_node` 改用 model_validate | `docgen/nodes/load_context_node.py` | 替代当前的 `.get()` + fallback 散逻辑 |
| 补充 trace metadata | `docgen/nodes/*.py` | 每个节点的 `wrap_digest_node` 调用补充 `course_type` / `retrieval_profile` / `chapter_index` |
| 统一进度事件语义 | `docgen/nodes/common.py` | `publish_docgen_progress()` 补充业务维度字段 |
| Planner 输出端对齐 | `services/knowledge/build_planner_service.py` | Planner confirm 时输出符合 `BuildContract` schema 的 dict |

### 只允许改动

- `workflows/digest/shared/contracts.py`（新增）
- `workflows/digest/docgen/nodes/`
- `workflows/digest/observability.py`
- `services/knowledge/build_planner_service.py`
- `workflows/common/` 的 event 定义

### 不允许改动

- `digest/kg/` 任何文件
- `digest/curriculum/` 任何文件
- `ingest/` / `interact/` / `examine/` / `profile/`
- `unified/graph.py` 的节点拓扑

### 验收标准

- `BuildContract.model_validate(confirmed_plan)` 在 `load_context_node` 中一次性校验通过
- 打开 LangSmith 后，能通过 `build_session_id` 一眼看到 Planner → DocGen 的关联
- 每章 research / writing / enrich / examine 都能通过 `chapter_index` + `course_type` 单独定位
- 现有测试和前端流程不受影响

---

## 9.4 Phase 2：章节研究微循环与检索 profile

### 目标

让章节 research 从”一次性搜一轮”升级为”轻量质量驱动研究”，同时让检索策略按课程模式差异化。

### 具体改动清单

| 改动 | 文件 | 说明 |
|:---|:---|:---|
| `ResearchConductor.run()` 增加微循环 | `shared/infra/skills/researcher.py` | 增加 `assess_gaps()` → `generate_gap_queries()` → 补检索 的内部循环 |
| 新增 `assess_gaps()` 方法 | `shared/infra/skills/researcher.py` | 用 Fast LLM 判断 `required_elements` 覆盖情况 |
| 检索 profile 显式化 | `shared/infra/search/factory.py` | `docgen_sprint` / `docgen_systematic` profile 控制检索器组合和优先级 |
| 检索结果缓存 | `shared/infra/search/cache.py`（新增或扩展） | 同一 `build_session_id` 内相同 query 不重复搜索 |
| `SkillResult` 扩展 | `shared/infra/skills/base.py` | 增加 `rounds_executed` / `gaps_remaining` / `confidence_level` 字段 |

### 只允许改动

- `shared/infra/skills/researcher.py`
- `shared/infra/search/`
- `shared/infra/skills/base.py`（SkillResult 扩展）

### 关键约束

- 微循环在 `ResearchConductor` 内部实现，不改 docgen graph 的 9 节点拓扑
- `sprint` 最多 1 轮补研究，`systematic` 最多 2 轮
- 每轮补检索作为独立 LangSmith span

### 验收标准

- `systematic` 模式下，章节研究能自动识别缺口并补检索
- LangSmith 中能看到 `research_round_1` / `research_round_2` / `assess_gaps` 等 span
- 同一 query 在同一 build session 内不重复搜索
- `sprint` 模式下研究速度不明显退化

---

## 9.5 Phase 3：课程模式硬约束与 Writer 升级

### 目标

让 `sprint` / `systematic` 的差异从”prompt 暗示”变成”结构性硬约束”。

### 具体改动清单

| 改动 | 文件 | 说明 |
|:---|:---|:---|
| 课程模式 prompt 模板 | `workflows/digest/prompts/`（新增或扩展） | `sprint_chapter_prompt` / `systematic_chapter_prompt` 分别定义章节必备区块 |
| `PedagogyWriter` 按模式分支 | `shared/infra/skills/writer.py` | 根据 `course_type` 选择不同的 prompt 模板和字数目标 |
| `ChapterDraft` 结构化 | `workflows/digest/shared/contracts.py` | 定义 `ChapterDraft` model，含 `markdown` / `word_count` / `required_elements_coverage` / `asset_hints` |
| `enrich_document_node` 按模式增强 | `docgen/nodes/enrich_document_node.py` | `sprint` 补速记卡/错因卡，`systematic` 补脉络图/推导说明 |
| `inject_examine_node` 按模式差异化 | `docgen/nodes/inject_examine_node.py` | `sprint` 注入真题范例/速测，`systematic` 注入形成性检查/延展问题 |
| 教学块定义 | `teaching/documents/content_blocks.py` | 扩展 `recap_block` / `formula_card_block` / `misconception_block` 等 |

### 验收标准

- `sprint` 文档每章必含：导读 + 核心概念 + 范例题 + 易错点 + 快速回顾
- `systematic` 文档每章必含：导读 + 概念体系 + 推导/论证 + 应用案例 + 章节总结 + 延展思考
- `systematic` 文档总字数稳定 ≥ 10000 字
- `sprint` 文档总字数在 4000-8000 字范围
- 前端渲染无异常

---

## 9.10 每个阶段都要验证的四件事

1. 不影响 `ingest / interact / examine / profile` 的主流程。
2. 不破坏 `digest/kg` 与 `digest/curriculum`。
3. LangSmith 图是否仍然一眼能看懂。
4. 前端是否还能稳定展示当前文档产物。

---

## 9.11 一句话结论

这轮重构最怕的不是“做得慢”，而是“边界没立住就乱改”。
正确路径是：先冻结边界，再升级 research，再升级呈现，最后接教学闭环与语料库。
