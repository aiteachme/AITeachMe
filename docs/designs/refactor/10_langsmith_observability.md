## 十、LangSmith 全链路可观测性

> 目标：保证这轮算法升级不是“黑盒优化”，而是每一步都能被看见、被比较、被定位。
> 最后更新：2026-04-10

---

## 10.1 观测目标

对这轮重构，LangSmith 至少要回答 4 个问题：

1. Planner 最终确认的课程合同是什么。
2. 每章 research 为什么会查这些来源、补这些 query。
3. Writer 和 teaching blocks 为什么让文档长成这样。
4. 富媒体 sidecar 和练习注入是否真的提升了质量，而不是拖慢流程。

---

## 10.2 必须保持的 trace 树

```text
API / service request
└── workflow root span
    ├── node span
    │   ├── workflow runtime span
    │   │   ├── research_round span
    │   │   ├── retriever span
    │   │   ├── scraper span
    │   │   └── llm span
    │   └── direct llm span
    └── publish / asset / eval span
```

关键要求：

- graph 拓扑清楚
- node 边界清楚
- workflow runtime 内部关键子步骤可下钻
- asset sidecar 和正文主链路分得开

---

## 10.3 最重要的业务 ID

所有 Docs Lane trace 至少统一带：

| 字段 | 作用 |
| --- | --- |
| `subject` | 学科/主题 |
| `user_id` | 用户定位 |
| `build_session_id` | 本次构建主链路 |
| `planner_session_id` | Planner 会话 |
| `confirmed_plan_id` | 已确认方案 |
| `course_type` | `sprint / systematic` |
| `retrieval_profile` | 期望检索策略 |
| `chapter_index` | fan-out 追踪 |
| `teaching_action` | 教学动作 |
| `asset_kind` | `mermaid / image / interactive_html / animation` |

后续新增的关键字段：

- `requested_profile`
- `applied_profile`
- `research_round`
- `gaps_remaining`
- `build_contract_version`
- `quality_score`

---

## 10.4 当前最需要补强的观测点

### 问题 1：profile 需要区分“请求的”和“真正执行的”

当前 state 里已经有 `retrieval_profile`，但执行层还没完全打通。
因此 trace 后续必须显式区分：

- `requested_profile`
- `applied_profile`

否则会出现“看上去是 systematic profile，实际上 retriever 组合没变”的假象。

### 问题 2：research 需要 round 级 trace

如果后续引入研究微循环，必须能看清：

- 第 1 轮查了什么
- 为什么触发第 2 轮
- 第 2 轮补了哪些 gaps
- 为什么停止

### 问题 3：asset 需要单独可见

Mermaid、image、interactive、animation 必须作为 sidecar span，而不是埋在正文节点输出里。

---

## 10.5 每个重点节点应该记录什么

### `load_context`

- `chapter_count`
- `course_type`
- `retrieval_profile`
- `has_confirmed_plan`
- `build_contract_version`

### `targeted_research`

- `chapter_index`
- `requested_profile`
- `applied_profile`
- `query_count`
- `research_rounds`
- `local_hits`
- `web_hits`
- `academic_hits`
- `curated_source_count`
- `gaps_remaining`
- `confidence_level`

### `pedagogy_craft`

- `chapter_index`
- `word_count`
- `required_elements_coverage`
- `teaching_block_count`
- `question_hook_count`
- `asset_hint_count`

### `enrich_document`

- `mermaid_count`
- `image_count`
- `interactive_block_count`
- `formula_block_count`
- `asset_failures`

### `inject_examine`

- `question_count`
- `practice_block_count`
- `practice_mode`

### `finalize_assemble`

- `published_doc_count`
- `built_paths`
- `asset_summary`
- `quality_score`

---

## 10.6 Workflow Runtime / Retriever / Scraper 的 metadata

### Workflow runtime

至少带：

- `runtime_name`
- `course_type`
- `retrieval_profile`
- `chapter_index`
- `research_stage`

### Retriever

至少带：

- `retriever_name`
- `source_class`
- `query`
- `result_count`
- `latency_ms`

### Scraper

至少带：

- `scraper_name`
- `url`
- `content_kind`
- `success`
- `content_length`

---

## 10.7 课程模式和算法的核心对比视图

### Dashboard 1：Docs Lane 总览

看：

- build 总耗时
- 节点耗时占比
- 失败率

### Dashboard 2：模式对比

看：

- `sprint / systematic` 平均耗时
- 平均字数
- 平均练习数
- 平均媒体数

### Dashboard 3：Research 质量

看：

- `requested_profile / applied_profile`
- local / edu_web / academic / general 的命中分布
- `gaps_remaining`
- `curated_source_count`

### Dashboard 4：LLM tier 与 fallback

看：

- `strategic / smart / fast` 占比
- fallback 频率
- 哪些节点最容易降级

### Dashboard 5：Asset sidecar

看：

- Mermaid 成功率
- image 成功率
- interactive / animation 调用频率
- asset 对总耗时的影响

---

## 10.8 前端事件与 LangSmith 对齐

前端进度事件建议尽量贴近 LangSmith node 语义：

- `plan_ready`
- `chapter_research_started`
- `chapter_research_completed`
- `chapter_draft_completed`
- `asset_generation_completed`
- `practice_injected`
- `publish_completed`

如果未来要引入 research 微循环，再补：

- `research_round_started`
- `research_gap_detected`
- `research_round_completed`

---

## 10.9 验收标准

以下四条至少全部满足：

1. 打开 LangSmith，能一眼看懂主流程与章节 fan-out。
2. 任意一章的 research round、writer、asset 都能独立定位。
3. 能对比 `requested_profile` 和 `applied_profile`。
4. 能比较不同课程模式、不同 research 深度、不同 asset 策略的效果。

---

## 10.10 一句话结论

LangSmith 在这轮重构里不是“埋点系统”，而是算法迭代的操作台。
如果 trace 不能回答“为什么查、为什么写、为什么补、为什么停”，后续优化就会重新变成黑盒。
