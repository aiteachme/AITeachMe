# 07. Examine 引擎

## 1. 目标与职责

Examine 负责把知识内容转成诊断式测评，并把测评结果回流给学习状态层。它的目标不是“随机出几道题”，而是形成完整测评闭环：

- 确定测评范围
- 组织试卷
- 判卷和错因分析
- 形成可追踪答题记录
- 把结果送回掌握度与复习调度

---

## 2. 当前实现落点

当前 Examine 处于显式双轨期。

### 2.1 legacy 路径

- 前端页面：`frontend/src/pages/ExamPage.tsx`
- 后端资源组：`exams`
- 业务入口：`backend/app/services/exams_service.py`
- 关键模型：`exam`、`question`、`exam_submission`、`answer_record`、`mistake`

### 2.2 workflow-backed 新路径

- 后端资源组：`assessment`
- 业务入口：`backend/app/services/assessment_service.py`
- 工作流编排：`backend/app/workflows/examine/*`
- 关键模型：
  - `question_build_job`
  - `question_template`
  - `exam_generate_job`
  - `exam_paper`
  - `exam_paper_item`
  - `exam_grade_job`
  - `user_answer_attempt`

文档必须把这两条链路都写清楚，不能再假装系统里只有旧 `exam/question` 模型。

---

## 3. 当前主 Pipeline

### 3.1 legacy 测评链路

| 步骤 | 当前主模块 | 输入 | 输出 |
| --- | --- | --- | --- |
| 1. 组卷请求 | `POST /exams/make` | `subject`、题量、知识点 | legacy 试卷 |
| 2. 出题 | `exams_service.create_exam` | 知识点候选 | `exam`、`question[]` |
| 3. 交卷 | `POST /exams/submit` | `exam_id`、答案 | 判卷结果 |
| 4. 判卷与错题 | `exams_service.submit_exam` | 题目、答案 | `exam_submission`、`answer_record`、`mistake` |
| 5. 画像回流 | `profile_service` 相关逻辑 | 判卷结果 | `user_profile` |

### 3.2 workflow-backed 新测评链路

| 步骤 | 当前主模块 | 输入 | 输出 |
| --- | --- | --- | --- |
| 1. 模板构建 | `question_build_workflow.py` | `teaching_unit` 集合 | `question_template` |
| 2. 组卷 | `paper_assembler.py` / `assessment_service` | `subject`、模式、数量、快照 | `exam_generate_job`、`exam_paper`、`exam_paper_item` |
| 3. 提交答案 | `assessment_service.submit_exam_answers` | `exam_paper_id`、答案 | `user_answer_attempt` |
| 4. 判卷 | `exam_grade_workflow.py`、`answer_grader.py` | 试卷与作答 | `exam_grade_job`、已判分 attempts |
| 5. 状态回流 | `workflows/profile/*` | 判卷结果 | `user_knowledge_state`、`review_task` |

---

## 4. 核心设计原则

### 4.1 测评优先服务诊断，不是单纯刷题

Examine 的高价值不在“题目多”，而在“能知道哪里不会、为什么不会、下一步该补什么”。

### 4.2 测评范围必须绑定知识结构

新测评链路应优先围绕：

- `curriculum_snapshot`
- `teaching_unit`
- `question_template`

来组织范围，而不是只依赖自由字符串知识点。

### 4.3 蓝图要先于题目

试卷的稳定性来自蓝图层，而不只是题目内容本身。当前 assessment 链路已经比 legacy 链路更接近“先蓝图、后试卷快照”的设计。

### 4.4 判卷结果必须结构化

可复用的判卷输出至少应包括：

- 是否正确
- 分数
- 错因标签
- 题目快照
- 与知识单元或节点的关联

### 4.5 测评必须接回状态层

测评不是终点，最终要回到：

- `user_knowledge_state`
- `review_task`
- 对话复盘
- 后续再练

---

## 5. 数据库写入对象

### 5.1 legacy 链路

直接写入：

- `exam`
- `question`
- `exam_submission`
- `answer_record`
- `mistake`

并间接更新：

- `user_profile`

### 5.2 workflow-backed 新链路

直接写入：

- `question_build_job`
- `question_template`
- `question_template_node_link`
- `exam_generate_job`
- `exam_paper`
- `exam_paper_item`
- `exam_paper_generation_context`
- `exam_grade_job`
- `user_answer_attempt`

并在 Profile workflow 中继续推进：

- `user_knowledge_state`
- `review_task`

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

### 7.1 legacy 链路

主要通过：

- `exam`
- `exam_submission`

隐式表达流程状态。

### 7.2 workflow-backed 链路

显式状态表包括：

- `question_build_job`
- `exam_generate_job`
- `exam_grade_job`
- `exam_paper.status`

这套设计更适合：

- 幂等触发
- 长流程追踪
- 失败恢复
- 前端轮询状态

---

## 8. 节点到表责任

### 8.1 新链路主要责任矩阵

| 模块 | 读 DB | 写 DB | 写 FS |
| --- | --- | --- | --- |
| `question_build_workflow.py` | `teaching_unit`、图谱/课程对象 | `question_build_job` | 无 |
| `question_builder.py` | `teaching_unit`、知识节点 | `question_template`、`question_template_node_link` | 无 |
| `paper_assembler.py` | `question_template`、`curriculum_snapshot`、`user_knowledge_state`、`review_task` | `exam_paper`、`exam_paper_item`、`exam_paper_generation_context`、`exam_generate_job` | 无 |
| `exam_grade_workflow.py` | `exam_paper`、`exam_grade_job` | `exam_grade_job`、`exam_paper.status` | 无 |
| `answer_grader.py` | `exam_paper_item`、`user_answer_attempt`、知识节点 | `user_answer_attempt` | 无 |
| `workflows/profile/mastery_updater.py` | `exam_paper*`、`user_answer_attempt` | `user_knowledge_state` | 无 |
| `workflows/profile/review_scheduler.py` | `user_knowledge_state`、`review_task` | `review_task`、`forgetting_due_at` 相关字段 | 无 |

### 8.2 legacy 链路说明

legacy 责任主要集中在 `exams_service.py` 与旧 repo 层，不在当前新 workflow 中。

---

## 9. 开发关注点

### 9.1 新文档必须显式区分两条链路

任何继续写 Examine 设计的人，都不能再把 `Exam` / `Question` 当成系统唯一测评模型。

### 9.2 新链路应该优先围绕课程快照与模板

assessment 方向的核心价值在于“可追踪蓝图 + 可快照试卷 + 可回流状态”，这也是它优于 legacy 链路的地方。

### 9.3 前端当前可能仍更多消费 legacy 接口

这不是问题，但文档要写清楚“当前 UI 可用路径”和“后续演进主路径”不是同一个层次。

---

## 10. 总结

Examine 当前不是单一路径，而是：

- 一条仍对外服务的 legacy exam/profile 链路
- 一条已经落地到 workflow、job 表和新 assessment 模型的演进链路

后续开发应优先强化后者，同时在文档和代码里继续明确两条链路的边界、状态表和回流路径，避免再出现“文档描述只有旧世界，数据库却已经进入新世界”的漂移。
