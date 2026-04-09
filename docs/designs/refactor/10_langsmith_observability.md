## 十、LangSmith 全链路可观测性

> 目标：保证后续所有重构都不是“黑盒升级”，而是每一步都能被看见、被比较、被定位。  
> 最后更新：2026-04-09

---

## 10.1 观测目标

后续 Digest 重构一定要满足下面三个目标：

1. 能看清 Planner 如何决定课程合同。
2. 能看清每章 research / write / enrich / examine 的耗时和质量差异。
3. 能把不同课程模式、不同检索 profile、不同媒体策略拉出来比较。

如果做不到这三点，后续调优会非常低效。

---

## 10.2 必须保持的 trace 层次

推荐统一成下面这棵树：

```text
API / service request
└── workflow root span
    ├── node span
    │   ├── skill span
    │   │   ├── retriever span
    │   │   ├── scraper span
    │   │   └── llm span
    │   └── direct llm span
    └── publish / asset / eval span
```

### 关键要求

- graph 拓扑清楚
- node 粒度清楚
- skill / retriever / scraper / llm 都能下钻

### 禁止事项

- 新增第二套 tracing 系统
- workflow runtime 和 node wrapper 之外自行乱开根 span
- 在关键动作里完全不打 metadata

---

## 10.3 关键关联 ID

所有 Docs Lane 相关 trace，建议最少统一带以下字段：

| 字段 | 作用 |
| --- | --- |
| `subject` | 学科或主题 |
| `user_id` | 用户定位 |
| `build_session_id` | 本次构建主链路 ID |
| `planner_session_id` | Planner 会话关联 |
| `confirmed_plan_id` | 已确认方案关联 |
| `digest_mode` | `sprint` / `systematic` |
| `course_type` | 与 `digest_mode` 同语义或保留扩展 |
| `chapter_index` | 章节 fan-out 追踪 |
| `retrieval_profile` | 检索策略标识 |
| `asset_kind` | `mermaid` / `image` / `interactive_html` |
| `teaching_action` | 教学动作标识 |

其中最重要的是：

- `build_session_id`
- `planner_session_id`
- `confirmed_plan_id`
- `chapter_index`

这四个字段决定你能不能跨 graph 把一条链拉通。

---

## 10.4 Planner 与 DocGen 的跨图关联

这是当前后续调优最关键的一条链。

### 推荐关系

```text
planner session
→ confirmed plan
→ docgen build
→ practice injection
→ publish result
```

### 必须做到

- Planner graph 的输出 trace 能定位到 `confirmed_plan_id`
- DocGen graph 的每章 trace 能带上 `planner_session_id` 和 `confirmed_plan_id`
- 如果后续 `inject_examine` 生成练习，也应沿用同一主链路 ID

这样打开 LangSmith 时，才能从“用户如何下需求”一路看到“文档为何长成这样”。

---

## 10.5 Docs Lane 重点节点应该记录什么

### `load_context`

- `chapter_count`
- `has_confirmed_plan`
- `digest_mode`
- `retrieval_profile`

### `targeted_research`

- `chapter_index`
- `query_count`
- `local_hits`
- `web_hits`
- `academic_hits`
- `curated_source_count`
- `retriever_names`
- `compression_mode`
- `gap_fill_rounds`

### `pedagogy_craft`

- `chapter_index`
- `word_count`
- `required_elements_coverage`
- `placeholder_count`
- `teaching_block_count`

### `enrich_document`

- `mermaid_count`
- `image_count`
- `interactive_block_count`
- `latex_normalized`
- `asset_failures`

### `inject_examine`

- `question_count`
- `practice_block_count`
- `practice_mode`

### `finalize_assemble`

- `doc_ids`
- `built_paths`
- `staged_chapter_count`
- `published_doc_count`

---

## 10.6 Skill / Retriever / Scraper 必须补充的 metadata

### Skill

建议所有组合 Skill 至少带：

- `skill_name`
- `research_stage`
- `chapter_index`
- `digest_mode`
- `retrieval_profile`

### Retriever

建议至少带：

- `retriever_name`
- `source_class`
- `query`
- `result_count`
- `latency_ms`

其中 `source_class` 推荐统一成：

- `local_user_material`
- `local_edu_corpus`
- `edu_web`
- `academic_web`
- `general_web`

### Scraper

建议至少带：

- `scraper_name`
- `url`
- `content_kind`
- `success`
- `content_length`

---

## 10.7 课程模式对比视图

LangSmith 后续应该重点支持下面几类对比：

### `sprint` vs `systematic`

比较：

- 总时延
- 总 token
- research 阶段耗时占比
- 每章字数
- 例题 / 练习块数量
- 媒体生成成功率

### 检索 profile 对比

比较：

- `planner_grounding` 命中率
- `docgen_sprint` 命中率
- `docgen_systematic` 命中率
- 本地命中与外部命中的占比

### asset 策略对比

比较：

- 仅 Mermaid
- Mermaid + image
- Mermaid + image + interactive

---

## 10.8 推荐 Dashboard

### Dashboard 1：Docs Lane 总览

看：

- build 总耗时
- 节点耗时占比
- 失败率

### Dashboard 2：课程模式对比

看：

- `sprint` / `systematic` 的平均耗时、字数、token

### Dashboard 3：Research 质量

看：

- retriever 命中数
- curated source 数
- 本地/外部来源占比

### Dashboard 4：媒体生成

看：

- Mermaid 成功率
- image 成功率
- interactive block 占比

### Dashboard 5：Fallback 与 rate limit

看：

- LLM fallback 频率
- retriever 失败率
- scraper 失败率
- 并发压力下的异常分布

---

## 10.9 前端事件与 LangSmith 对齐

建议前端实时事件不要再使用完全独立的一套命名，而应尽量和 LangSmith node 语义贴近。

### 推荐事件语义

- `planner_grounding`
- `plan_confirmed`
- `chapter_research_progress`
- `chapter_draft_progress`
- `asset_generation_progress`
- `practice_injected`
- `publish_completed`

这样用户界面、日志和 LangSmith 三套视角会更容易相互对照。

---

## 10.10 验收标准

以下四条至少要全部满足：

1. 打开 LangSmith，能一眼看出主流程、章节 fan-out、失败位置。
2. 任意一章的 research 和 writing 都能单独追踪。
3. 能把 Planner 决策和最终文档结果串起来。
4. 能比较不同课程模式、不同检索 profile、不同媒体策略的效果。

---

## 10.11 一句话结论

LangSmith 在这个项目里不是“埋点系统”，而是后续所有重构的操作台。  
如果 trace 树不清楚，后面越做越复杂时，整个系统会很难继续优化。
