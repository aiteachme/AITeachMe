## 四、Digest DocGen 流程升级

> 目标：把当前 DocGen 从“章节 fan-out 写作流程”升级为“教育型 deep research 文档生产流程”。
> 约束：只改 Docs Lane，不破坏 KG Lane、Curriculum Lane 和其他四大引擎。
> 最后更新：2026-04-09

---

## 4.1 当前基线

当前 `docgen` 已有稳定的 8 节点流程：

```text
load_context
→ targeted_research (fan-out)
→ collect_materials
→ pedagogy_craft (fan-out)
→ collect_drafts
→ enrich_document
→ inject_examine
→ finalize_assemble
```

这个基线已经具备三个优点：

- Docs Lane 与 KG / Curriculum Lane 已经分离
- LangGraph fan-out / fan-in 结构清晰
- Research / Write / Enrich 的基本阶段已经存在

所以这轮重构不是推倒重来，而是在这个基线上升级。

---

## 4.2 当前还不够好的地方

### 问题 1：用户选择还没有收敛成稳定的 Build Contract

用户希望在构建过程中通过对话确定：

- 是速成课还是系统课
- 面向考试还是学科系统学习
- 文风、深度、公式强度、例题密度
- 是否要更多 Mermaid / 配图 / 交互 HTML

当前这些意图分散在 `user_prompt`、planner 对话和若干隐式默认值里，后续很难稳定控制输出质量。

### 问题 2：章节研究还不够“deep research”

当前 `targeted_research` 已经有检索、抓取、压缩和提纯，但整体仍偏一次性：

- 查一轮
- 压一轮
- 直接交给写作

还缺少“识别缺口 -> 定向补检索 -> 再压缩”的质量驱动机制。

### 问题 3：文档仍然过度依赖 Markdown 字符串作为中间表达

这在早期是合理的，但当文档要支持：

- 公式卡片
- 思维导图
- 文生图
- 交互 HTML
- 章节统计卡
- 章节练习块

就需要更稳定的中间契约，而不是只依赖自由文本和占位符。

### 问题 4：产物模式约束不够硬

“速成课”和“系统课”已经被提出来了，但还没有成为真正的产物契约：

- 章节数范围
- 每章必含区块
- 字数下限
- 例题密度
- 富媒体密度
- 公式推导要求

都还需要收紧。

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

## 4.4 Build Contract：Planner 必须产出的上游契约

后续 DocGen 不应再只吃一个宽泛的 `confirmed_plan`，而应明确依赖一份更稳定的构建合同。

### 建议字段

| 字段 | 说明 |
| --- | --- |
| `course_type` | `sprint` / `systematic` |
| `learning_goal` | 这份文档最终要帮助用户完成什么 |
| `exam_context` | 若是考试型任务，记录考试名、题型偏好、分值导向 |
| `tone` | 文风，如 `casual` / `professional` / `encouraging` |
| `target_word_count` | 全文目标字数 |
| `formula_depth` | `light` / `standard` / `full_derivation` |
| `example_density` | 例题密度偏好 |
| `media_plan` | Mermaid / image / interactive HTML / tables 的偏好 |
| `retrieval_profile` | `planner_grounding` / `docgen_sprint` / `docgen_systematic` |
| `profile_signals` | 来自 learner profile 的难点、薄弱点、偏好 |
| `chapter_contracts` | 每章的标题、目标、必备要点、输出要求 |

### 设计意图

- Planner 负责“先把课设计清楚”
- DocGen 负责“按合同把课做出来”
- 这样才能让后续调优集中在具体质量问题，而不是反复猜用户意图

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

## 4.6 章节级“研究微循环”建议

为了不把 graph 切得过碎，也为了保持 LangSmith 图可读，推荐把 deep research 的“递进式补研究”先放在 `ResearchConductor` 内部，而不是马上扩成更多 graph 节点。

### 微循环结构

```text
plan queries
→ retrieve
→ curate
→ compress
→ assess gaps
→ (需要时再补一轮 retrieve/compress)
→ purify
```

### 适用规则

- `sprint`：默认最多 1 轮补研究，优先速度
- `systematic`：允许 1-2 轮补研究，优先完整性
- 一旦触发 rate limit 或质量收益过低，直接停止补研究

### 为什么先做成 skill 内部循环

- 不污染 graph 结构
- 便于按章节开关
- 依旧能在 LangSmith 里看见 skill 内部的研究阶段

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
