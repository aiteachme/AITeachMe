# 07. Examine 引擎

## 1. 目标与职责

Examine 负责把知识内容转成诊断式测评，并把测评结果回流给学习状态层。它的目标不是“随机出几道题”，而是形成完整测评闭环：

- 确定测评范围
- 组织试卷
- 判卷和错因分析
- 形成可追踪题目快照
- 把结果送回掌握度与学科级画像

---

## 2. 当前实现落点

当前 Examine 的对外资源组已经收口到 `exams`，底层主线是 workflow-backed 的压缩版考试模型。

### 2.1 当前正式路径

- 前端页面：`frontend/src/pages/ExamPage.tsx`
- 后端资源组：`exams`
- 业务入口：`backend/app/services/exams_service.py`
- 工作流编排：`backend/app/workflows/examine/*`
- 关键模型：
  - `question_template`
  - `exam_paper`
  - `exam_paper_item`
  - `subject.profile_json`
  - `user_knowledge_state`

补充说明：

- 旧 `exam/question/...` 表仍可能在仓库里残留，但不再是主设计
- `assessment` 不再是正式资源组名称
- `user_answer_attempt` 和 `review_task` 在目标态不再独立建表

---

## 3. 当前主 Pipeline

| 步骤 | 当前主模块 | 输入 | 输出 |
| --- | --- | --- | --- |
| 1. 模板构建 | `question_build_workflow.py` | `teaching_unit` 集合 | `question_template` |
| 2. 组卷 | `paper_assembler.py` / `exams_service` | `subject`、模式、数量、课程版本、学科级画像 | `exam_paper`、`exam_paper_item` |
| 3. 提交答案 | `exams_service.submit_exam_answers` | `exam_paper_id`、答案 | `exam_paper_item.answer_*` 字段 |
| 4. 判卷 | `exam_grade_workflow.py`、`answer_grader.py` | 试卷与作答 | `exam_paper_item` 判卷字段 |
| 5. 状态回流 | `workflows/profile/*` | 判卷结果 | `user_knowledge_state`、`subject.profile_json` 摘要 |

---

## 4. 核心设计原则

### 4.1 测评优先服务诊断，不是单纯刷题

Examine 的高价值不在“题目多”，而在“能知道哪里不会、为什么不会、下一步该补什么”。

### 4.2 测评范围必须绑定知识结构

新测评链路应优先围绕：

- `curriculum_version`
- `teaching_unit`
- `question_template`

来组织范围，而不是只依赖自由字符串知识点。

### 4.3 学科级画像必须进入组卷

`subject.profile_json` 不是展示字段，它至少要给组卷和出题提供：

- 当前目标考试或目标课程
- 偏好的题型结构
- 难度分布偏好
- 当前薄弱面摘要
- 速成课 / 系统课对应的测评风格先验

### 4.4 判卷结果必须结构化

可复用的判卷输出至少应包括：

- 是否正确
- 分数
- 错因标签
- 题目快照
- 与知识单元或节点的关联

这些结果在目标态直接落到 `exam_paper_item`，不再额外拆 `user_answer_attempt`。

### 4.5 测评必须接回状态层

测评不是终点，最终要回到：

- `user_knowledge_state`
- `subject.profile_json`
- 对话复盘
- 后续再练

---

## 5. 数据库写入对象

直接写入：

- `question_template`
- `exam_paper`
- `exam_paper_item`
- `user_knowledge_state`
- `subject.profile_json`

其中：

- 模板覆盖知识点并回 `question_template.node_refs_json`
- 组卷上下文并入 `exam_paper.selection_context_json`
- 运行时 job 只作为返回状态对象，不单独持久化成业务表

---

## 6. 本地落盘对象

当前 Examine 以数据库为主，没有强依赖的正式本地业务文件。

开发阶段如果需要补调试快照，统一写入：

- `data/<subject>/debug/examine.question_build/<job_id>/`
- `data/<subject>/debug/examine.generate/<job_id>/`
- `data/<subject>/debug/examine.grade/<job_id>/`

推荐只保存：

- 组卷选择理由摘要
- 模板命中统计
- 判卷汇总摘要

---

## 7. 关键状态推进

当前持久化状态主要看：

- `exam_paper.status`
- `exam_paper_item.answer_content / is_correct / score_obtained / feedback_text`
- `user_knowledge_state`
- `subject.profile_json`

如果需要 job 风格状态，应通过运行时返回对象表达，不再额外落库。

---

## 8. 节点到表责任

| 模块 | 读 DB | 写 DB | 写 FS |
| --- | --- | --- | --- |
| `question_builder.py` | `teaching_unit`、知识节点 | `question_template` | 无 |
| `paper_assembler.py` | `question_template`、`curriculum_version`、`subject.profile_json`、`user_knowledge_state` | `exam_paper`、`exam_paper_item` | 无 |
| `exam_grade_workflow.py` | `exam_paper`、`exam_paper_item` | `exam_paper.status`、`exam_paper_item` | 无 |
| `answer_grader.py` | `exam_paper_item`、知识节点 | `exam_paper_item` | 无 |
| `workflows/profile/mastery_updater.py` | `exam_paper*` | `user_knowledge_state` | 无 |
| `profile_service / 后续 profile 聚合模块` | `user_knowledge_state`、`exam_paper_item`、`subject` | `subject.profile_json` | 无 |

---

## 9. 开发关注点

### 9.1 新文档必须围绕正式主表写

任何继续写 Examine 设计的人，都不应再把 `exam/question/...`、`user_answer_attempt`、`review_task` 或 `*_job` 当成系统正式测评模型。

### 9.2 主线应该优先围绕课程版本、模板和画像

Examine 的核心价值在于“可追踪蓝图 + 可快照试卷 + 可回流状态 + 可利用画像调优”。

### 9.3 考试和小测可以共用同一套主表

无论是页面内直接作答的小测，还是后续可导出的真实试卷，本质上都还是：

- `exam_paper`
- `exam_paper_item`
- 配套导出产物或打印模板

不需要再为“小测”和“考试”拆两套主表。

---

## 10. 总结

Examine 当前的正式主线已经明确：围绕 `question_template -> exam_paper -> exam_paper_item -> user_knowledge_state` 组织测评闭环，并通过 `subject.profile_json` 挂住学科级出题先验。后续开发应继续强化这条主线，不再新增新的 legacy 表、legacy job 表和 `assessment` 命名分支。
