# 13. Database Schema Inventory

## 1. 文档定位

这份文档是当前数据库主设计文档，也是数据库层唯一真相源。

这一轮的核心原则很明确：先用尽可能简单的实现把当前功能闭环跑通，不为了“未来可能会有版本历史”提前拆出一批 version 表。

当前结论：

- 业务主表目标收敛到 `18` 张左右
- `chunk_embeddings` 只算向量实现层，不算业务主表
- `theme_tree_version` 和 `prereq_dag_version` 不再作为目标态主表
- `curriculum_version` 也不再按“版本表”思路设计，目标态改为 `curriculum` 当前态主表
- 版本语义优先通过字段实现，不额外起表
- `membership / revision / alias / evidence / attempt / review_task` 继续并回主表字段或 JSON
- 2026-04 这轮 examine/profile 调整未新增业务主表，仍在既有 schema 上演进

如果短期代码兼容需要，物理表名可以暂时沿用旧名字，但设计语义要先统一到“当前态主表 + 修订字段”。

---

## 2. 收敛原则

1. 先服务当前五大引擎闭环，不为低频历史追溯过度设计。
2. 外部模块要能轻松消费 core，所以数据库优先暴露稳定主对象：
   `subject / curriculum / teaching_unit / knowledge_node / exam_paper`。
3. 中文优先，课程组织、命名、锚点管理要适合中文教学场景。
4. 版本先用字段表达，而不是拆版本表。优先使用：
   `version_no / build_session_id / is_current / published_at / updated_at / source_hash`
5. 当前态结构优先按学科整体替换：
   一次 digest 重建时，事务性替换该学科当前 `theme_tree_node` 与 `unit_dependency`。
6. 只有满足下面任一条件，才值得再拆表：
   独立分页查询、高频过滤更新、独立生命周期、强唯一约束、跨模块直接复用。

---

## 3. 当前目标主树

```text
user
  └─ 1:N subject
        ├─ 1:N raw_file
        ├─ 1:N retrieval_chunk
        ├─ 1:N knowledge_document
        ├─ 1:N knowledge_node
        │     └─ 1:N knowledge_edge
        ├─ 1:N teaching_unit
        ├─ 1:N taxonomy_anchor
        ├─ 1:N curriculum
        │     ├─ 1:N theme_tree_node
        │     └─ 1:N unit_dependency
        ├─ 1:N question_template
        ├─ 1:N exam_paper
        │     └─ 1:N exam_paper_item
        ├─ 1:N user_knowledge_state
        └─ 1:N chat_session
              └─ 1:N chat_message
```

说明：

- `curriculum` 是“课程构建主表”，当前实现用单表同时承载当前生效态和轻量历史。
- 同一学科只允许一条 `published + is_current=true` 的当前记录；旧构建可继续留在同一张 `curriculum` 表中。
- `theme_tree_node` 和 `unit_dependency` 直接挂在当前 `curriculum` 下，不再各自挂一个 version 表。
- `knowledge_document.version_no`、`knowledge_node.build_revision_no`、`knowledge_edge.build_revision_no` 必须与当前 `curriculum.version_no` 对齐；同一轮 digest 中，知识文档和知识图谱共用同一版号。
- 如果以后真的要保留多次发布历史，再额外引入 release/history 表，而不是现在先把三套 version 表铺开。

---

## 4. 18 张业务主表

### 4.1 用户与学科

1. `user`
   顶层拥有者。保存账号信息、最近 IP、用户级 `profile_json`。
   当前 `profile_json` 用来承载跨学科轻量学习画像摘要，例如常用考试模式、偏好题型、讲解风格、学习节奏。

2. `subject`
   学科工作空间根。保存学科名、描述、偏好的 digest 模式、学科级 `profile_json`、`settings_json`。
   当前 `profile_json` 是 owner-scoped 的学科画像摘要，用来表达这门课下一步更适合怎么练、怎么考。

### 4.2 原始资料与检索

3. `raw_file`
   用户上传的原始资料。保存源文件路径、Markdown 路径、解析结果、资源清单、材料画像、识别出的学科信息。

4. `retrieval_chunk`
   统一检索切块表。直接挂在 `raw_file` 下，保存标题、层级、`header_path`、chunk 内容、向量引用信息。
   当前代码应直接使用 `subject + document_id + title + header_path + content` 这组字段，不再假设旧版 `subject_id / source_id / chunk_role`。

### 4.3 知识文档与图谱

5. `knowledge_document`
   digest 产出的正式知识文档。支持章节、文档包、`build_session_id`、`version_no`、模式判定、manifest、source scope。

6. `knowledge_node`
   知识图谱节点主表。保存 `canonical_name`、摘要、正文、`aliases_json`、`evidence_refs_json`。

7. `knowledge_edge`
   知识图谱边主表。保存 `source/target`、`edge_type`、描述、`evidence_refs_json`。

### 4.4 教学结构与课程快照

8. `teaching_unit`
   教学单元主表。是 digest / examine / profile 的共同锚点。成员节点关系并入 `member_node_refs_json`。

9. `taxonomy_anchor`
   课程锚点主表。负责中文教学分类、人工纠偏、主题树命名约束。

10. `curriculum`
    课程构建主表。一个学科可以保留多条同表历史，但任意时刻只允许一条 current/published 记录。

    建议核心字段：
    `subject`、`version_no`、`status`、`summary`、`blueprint_json`、`tree_json`、
    `dependency_json`、`build_context_json`、`build_session_id`、`is_current`、`published_at`、`updated_at`。

11. `theme_tree_node`
    当前态主题树节点表。保留独立节点，支持树形查询、分页、UI 展示。节点挂载的教学单元继续并入 `unit_refs_json`。

    目标语义上不再需要独立 `theme_tree_version` 主表。
    兼容实现可以暂保留 `tree_version_id` 这个字段名，但它实际应引用 `curriculum.id`。

    当前态建议约束为：
    `subject + curriculum_id(tree_version_id) + parent_tree_node_id`

12. `unit_dependency`
    当前态教学单元依赖边表。因为要按 `source/target` 独立查询、分析薄弱链路、服务组卷和画像，所以继续保留。

    目标语义上不再需要独立 `prereq_dag_version` 主表。
    兼容实现可以暂保留 `dag_version_id` 这个字段名，但它实际应引用 `curriculum.id`。

    当前态建议约束为：
    `subject + curriculum_id(dag_version_id) + source_unit_id + target_unit_id`

### 4.5 出题、试卷、画像

13. `question_template`
    题模板主表。知识点关联继续并入 `node_refs_json`。如需记录当时课程快照，当前实现优先保留 `curriculum_version_id`，需要版号时再通过 `curriculum.version_no` 回查。
    当前 examine 实现应在模板生成时就写入 `curriculum_version_id`，不应长期留空。

14. `exam_paper`
    试卷主表。保存组卷上下文、模式、总分、得分、状态。需要回溯时，优先保存 `curriculum_version_id` 和 `selection_context_json` 快照，而不是依赖单独版本表。
    `duration_seconds` 用来记录用户从拿到试卷到提交答卷的大致用时；生成试卷和判卷耗时暂不落业务字段，优先走 runtime timing summary。
    `exam_mode` 目标态当前收敛到两类：`web_practice`（网页测验）与 `paper_exam`（可打印考卷）；历史模式值由服务层兼容映射。
    `selection_context_json` 当前还会承载 `requested_difficulty`、`style_profile`、`resolved_teaching_unit_ids`、`section_plan` 与 `export_artifacts` 等运行时快照。

15. `exam_paper_item`
    试卷题目快照表。直接承载用户答案、判卷结果、错误原因、反馈文本。
    当前实现还保留 `time_spent_seconds / hint_used / confidence_self_report` 这些轻量交互字段，后续前端可继续补齐采集。

16. `user_knowledge_state`
   学习状态主表。保存掌握度、稳定度、遗忘时间、复习调度字段。`review_task` 已并回这里，`state_version` 保留为字段即可。
   `stats_json` 当前继续承载近几轮作答行为摘要，例如题型分布、难度分布、错因分布、提示使用情况和平均答题耗时。

### 4.6 聊天

17. `chat_session`
    聊天会话元信息表。

18. `chat_message`
    聊天消息表。引用上下文并入 `contexts_json`，额外元数据并入 `meta_json`。

---

## 5. 被移除并收敛的表

下面这些表不再进入目标态主设计：

- `theme_tree_version`
  并入 `curriculum.version_no / status / published_at`

- `prereq_dag_version`
  并入 `curriculum.version_no / dependency_json / published_at`

- `curriculum_version`
  改为 `curriculum` 当前态主表语义；短期兼容实现可暂沿用旧物理表名

- `raw_file_asset`
  并入 `raw_file.asset_manifest_json`

- `document`
  语义并入 `raw_file`

- `document_chunk`
  收敛为 `retrieval_chunk`

- `chunk_embedding`
  只保留物理向量表 `chunk_embeddings`

- `knowledge_alias`
  并入 `knowledge_node.aliases_json`

- `knowledge_revision`
  并入 `knowledge_node.summary / body_markdown`

- `edge_revision`
  并入 `knowledge_edge.description`

- `evidence_link`
  并入 `knowledge_node.evidence_refs_json` 与 `knowledge_edge.evidence_refs_json`

- `teaching_unit_revision`
  并入 `teaching_unit.title / summary / learning_objectives_json`

- `teaching_unit_membership`
  并入 `teaching_unit.member_node_refs_json`

- `unit_tree_membership`
  并入 `theme_tree_node.unit_refs_json`

- `question_template_node_link`
  并入 `question_template.node_refs_json`

- `user_answer_attempt`
  并入 `exam_paper_item`

- `review_task`
  并入 `user_knowledge_state`

- `graph_digest_job / curriculum_derive_job / question_build_job / exam_generate_job / exam_grade_job`
  当前阶段不单独落业务表，优先用现有任务状态字段、事件流或运行时缓存承载

- `subject_build_lock`
  当前阶段优先用轻量锁实现，不单独设计持久化主表

---

## 6. 版本如何简单实现

这轮不再设计“theme tree 一个版本表、dag 一个版本表、curriculum 再一个版本表”的三层版本体系。

当前推荐做法：

1. `curriculum` 用一张表承载当前态和轻量历史
   一个学科可以保留多条同表构建记录，但只有一条 `published + is_current=true`；`version_no` 自增即可。

2. `theme_tree_node` 和 `unit_dependency` 不再挂独立版本主表
   直接引用同一个 `curriculum.id`；兼容实现中 `tree_version_id / dag_version_id` 只是旧字段名。

3. 知识文档与知识图谱共享同一轮构建版号
   在 unified digest 中应满足：
   - `knowledge_document.version_no == curriculum.version_no`
   - `knowledge_node.build_revision_no == curriculum.version_no`
   - `knowledge_edge.build_revision_no == curriculum.version_no`
   - `theme_tree_node.tree_version_id == unit_dependency.dag_version_id == curriculum.id`

4. 需要追溯时优先存“当时快照字段”
   例如：
   - `knowledge_document.version_no`
   - `question_template.template_version`
   - `question_template.curriculum_version_id`
   - `exam_paper.curriculum_version_id`
   - `user_knowledge_state.state_version`
   - `exam_paper.selection_context_json`

5. digest 重建采用事务性替换
   推荐流程：
   - 先在内存或临时对象中完成 build
   - 开事务
   - 创建/发布新的 `curriculum.version_no`
   - 替换该学科当前 `theme_tree_node`
   - 替换该学科当前 `unit_dependency`
   - 更新 `knowledge_document.is_current` 与 `knowledge_document.version_no`
   - 回写 `knowledge_node.build_revision_no / knowledge_edge.build_revision_no`
   - 提交事务

6. 真要保历史时，再追加历史表
   未来如果确实需要“查看任意历史课程版本”，再补：
   `curriculum_release` 或 `curriculum_history`
   而不是现在先把所有版本表建出来。

补充：

- `exam_generate_job / exam_grade_job` 仍然不作为业务主表；当前 examine 只保留 runtime job 语义和 timing summary 日志。
- 如果未来真的要支持可轮询的长任务，再考虑在任务系统层补持久化 job，而不是先把考试域业务表扩成 job 表。
- 这轮 profile 聚合（`subject.profile_json` / `user.profile_json`）继续沿用现有字段，不新增独立 profile summary 表。
- `LEARNER.md` 当前落在 `backend/data/users/<user_id>/LEARNER.md`，它是运行时画像文档，不新增数据库主表。

### 补充：当前画像与行为摘要字段约定

- `user.profile_json`
  当前承载跨学科轻量用户画像，重点字段包括：
  `preferred_question_types / preferred_exam_modes / dominant_exam_mode / explanation_style / pace_preference / consistency_level / recent_subject_ids / active_subject_count / generated_at`

- `subject.profile_json`
  当前承载 owner-scoped 学科画像摘要，重点字段包括：
  `recommended_exam_mode / recommended_question_count / recommended_question_types / difficulty_focus / focus_teaching_unit_ids / focus_node_ids / due_review_count / pending_review_count / question_type_accuracy / difficulty_accuracy / generated_at`

- `user_knowledge_state.stats_json`
  当前承载近几轮作答行为摘要，重点字段包括：
  `question_type_counts / difficulty_counts / error_cause_counts / hint_used_count / avg_time_spent_seconds / avg_confidence_self_report / last_question_type / last_difficulty / last_error_cause_label`

这些字段当前都按“当前态聚合摘要”来设计，不单独起 history/version 表。

---

## 7. 为什么不是再压到 16 张

这轮不继续往下硬压，原因也很明确：

- `taxonomy_anchor` 需要独立管理，不适合揉进大 JSON
- `theme_tree_node` 需要独立树查询、分页和展示
- `unit_dependency` 需要按边查询、分析和回溯

如果再继续压：

- 主题树会退化成一个超大 JSON blob
- 先修依赖分析会明显变差
- 图谱页、课程页、薄弱点分析、组卷链路都会变得更难维护

所以当前以 `18` 张业务主表作为更稳妥的简单实现。

---

## 8. 当前实现边界

当前目标态强调的是：

- 先把当前态数据模型做薄、做稳
- 先让 ingest / digest / interact / examine / profile 共用同一组主对象
- 先让外部模块容易消费 `curriculum / teaching_unit / knowledge_node`
- 先避免“为了历史而历史”的过度拆表

向量层仍会创建这些物理表：

- `chunk_embeddings`
- sqlite-vec 的内部辅助表

这些都不算业务主表。

另外，`paper_exam` 会在文件系统落盘导出到 `backend/data/<subject>/exam/`（同步写 `md/tex`，后台尽力补 `pdf`），这属于运行时文件产物，不新增数据库主表。

---

## 9. 一句话结论

当前数据库目标态不是“三套版本表并行”，而是：

- 主表控制在 `18` 张左右
- `theme_tree_version / prereq_dag_version / curriculum_version` 不再作为目标态主表
- 版本优先通过字段实现
- 真正需要独立查询的结构表继续保留
- 其余 support 表尽量并回主表字段或 JSON
- 以后真的出现历史版本刚需，再补 history/release 表
