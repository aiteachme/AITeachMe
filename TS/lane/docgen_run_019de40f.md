# DocGen 运行复盘：run-019de40f

来源文件：`E:\ChromeDownload\run-019de40f-1ed7-75f0-bb97-77bf8aace0b9.json`

这份导出包含 DocGen 根 run 的完整输入、输出 state 和 runtime metrics。它能还原本轮“从 confirmed plan 到发布 KnowledgeDoc”的主要过程，但没有展开每个 LLM 子调用的完整消息树。

## 1. 本次输入

本轮是一次 `sprint` 模式的 AI 课程知识文档生成：

| 字段 | 值 |
| --- | --- |
| `workflow` | `digest.docgen` |
| `lane` | `docgen` |
| `build_session_id` | `2eb0bfc880f745c1a0f2954d96a62a35` |
| `course_id` | `course_x8iqbgjs81mw` |
| `course_name` | `AI主线冲刺` |
| `user_id` | `usr_5e217330381e4abe872c` |
| `confirmed_plan_id` | `d32b140eadc54f5eaa7a250073cf8a3f` |
| `planner_session_id` | `cc7318e93d044cc1bc103d46f948edb1` |
| `digest_mode` | `sprint` |
| `retrieval_profile` | `docgen_sprint` |
| `file_ids` | 15 个 PDF |
| `runtime max_concurrency` | `20` |

注意：这份 DocGen trace 里的 `confirmed_plan.model_override` 是空字符串。它和 Planner run 里的 `model_override=deepseek-v4-flash` 不一致，所以这次运行里模型大概率回落到了系统默认模型，而不是首页选择模型。这也是 LangSmith 里仍看到 `qwen-flash` 的直接解释之一。

## 2. 资料与章节合同

本轮进入 DocGen 的文件是 15 份人工智能课程 PDF，覆盖绪论、搜索、知识表示、概率推理、机器学习、神经网络、深度学习和强化学习。

confirmed plan 固化为 7 章：

| 章 | confirmed title |
| --- | --- |
| 1 | 人工智能概述与智能体基础 |
| 2 | 问题求解与搜索策略 |
| 3 | 知识表示与逻辑推理 |
| 4 | 不确定知识与概率推理 |
| 5 | 机器学习基础与有监督学习 |
| 6 | 无监督学习与人工神经网络 |
| 7 | 深度学习与强化学习 |

构建约束：

| 字段 | 值 |
| --- | --- |
| `include_exercises` | `true` |
| `include_sources` | `false` |
| `math_mode` | `false` |
| `target_chapter_count` | `7` |
| `target_length` | `8000-30000字` |

资料理解包里有一个明显偏差：课程画像被识别为 `数学 / 离散数学 / exam_paper / advanced`，并带有“考试题目、答案策略”倾向。实际文件是 AI 课程讲义，这会影响 sprint 文风和题型导向，需要后续关注 profile 分类。

## 3. 本次流程实际发生了什么

```text
load_context
  读取 confirmed plan、15 个文件、241 个 material section、planner_context。
  输出 7 个 chapter_assignments 和 document_context。
  耗时约 0.7 秒。
  |
  v
prepare_global_seed
  infer_intent_core + summarize_files。
  生成 15 个 file summaries、7 组 source_affinity_by_chapter、65 个 high_confidence_evidence_units。
  这是本轮最重的准备阶段，耗时约 486 秒。
  |
  v
lock_titles_for_chapters
  按章锁标题，输出 7 个 locked titles。
  耗时约 8.1 秒。
  |
  v
confirm_and_seed_backbone
  规则合并 confirmed plan、标题、文件摘要和证据候选。
  输出 7 个 chapter_task_seeds，耗时约 3 毫秒。
  |
  v
build_document_backbone
  构建全局术语、依赖、符号和核心主张池。
  输出 27 个 glossary、6 个 dependency、32 个 notation、74 个 canonical claims。
  耗时约 10 毫秒。
  |
  v
build_chapter_execution_briefs
  为 7 章生成执行 brief。
  耗时约 35.6 秒。
  |
  v
assemble_chapter_tasks
  规则装配最终 ChapterGenerationPlan 和 7 个 ChapterGenerationTask。
  耗时约 7 毫秒。
  |
  v
generate_chapters
  7 章 fan-out 研究和写作。
  输出 7 个 drafts、7 组 research traces、claim/evidence/conflict ledgers。
  本轮累计 research_sources=91。
  research 阶段约 304 秒，draft 阶段约 599 秒。
  |
  v
enhance_chapters
  对 7 章处理增强和练习。
  输出 7 个 enhanced drafts、7 个 asset manifests、7 个 practice manifests。
  耗时约 3.7 秒。
  |
  v
review_content
  7 章并行 review + 整本一致性检查。
  所有章节单章 review 均未通过，但 document_consistency_report 通过。
  产出 48 个 review_actions。
  耗时约 174 秒。
  |
  v
repair_or_route
  执行可落地的 surface/section patch。
  evidence_patch 被降级记录为 unresolved warning。
  耗时约 59.9 秒。
  |
  v
merge_review -> sync_locked_titles -> publish_document
  合并 7 章，标题不再 LLM 改写，发布 KnowledgeDoc rows。
```

## 4. 标题与正文产物

最终 locked titles：

| 章 | locked title |
| --- | --- |
| 1 | 人工智能概述与智能体基础 |
| 2 | 问题求解与搜索策略：状态空间、盲目搜索与启发式搜索 |
| 3 | 基于知识的Agent与逻辑推理 |
| 4 | 不确定性与概率推理：贝叶斯规则与贝叶斯网络 |
| 5 | 机器学习基础与有监督学习：回归、分类及模型评估 |
| 6 | 无监督学习与人工神经网络：聚类、感知器及BP神经网络 |
| 7 | 深度学习与强化学习：CNN与Q-learning |

章节生成规模：

| 指标 | 值 |
| --- | --- |
| `chapter_drafts` | 7 |
| `enhanced_chapter_drafts` | 7 |
| `reviewed_chapter_drafts` | 7 |
| `research_traces` | 7 |
| `claim_ledgers / evidence_ledgers / conflict_reports` | 各 7 |
| `asset_manifests / practice_manifests` | 各 7 |
| `llm_calls_total` | 65 |
| `built_paths / doc_ids` | 7 / 7 |

发布出的 `KnowledgeDoc` ID 是 `5, 6, 7, 8, 9, 10, 11`，分别对应 7 个章节。

## 5. Review 与修补结果

本轮 review 是最值得注意的部分：

| 指标 | 值 |
| --- | --- |
| `chapter_review_reports` | 7 |
| 单章 review `passed` | 7 章全为 `false` |
| `document_consistency_report.passed` | `true` |
| `review_actions` | 48 |
| `unresolved_warnings` | 41 |
| `repair_trace` | 48 |
| `review_decision` | `fail` |
| `merge_review_report.decision` | `publish` |

review actions 分布：

| 类型 | 数量 | 实际处理 |
| --- | --- | --- |
| `surface_patch` | 3 | 可执行，部分应用 |
| `section_patch` | 11 | 可执行，部分应用 |
| `evidence_patch` | 34 | 当前不能自动补证据，降级为 unresolved warning |

repair trace 分布：

| 状态 | 数量 |
| --- | --- |
| `applied` | 7 |
| `skipped` | 7 |
| `downgraded` | 34 |

解释：当前实现允许 `repair_or_route` 把重动作记录为 warning，然后让 `merge_review` 做发布前收口。因此出现了 `review_decision=fail` 但 `merge_review_report.decision=publish` 的情况。这不是 trace 展示问题，而是当前产品策略：能发布，但会带大量 unresolved warning。

## 6. 数据写入

本轮 DocGen 主要写入：

| 阶段 | 写入或更新 |
| --- | --- |
| API 接受 / background lifecycle | build lock、docgen lane runtime、构建状态 |
| `publish_document` | 7 条 `KnowledgeDoc`、章节 Markdown、整本 Markdown、`docgen_manifest.json`、版本归档 |
| 查询 runtime | `doc_ids`、`built_paths`、review/repair/merge/title metrics |

本轮发布后，KG 自动同步用的是同一个 `build_session_id=2eb0bfc880f745c1a0f2954d96a62a35`，说明 DocGen 发布结果进入了后续 kg_doc_sync。

## 7. 结论

这次 DocGen 主链路没有崩，资料读取、章节生成、增强、发布都完整跑完。但它暴露了三个重要问题：

| 问题 | 判断 |
| --- | --- |
| 模型覆盖没有进入 DocGen confirmed plan | 这解释了为什么 LangSmith 仍显示默认模型；当前代码已围绕 `model_override` 做贯通，但这份历史 run 证明当时没有生效 |
| review fail 仍发布 | 需要产品上决定：`evidence_patch` 大量存在时是允许发布带 warning，还是阻断发布 |
| profile 误判为数学考试材料 | 会影响 sprint 写作策略，应后续优化资料画像或让 DocGen 使用更稳的课程领域信号 |
