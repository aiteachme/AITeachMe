# 数据库精简方案（主题树 / 先修图 / 知识图谱 / 出题判题）

## 1) 现状判断

当前后端在“题目与画像”侧存在两套并行链路：

- 旧链路：`exam / question / exam_submission / answer_record / mistake + user_profile`
- 新链路：`question_template* / exam_paper* / user_answer_attempt / user_knowledge_state / review_task`

这会导致：

- 代码重复（出题、错题、薄弱点读取各有两套）
- 删除/清理逻辑复杂（容易漏删）
- API 概念重叠（`/exams/*` 与 `/exam/*` 并存）

在“主题树/先修图/KG”侧，模型本身是同一套，不是双轨；主要复杂度来自版本表数量与快照层次。

## 2) 建议保留/合并/删除

### 应保留（主干）

- `knowledge_node / knowledge_edge / evidence_link`（KG 真相层）
- `teaching_unit`（教学组织中层）
- `theme_tree_*`（主题导航视图）
- `prereq_dag_*`（先修依赖视图）
- `question_template* / exam_paper* / user_answer_attempt`（出题与判题）
- `user_knowledge_state / review_task`（画像与复习调度）

### 应删除（遗留）

- 旧考试链路：`exam / question / exam_submission / answer_record / mistake`
- 旧画像链路：`user_profile`

### 中期可合并（降低表数量）

- `theme_tree_version + prereq_dag_version + curriculum_snapshot`
  - 可演进为单一 `curriculum_version`（一条版本同时绑定 tree+dag 发布状态）
- `exam_paper_generation_context`
  - 可并入 `exam_paper.metadata_json`（若不需要强查询）

## 3) 本次已落地的低风险精简

- `interact` 历史节点优先读取新 assessment 数据（薄弱点、错题），旧链路仅兜底。
- 课程删除链路补齐新 assessment 表删除与计数，避免只清旧表导致残留。
- 删除预览统计已覆盖新旧两套考试/画像数据。

## 4) 推荐迁移顺序（避免中断）

1. 先保持旧 API 只读兼容，写入统一落到新链路。  
2. 增加一次性迁移脚本：旧 `mistake/user_profile` -> 新 `user_answer_attempt/user_knowledge_state`。  
3. 观察期后下线旧 API 与旧表。  
4. 再做版本层合并（`curriculum_version`），避免与业务迁移耦合。  

## 5) 目标结构（精简后）

- **KG 层**：知识事实（节点/边/证据）
- **课程视图层**：主题树 + 先修 DAG（同一版本发布）
- **评测层**：题模板、试卷快照、作答判题
- **学习状态层**：掌握度、复习任务

这样能把后端收敛成“单链路评测 + 单链路画像 + 单链路课程视图”，后续维护成本会明显降低。
