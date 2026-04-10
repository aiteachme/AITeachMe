## 四、Digest DocGen 流程升级

> 目标：把当前 DocGen 从”章节 fan-out 写作流程”升级为”教育型 deep research 文档生产流程”。
> 约束：只改 Docs Lane，不破坏 KG Lane、Curriculum Lane 和其他四大引擎。
> 最后更新：2026-04-10

---

## 4.1 当前基线（2026-04-10 校准）

当前 `docgen` 已有稳定的 **9 节点**流程：

```text
load_context
→ targeted_research (fan-out via Send)
→ collect_materials
→ resolve_titles          ← 后加的标题解析节点
→ pedagogy_craft (fan-out via Send)
→ collect_drafts
→ enrich_document
→ inject_examine
→ finalize_assemble
```

### 当前实际代码路径

| 节点 | 实现文件 | 核心依赖 |
|:---|:---|:---|
| `load_context` | `docgen/nodes/load_context_node.py` | 从 `confirmed_plan` dict 解析章节分配，调用 `prepare_shared_inputs()` |
| `targeted_research` | `docgen/nodes/targeted_research_node.py` | `ResearchConductor.run()` — 一次性 plan-search-compress |
| `collect_materials` | `docgen/nodes/collect_materials_node.py` | 汇聚 fan-out 结果 |
| `resolve_titles` | `docgen/nodes/resolve_titles_node.py` | 标题去重与规范化 |
| `pedagogy_craft` | `docgen/nodes/pedagogy_craft_node.py` | `PedagogyWriter.run()` — 章节写作 |
| `collect_drafts` | `docgen/nodes/collect_drafts_node.py` | 汇聚 fan-out 结果，合并 markdown |
| `enrich_document` | `docgen/nodes/enrich_document_node.py` | Mermaid / Image 占位符处理 |
| `inject_examine` | `docgen/nodes/inject_examine_node.py` | 练习题注入 |
| `finalize_assemble` | `docgen/nodes/finalize_node.py` | 最终组装与路径写入 |

### 上游编排

DocGen 不是独立运行的，它被 `unified/graph.py` 的 `run_parallel_lanes` 节点调用：

```text
unified: prepare_shared
→ run_parallel_lanes (asyncio.gather)
    ├── Doc Lane (docgen graph)
    └── KG Lane (kg graph)
→ derive_curriculum
→ publish_outputs
→ cleanup
```

### 当前基线的优点

- Docs Lane 与 KG / Curriculum Lane 已通过 unified graph 隔离
- LangGraph `Send()` fan-out / fan-in 结构清晰，章节并行可控（`docgen_max_parallel_chapters`）
- Research / Write / Enrich 的基本阶段已经存在
- `wrap_digest_node` 提供统一的 timing + tracing 包装
- `course_type` / `retrieval_profile` / `teaching_action` 已在 state 中流转

所以这轮重构不是推倒重来，而是在这个基线上升级。

---

## 4.2 当前还不够好的地方（2026-04-10 基于代码校准）

### 问题 1：`confirmed_plan` 是松散 dict，缺少 schema 约束

当前 `load_context_node` 从 `confirmed_plan` dict 中取值：

```python
# load_context_node.py 实际代码
plan_payload = deepcopy(state.get(“confirmed_plan”) or {})
digest_mode = str(plan_payload.get(“digest_mode”) or digest_mode)
tone = str(plan_payload.get(“tone”) or tone)
assignments = normalize_chapter_assignments(
    plan_payload.get(“chapter_plan”) or [],
    default_source_file_ids=list(state.get(“file_ids”, [])),
)
```

问题：
- 没有 Pydantic model 校验，字段缺失时 fallback 逻辑分散在多处
- `chapter_plan` 中每章的 `search_queries`、`required_elements`、`media_hints` 等字段全靠 `normalize_chapter_assignments()` 兜底
- Planner 对话输出的结构与 DocGen 期望的结构之间没有显式契约

### 问题 2：章节研究是一次性的，缺少质量驱动循环

当前 `targeted_research_node` 的核心逻辑：

```python
# targeted_research_node.py 实际代码
result = await researcher.run(
    queries=queries[:max(1, int(get_settings().docgen_max_queries_per_chapter))],
    section_packets=section_packets,
    chapter_assignment=assignment,
)
```

`ResearchConductor.run()` 内部做了 plan → search → compress → purify，但只跑一轮。缺少：
- 研究结果的缺口评估（哪些 `required_elements` 没有被覆盖？）
- 定向补检索（针对缺口生成新 query 再搜一轮）
- 质量置信度判断（当前材料是否足够支撑写作？）

这是与 gpt-researcher 的 `deep_research.py` 最大的差距——后者有递归的 breadth/depth 探索 + learnings 提取 + follow-up 生成。

### 问题 3：writer 和 enrich 节点未按课程模式做差异化

当前 `course_type` 已在 state 中流转（`resolve_docgen_course_type()` 已存在），但：
- `pedagogy_craft_node` 的 prompt 没有根据 `sprint` / `systematic` 做结构性差异
- `enrich_document_node` 的教学块补充逻辑没有按模式区分
- `inject_examine_node` 的练习注入没有区分”冲刺型速测”和”形成性检查”

### 问题 4：中间产物仍是自由 Markdown 字符串

`chapter_drafts` 和 `chapter_materials` 都是 `list[dict]`，但内部结构松散：
- `pedagogy_craft_node` 输出的 draft 只有 `markdown` + `chapter_index` + `word_count`
- 缺少 `required_elements_coverage`（必备要点覆盖情况）
- 缺少 `asset_hints`（媒体增强建议）
- 缺少 `question_hooks`（练习注入锚点）

这导致下游 `enrich_document` 和 `inject_examine` 只能靠正则匹配占位符，无法做结构化增强。

---

## 4.3 目标：教育型 Deep Research DocGen

我们要的是“像 deep research 那样研究”，但“产出是教学文档而不是通用报告”。

### 总体形态

```text
用户对话
→ Planner 形成 Build Contract
→ 章节级研究包构建
→ 教学写作
→ 教学增强
→ 媒体/交互产物补全
→ 练习注入
→ 发布
```

### 核心原则

1. 先确定课程合同，再开始构建。
2. 先做章节 research，再做教学写作。
3. 先把知识讲清楚，再加媒体和花样。
4. 富媒体是增强项，不得反向主导正文结构。
5. 所有阶段都必须在 LangSmith 中可读。

---

## 4.4 Build Contract：从松散 dict 到 Pydantic Model

### 当前状态

Planner 对话输出的 `confirmed_plan` 是一个松散 dict，`load_context_node` 通过 `.get()` 取值并逐字段 fallback。当前已有的字段包括：

```python
# 从 load_context_node.py 和 normalize_chapter_assignments() 反推的实际字段
confirmed_plan = {
    “digest_mode”: “sprint” | “systematic”,
    “tone”: “casual” | “professional” | “encouraging”,
    “plan_summary”: str,
    “user_goal”: str,
    “mode_reason”: str,
    “chapter_plan”: [
        {
            “chapter_index”: int,
            “title”: str,
            “objective”: str,
            “required_elements”: list[str],
            “search_queries”: list[str],
            “writing_instructions”: str,
            “media_hints”: {“images”: [], “mermaid”: [], “interactive”: []},
            “source_file_ids”: list[int],
        }
    ]
}
```

### 目标：定义 `BuildContract` Pydantic Model

后续 DocGen 不应再只吃一个宽泛的 `confirmed_plan`，而应明确依赖一份有 schema 约束的构建合同。

### 建议字段（在当前基础上扩展）

| 字段 | 类型 | 说明 | 当前是否已有 |
| --- | --- | --- | --- |
| `course_type` | `Literal[“sprint”, “systematic”]` | 课程模式 | ✅ 通过 `digest_mode` 间接推导 |
| `learning_goal` | `str` | 这份文档最终要帮助用户完成什么 | 🟡 `user_goal` 存在但不稳定 |
| `exam_context` | `ExamContext | None` | 考试名、题型偏好、分值导向 | ❌ 新增 |
| `tone` | `Literal[“casual”, “professional”, “encouraging”]` | 文风 | ✅ 已有 |
| `target_word_count` | `int` | 全文目标字数 | ❌ 新增，sprint 默认 6000，systematic 默认 12000 |
| `formula_depth` | `Literal[“light”, “standard”, “full_derivation”]` | 公式深度 | ❌ 新增 |
| `example_density` | `Literal[“low”, “medium”, “high”]` | 例题密度偏好 | ❌ 新增 |
| `media_preferences` | `MediaPreferences` | Mermaid / image / interactive HTML 的偏好 | 🟡 `media_hints` 在章节级存在 |
| `retrieval_profile` | `str` | 检索 profile 名 | ✅ 已有 `resolve_docgen_retrieval_profile()` |
| `profile_signals` | `list[str]` | 来自 learner profile 的难点、薄弱点 | ❌ 新增 |
| `chapter_contracts` | `list[ChapterContract]` | 每章的标题、目标、必备要点、输出要求 | ✅ 当前是 `chapter_plan` list[dict] |

### 实施策略

1. 先在 `workflows/digest/shared/contracts.py` 定义 `BuildContract` 和 `ChapterContract` Pydantic model
2. `load_context_node` 改为 `BuildContract.model_validate(confirmed_plan)` 一次性校验
3. Planner 输出端逐步对齐，新增字段先给默认值
4. 不改 Planner 对话流程本身，只收紧输出格式

---

## 4.5 推荐的新流水线

### 阶段 A：Planner 对话与 grounding

```text
user dialog
→ load_context
→ ground_concepts
→ draft_plan
→ user_feedback_loop
→ confirm_plan
```

这里已经接近当前设计，只需要进一步把输出收紧为 `Build Contract`。

### 阶段 B：章节研究包构建

当前 graph 仍保留 `targeted_research` 节点名，但内部能力要升级。

每个章节研究包建议包含：

- `dense_context`
- `source_ledger`
- `concept_gaps`
- `retrieval_profile`
- `local_hits / web_hits / academic_hits`
- `confidence_note`

### 阶段 C：教学写作

`PedagogyWriter` 不应只写“正文”，而应负责输出：

- 章节正文
- 本章导读
- 学习目标对照
- 必要的占位符与 block hint
- 章节级质量元信息

### 阶段 D：教学增强与媒体增强

`enrich_document` 不再只是“后处理占位符”，而是做三件事：

1. 根据课程模式补教学块
2. 解析和执行 media / interactive asset plan
3. 保证公式、引用、目录、章节统计的一致性

### 阶段 E：练习注入与发布

`inject_examine` 和 `finalize_assemble` 保留，但要更模式化：

- `sprint` 更偏真题范例、速测、错因提醒
- `systematic` 更偏形成性检查、章节回顾、延展问题

---

## 4.6 章节级”研究微循环”具体实施方案

### 当前代码路径

`targeted_research_node` → `ResearchConductor.run()` → 一次性返回 `SkillResult`

当前 `ResearchConductor` 内部已有 plan → search → compress → purify 的基本能力，但只跑一轮。

### 微循环设计（在 `ResearchConductor.run()` 内部实现）

```text
┌─────────────────────────────────────────────┐
│  ResearchConductor.run(queries, chapter)    │
│                                             │
│  1. plan_queries(chapter.search_queries)    │
│  2. retrieve(queries, profile)              │
│  3. curate(results)                         │
│  4. compress(curated_context)               │
│  5. assess_gaps(                            │
│       compressed_context,                   │
│       chapter.required_elements             │
│     )                                       │
│  6. IF gaps AND round < max_rounds:         │
│       generate_gap_queries(gaps)            │
│       → goto 2 (补检索)                     │
│  7. purify(final_context)                   │
│  8. return SkillResult(                     │
│       context, sources, gaps, confidence    │
│     )                                       │
└─────────────────────────────────────────────┘
```

### 关键实现细节

**缺口评估函数 `assess_gaps()`**：
- 输入：压缩后的上下文 + 章节 `required_elements` 列表
- 用 Fast LLM（`TaskType.DOCGEN_LIGHT`）判断哪些 required_elements 在当前上下文中覆盖不足
- 输出：`list[str]` 未覆盖的要点

**补检索 query 生成 `generate_gap_queries()`**：
- 输入：未覆盖的要点列表
- 用 Fast LLM 生成 1-3 个针对性搜索 query
- 输出：`list[str]` 新 query

**轮次控制**：
- `sprint`：`max_rounds=1`（最多补 1 轮），优先速度
- `systematic`：`max_rounds=2`（最多补 2 轮），优先完整性
- 每轮补检索前检查：如果 gaps 数量 ≤ 1 或上一轮没有新增有效结果，直接停止
- 触发 rate limit 时立即停止，不重试

**LangSmith 可观测性**：
- 每轮 retrieve/compress 作为独立 span（`research_round_1` / `research_round_2`）
- `assess_gaps` 作为独立 span，输出 gaps 列表
- 最终 `SkillResult` 中记录 `rounds_executed` / `gaps_remaining` / `confidence_level`

### 为什么先做成 skill 内部循环

- 不改变 docgen graph 的 9 节点拓扑，LangSmith 图保持清晰
- 便于按章节开关（某些章节本地材料充足，不需要补检索）
- 微循环的每一步仍能在 LangSmith 的 skill span 内部看见
- 后续如果需要更复杂的研究策略，可以在不改 graph 的前提下升级 skill 内部逻辑

---

## 4.7 建议引入的中间契约

### 4.7.1 `ChapterDraft`

建议不是只返回 `markdown`，而是附带结构信息：

| 字段 | 作用 |
| --- | --- |
| `markdown` | 当前章节主文本 |
| `chapter_index` | 章节索引 |
| `word_count` | 字数 |
| `required_elements_coverage` | 必备要点覆盖情况 |
| `asset_hints` | 媒体和交互增强建议 |
| `question_hooks` | 后续练习注入的锚点 |

### 4.7.2 `AssetPlan`

建议把媒体增强做成显式计划，而不只靠自由占位符：

| 资产类型 | 用途 |
| --- | --- |
| `mermaid` | 知识脉络图、流程图、对比图 |
| `image` | 配图、示意图、记忆图 |
| `interactive_html` | Desmos / GeoGebra / 交互习题 |
| `formula_card` | 公式总结块 |
| `summary_card` | 章节速记卡 |

MVP 阶段仍可继续保留 Markdown 占位符，但建议同时生成 `asset_plan` sidecar，为后续升级留出稳定接口。

---

## 4.8 对两种课程模式的流程差异

### `sprint`

- 更强的 exam / 题型导向
- 研究优先查“高频考点、典型题型、易错点”
- 每章更强调“可得分路径”
- 富媒体重点是速记图、对比表、错因卡

### `systematic`

- 更强的知识脉络和概念依赖
- 研究优先查“定义、推导、理论联系、应用展开”
- 每章更强调“为什么”和“如何连接”
- 富媒体重点是总图、章节概念图、推导说明图

---

## 4.9 不能动的边界

### 不改

- `digest/kg`
- `digest/curriculum`
- `ingest`
- `interact`
- `examine`
- `profile`

### 可以改

- `digest/planner`
- `digest/docgen`
- `shared/infra/skills`
- `shared/infra/search`
- `app.teaching.documents`

这条边界必须严格遵守，否则会把“文档升级”演变成“全仓大修”。

---

## 4.10 验收标准

### 功能层

- 用户可以在 Planner 对话中明确选择课程模式和文风
- `sprint` / `systematic` 的文档结构差异稳定可感知
- 文档可稳定输出公式、Mermaid、图片占位，后续可扩展交互 HTML

### 质量层

- `sprint` 文档更像“高质量冲刺讲义”，不是泛泛摘要
- `systematic` 文档能稳定达到 10000+ 字，并具备完整脉络
- 内容显著优于单次 AI 问答和原始 PPT 摘抄

### 观测层

- Planner 与 DocGen 可通过 `planner_session_id / confirmed_plan_id / build_session_id` 串联
- 每章研究与写作都能单独定位问题
- asset generation 和 question injection 也能单独看见

---

## 4.11 一句话结论

当前 DocGen 的骨架不用推翻。
真正要做的是：让 Planner 先产出清晰合同，让章节 research 更像 deep research，让文档产物从“自由 Markdown”升级为“带教学契约和媒体计划的课程文档”。
