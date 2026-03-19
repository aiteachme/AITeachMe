# 需求文档：Assessment & Mastery Layer（第四层：测评与掌握度层）

## 简介

在 AITeachMe 现有三层知识架构（知识图谱 → 教学单元 → 课程视图）之上，构建第四层——测评与掌握度层。该层以 TeachingUnit + KnowledgeNode 的掌握状态为核心资产，而非以"题目"为中心。考试是诊断载体，真正的价值在于用户对每个教学单元/知识节点的掌握状态追踪与遗忘风险驱动的复习调度。

该层严格依赖现有三层架构：
- 知识图谱（KnowledgeNode / KnowledgeEdge）提供知识真相
- 教学单元（TeachingUnit / TeachingUnitMembership）提供组织粒度
- 主题树（ThemeTree）/ 先修 DAG（PrereqDag）提供导航与学习路径
- CurriculumSnapshot 确保考试生成时的课程结构一致性

## 术语表

- **Assessment_Layer**: 测评与掌握度层，AITeachMe 第四层架构，负责出题、组卷、判卷、掌握度追踪与复习调度
- **QuestionTemplate**: 题目模板，绑定到 TeachingUnit + KnowledgeNode 的可复用题目原型，包含题干、选项、标准答案、解析、难度、题型
- **ExamPaper**: 试卷，组卷结果实体，包含考试模式（ExamMode）、关联的 CurriculumSnapshot 版本引用、用户 ID
- **ExamPaperItem**: 试卷题目条目，ExamPaper 与 QuestionTemplate 的关联表，包含题目内容快照以保证试卷不可变性
- **UserAnswerAttempt**: 用户作答记录，包含用户答案、用时（time_spent）、是否使用提示（hint_used）、自信度自评（confidence_self_report）
- **UserKnowledgeState**: 用户知识状态，以 TeachingUnit 和 KnowledgeNode 双粒度追踪掌握度，包含 mastery_score、confidence_score、stability_score、forgetting_due_at、review_priority
- **ReviewTask**: 复习任务，复习队列条目，类型包含 review_unit / review_node / review_exam / prereq_patch
- **Examine_Engine**: 测验引擎，包含 question_builder（题目生成）、paper_assembler（组卷）、answer_grader（判卷 + 错因标注）
- **Profile_Engine**: 画像引擎，负责掌握度更新（MVP 阶段使用统计方法，后续升级 BKT/DKT）与薄弱分析
- **Weakness_Analyzer**: 薄弱分析器，综合掌握度、近期错误、先修缺口、遗忘风险、考试权重进行薄弱诊断
- **Review_Scheduler**: 复习调度器，基于 SM-2 启发的间隔重复算法，按知识单元和遗忘风险调度复习
- **ExamMode**: 考试模式枚举，包含 diagnostic（诊断测试）、practice（练习）、weakpoint_boost（薄弱强化）、review（遗忘曲线复习）、mock_final（模拟考试）
- **QuestionBuildJob**: 题目构建任务，按 TeachingUnit 增量生成 QuestionTemplate 的异步任务
- **ExamGenerateJob**: 组卷任务，按用户状态生成个性化 ExamPaper 的异步任务
- **ExamGradeJob**: 判卷任务，自动判分 + 错因标注的异步任务
- **MasteryUpdateJob**: 掌握度更新任务，根据判卷结果更新 UserKnowledgeState + 生成 ReviewTask 的异步任务
- **SM2_Algorithm**: SM-2 间隔重复算法，用于计算复习间隔与间隔扩展因子
- **BKT**: 贝叶斯知识追踪模型（Phase 3 预留）
- **DKT**: 深度知识追踪模型（Phase 3 预留）
- **ErrorCauseLabel**: 错因标签，判卷时为错误答案标注的错因分类（如概念混淆、计算错误、先修缺失等）

## 需求


### 需求 1：QuestionTemplate 数据模型与题目模板管理

**用户故事：** 作为系统开发者，我希望定义绑定到 TeachingUnit + KnowledgeNode 的可复用题目模板，以便题目与知识架构严格关联，支持多次组卷复用。

#### 验收标准

1. THE QuestionTemplate SHALL 包含以下必填字段：subject、teaching_unit_id（外键引用 TeachingUnit）、knowledge_node_id（外键引用 KnowledgeNode）、question_type（QuestionType 枚举）、difficulty（Difficulty 枚举）、stem（题干）、answer（标准答案）、explanation（解析）、template_version（整数版本号）、status（active / deprecated）
2. WHERE QuestionTemplate 的 question_type 为 SINGLE_CHOICE，THE QuestionTemplate SHALL 包含非空的 options 字段（JSON 数组，至少 2 个选项）
3. THE QuestionTemplate SHALL 通过 teaching_unit_id 外键引用 TeachingUnit 表，通过 knowledge_node_id 外键引用 KnowledgeNode 表
4. WHEN 创建 QuestionTemplate 时引用的 TeachingUnit 或 KnowledgeNode 不存在，THE Assessment_Layer SHALL 拒绝创建并返回引用完整性错误
5. THE QuestionTemplate SHALL 包含 subject + teaching_unit_id + stem_hash 的唯一约束，防止同一教学单元下出现重复题干
6. WHEN QuestionTemplate 的 status 为 deprecated，THE Paper_Assembler SHALL 在组卷时排除该模板

### 需求 2：ExamPaper 与 ExamPaperItem 数据模型

**用户故事：** 作为系统开发者，我希望定义试卷实体与试卷题目条目，以便组卷结果可持久化且题目内容不可变。

#### 验收标准

1. THE ExamPaper SHALL 包含以下必填字段：subject、user_id、exam_mode（ExamMode 枚举：diagnostic / practice / weakpoint_boost / review / mock_final）、curriculum_snapshot_id（外键引用 CurriculumSnapshot，记录组卷时的课程结构版本）、status（draft / ready / in_progress / submitted / grading / graded / archived，其中 grading 为异步判卷中间态）、created_at
2. THE ExamPaperItem SHALL 包含以下必填字段：exam_paper_id（外键引用 ExamPaper）、question_template_id（外键引用 QuestionTemplate）、item_order（题目序号）、snapshot_stem（题干快照）、snapshot_options（选项快照，可为空）、snapshot_answer（标准答案快照）、snapshot_explanation（解析快照）
3. WHEN 创建 ExamPaperItem 时，THE Assessment_Layer SHALL 从 QuestionTemplate 复制当前内容到 snapshot 字段，确保试卷内容在模板更新后保持不变
4. THE ExamPaperItem SHALL 在 exam_paper_id + item_order 上具有唯一约束
5. WHEN ExamPaper 的 status 为 submitted、grading 或 graded，THE Assessment_Layer SHALL 拒绝对该 ExamPaper 关联的 ExamPaperItem 进行修改

### 需求 3：UserAnswerAttempt 数据模型

**用户故事：** 作为系统开发者，我希望记录用户每道题的详细作答信息，以便支持精细化的掌握度分析。

#### 验收标准

1. THE UserAnswerAttempt SHALL 包含以下必填字段：exam_paper_item_id（外键引用 ExamPaperItem）、user_id、user_answer（用户答案文本）、is_correct（布尔值，判卷后填充）、time_spent_seconds（作答用时，整数，单位秒，允许为空）、hint_used（布尔值，默认 false）、confidence_self_report（整数 1-5，允许为空）、error_cause_label（ErrorCauseLabel 枚举，允许为空，判卷后填充）、created_at
2. THE UserAnswerAttempt SHALL 在 exam_paper_item_id + user_id 上具有唯一约束，确保每个用户对每道题只有一条作答记录
3. WHEN time_spent_seconds 字段有值时，THE UserAnswerAttempt SHALL 确保该值为非负整数
4. WHEN confidence_self_report 字段有值时，THE UserAnswerAttempt SHALL 确保该值在 1 到 5 的闭区间内

### 需求 4：UserKnowledgeState 数据模型与双粒度掌握度追踪

**用户故事：** 作为学习者，我希望系统以 TeachingUnit 和 KnowledgeNode 双粒度追踪我的掌握状态，以便精确定位薄弱环节。

#### 验收标准

1. THE UserKnowledgeState SHALL 包含以下必填字段：user_id、subject、granularity（unit / node 枚举）、target_id（引用 TeachingUnit.id 或 KnowledgeNode.id，取决于 granularity）、mastery_score（浮点数 0.0-1.0）、confidence_score（浮点数 0.0-1.0，表示掌握度估计的置信度）、stability_score（浮点数 0.0-1.0，表示记忆稳定性）、forgetting_due_at（datetime，预计遗忘时间点）、review_priority（浮点数，复习优先级）、total_attempts（总作答次数）、correct_attempts（正确次数）、last_attempt_at（最近作答时间）、updated_at
2. THE UserKnowledgeState SHALL 在 user_id + subject + granularity + target_id 上具有唯一约束
3. WHEN mastery_score 更新时，THE Profile_Engine SHALL 确保 mastery_score 值在 0.0 到 1.0 的闭区间内
4. WHEN confidence_score 更新时，THE Profile_Engine SHALL 确保 confidence_score 值在 0.0 到 1.0 的闭区间内
5. WHEN stability_score 更新时，THE Profile_Engine SHALL 确保 stability_score 值在 0.0 到 1.0 的闭区间内
6. THE UserKnowledgeState SHALL 确保 correct_attempts 小于等于 total_attempts

### 需求 5：ReviewTask 数据模型与复习队列

**用户故事：** 作为学习者，我希望系统根据遗忘风险和知识单元自动生成复习任务队列，以便高效安排复习。

#### 验收标准

1. THE ReviewTask SHALL 包含以下必填字段：user_id、subject、task_type（review_unit / review_node / review_exam / prereq_patch 枚举）、target_id（引用 TeachingUnit.id 或 KnowledgeNode.id，取决于 task_type）、priority（浮点数，越高越优先）、scheduled_at（计划复习时间）、status（pending / completed / skipped / expired）、interval_days（当前复习间隔天数）、ease_factor（SM-2 易度因子，浮点数，默认 2.5）、repetition_count（重复次数）、created_at、completed_at（完成时间，允许为空）
2. WHEN ReviewTask 的 status 从 pending 变为 completed，THE Assessment_Layer SHALL 记录 completed_at 时间戳
3. WHEN ReviewTask 的 scheduled_at 超过当前时间 7 天且 status 仍为 pending，THE Review_Scheduler SHALL 将该 ReviewTask 的 status 更新为 expired
4. THE ReviewTask SHALL 确保 ease_factor 大于等于 1.3（SM-2 算法下限）


### 需求 6：ExamMode 枚举与五种考试模式定义

**用户故事：** 作为学习者，我希望系统支持五种不同目的的考试模式，以便在不同学习阶段获得针对性的测评。

#### 验收标准

1. THE Assessment_Layer SHALL 支持以下五种 ExamMode：diagnostic（诊断测试，广覆盖初始评估）、practice（练习，当前主题的课后练习）、weakpoint_boost（薄弱强化，70% 薄弱单元 + 20% 先修补漏 + 10% 迁移拓展）、review（遗忘曲线复习，由 forgetting_due_at 驱动）、mock_final（模拟考试，按大纲比例模拟）
2. WHEN exam_mode 为 diagnostic，THE Paper_Assembler SHALL 从当前 CurriculumSnapshot 的全部 TeachingUnit 中均匀抽取题目，覆盖尽可能多的教学单元
3. WHEN exam_mode 为 practice，THE Paper_Assembler SHALL 仅从用户当前学习主题（ThemeTreeNode）关联的 TeachingUnit 中抽取题目
4. WHEN exam_mode 为 weakpoint_boost，THE Paper_Assembler SHALL 按 70% 薄弱单元、20% 先修依赖单元、10% 迁移拓展单元的比例组卷
5. WHEN exam_mode 为 review，THE Paper_Assembler SHALL 优先选取 UserKnowledgeState 中 forgetting_due_at 早于或等于当前时间的 TeachingUnit 关联的题目
6. WHEN exam_mode 为 mock_final，THE Paper_Assembler SHALL 按 ThemeTree 中各章节的 TeachingUnit 数量比例分配题目数量

### 需求 7：Examine_Engine — question_builder 题目生成

**用户故事：** 作为系统开发者，我希望按 TeachingUnit 增量生成题目模板库，以便为组卷提供充足的题目储备。

#### 验收标准

1. WHEN QuestionBuildJob 启动时，THE question_builder SHALL 接收目标 TeachingUnit 列表，为每个 TeachingUnit 生成指定数量的 QuestionTemplate
2. WHEN 生成 QuestionTemplate 时，THE question_builder SHALL 从 TeachingUnit 关联的 KnowledgeNode（通过 TeachingUnitMembership）获取知识内容，作为出题依据
3. THE question_builder SHALL 为每个 TeachingUnit 生成覆盖 SINGLE_CHOICE、FILL_BLANK、SHORT_ANSWER 三种题型的 QuestionTemplate
4. THE question_builder SHALL 为每个 TeachingUnit 生成覆盖 EASY、MEDIUM、HARD 三种难度的 QuestionTemplate
5. WHEN 生成的 QuestionTemplate 的 stem_hash 与同一 TeachingUnit 下已有模板重复时，THE question_builder SHALL 跳过该模板并记录日志
6. THE question_builder SHALL 在 QuestionTemplate 中正确设置 teaching_unit_id 和 knowledge_node_id，确保每个模板绑定到具体的教学单元和知识节点

### 需求 8：Examine_Engine — paper_assembler 组卷

**用户故事：** 作为学习者，我希望系统根据我的学习状态和考试模式自动组装个性化试卷，以便获得针对性的测评。

#### 验收标准

1. WHEN ExamGenerateJob 启动时，THE paper_assembler SHALL 接收 user_id、subject、exam_mode、num_questions 参数，生成一份 ExamPaper
2. THE paper_assembler SHALL 在组卷时引用当前 subject 最新的 published 状态的 CurriculumSnapshot，并将其 id 记录到 ExamPaper.curriculum_snapshot_id
3. WHEN 可用的 QuestionTemplate 数量不足以满足 num_questions 时，THE paper_assembler SHALL 使用全部可用模板组卷，并在 ExamPaper 中记录实际题目数量
4. THE paper_assembler SHALL 在组卷时对选中的 QuestionTemplate 进行内容快照，创建对应的 ExamPaperItem 记录
5. THE paper_assembler SHALL 确保同一 ExamPaper 中不包含重复的 QuestionTemplate（同一 question_template_id 只出现一次）
6. WHEN exam_mode 为 weakpoint_boost，THE paper_assembler SHALL 通过 Weakness_Analyzer 获取薄弱单元列表，并通过 PrereqDag 的 UnitDependency 获取先修依赖单元列表

### 需求 9：Examine_Engine — answer_grader 判卷与错因标注

**用户故事：** 作为学习者，我希望系统自动判卷并标注错因，以便了解错误的根本原因。

#### 验收标准

1. WHEN ExamGradeJob 启动时，THE answer_grader SHALL 接收 ExamPaper.id，对该试卷的全部 UserAnswerAttempt 进行判分
2. WHEN question_type 为 SINGLE_CHOICE 或 FILL_BLANK，THE answer_grader SHALL 通过精确匹配（忽略大小写和首尾空白）判定 is_correct
3. WHEN question_type 为 SHORT_ANSWER，THE answer_grader SHALL 调用 LLM 进行语义判分，并返回 is_correct 布尔值
4. WHEN UserAnswerAttempt 的 is_correct 为 false，THE answer_grader SHALL 调用 LLM 生成错因分析，并将错因分类写入 error_cause_label 字段
5. THE answer_grader SHALL 在判卷完成后将 ExamPaper 的 status 更新为 graded
6. IF answer_grader 在判卷过程中遇到 LLM 调用失败，THEN THE answer_grader SHALL 对该题使用精确匹配作为降级策略，并记录警告日志


### 需求 10：Profile_Engine — 掌握度更新

**用户故事：** 作为学习者，我希望系统在每次判卷后自动更新我的知识掌握状态，以便实时反映我的学习进度。

#### 验收标准

1. WHEN MasteryUpdateJob 启动时，THE Profile_Engine SHALL 接收已判卷的 ExamPaper.id，根据该试卷的全部 UserAnswerAttempt 更新对应的 UserKnowledgeState 记录
2. WHEN 更新 UserKnowledgeState 时，THE Profile_Engine SHALL 同时更新 unit 粒度（TeachingUnit）和 node 粒度（KnowledgeNode）的掌握状态
3. THE Profile_Engine SHALL 使用加权统计方法计算 mastery_score：mastery_score = correct_attempts / total_attempts，其中近期作答的权重高于早期作答
4. WHEN UserKnowledgeState 记录不存在时，THE Profile_Engine SHALL 创建新记录，初始 mastery_score 基于首次作答结果计算
5. THE Profile_Engine SHALL 在更新 mastery_score 后同步更新 confidence_score（基于作答次数，次数越多置信度越高）和 stability_score（基于连续正确次数）
6. THE Profile_Engine SHALL 在掌握度更新完成后触发 Review_Scheduler 重新计算受影响的 ReviewTask

### 需求 11：Weakness_Analyzer — 薄弱分析

**用户故事：** 作为学习者，我希望系统综合多维度信息诊断我的薄弱环节，以便精准定位需要加强的知识点。

#### 验收标准

1. WHEN Weakness_Analyzer 被调用时，THE Weakness_Analyzer SHALL 接收 user_id 和 subject，返回按优先级排序的薄弱 TeachingUnit 列表
2. THE Weakness_Analyzer SHALL 综合以下五个维度计算薄弱优先级：mastery_score（掌握度越低优先级越高）、近期错误频率（错误越多优先级越高）、先修缺口（通过 PrereqDag 的 UnitDependency 检测未掌握的先修单元）、遗忘风险（forgetting_due_at 越近优先级越高）、考试权重（在 ThemeTree 中占比越大优先级越高）
3. WHEN 检测到某 TeachingUnit 的先修单元（通过 UnitDependency 的 source_unit_id）的 mastery_score 低于 0.6 时，THE Weakness_Analyzer SHALL 将该先修单元标记为先修缺口并提升其优先级
4. THE Weakness_Analyzer SHALL 返回的薄弱列表中包含每个 TeachingUnit 的薄弱原因标签（低掌握度 / 高错误率 / 先修缺口 / 遗忘风险）

### 需求 12：Review_Scheduler — 间隔重复复习调度

**用户故事：** 作为学习者，我希望系统基于 SM-2 算法自动安排复习计划，以便在最佳时机复习即将遗忘的知识。

#### 验收标准

1. WHEN MasteryUpdateJob 完成掌握度更新后，THE Review_Scheduler SHALL 为 mastery_score 低于 0.8 的 UserKnowledgeState 生成或更新 ReviewTask
2. THE Review_Scheduler SHALL 使用 SM-2 启发的间隔重复算法计算 ReviewTask 的 scheduled_at：首次复习间隔为 1 天，第二次为 6 天，后续间隔 = 前次间隔 × ease_factor
3. WHEN 用户完成 ReviewTask 对应的复习测试且正确率高于 0.8 时，THE Review_Scheduler SHALL 增加 ease_factor（最大不超过 2.5）并延长下次复习间隔
4. WHEN 用户完成 ReviewTask 对应的复习测试且正确率低于 0.6 时，THE Review_Scheduler SHALL 降低 ease_factor（最小不低于 1.3）并缩短下次复习间隔
5. THE Review_Scheduler SHALL 根据 UserKnowledgeState 的 stability_score 和 mastery_score 计算 forgetting_due_at，并更新到 UserKnowledgeState 记录
6. THE Review_Scheduler SHALL 确保同一 user_id + subject + target_id 组合在同一时间只有一个 pending 状态的 ReviewTask

### 需求 13：QuestionBuildJob — 题目构建异步任务

**用户故事：** 作为系统开发者，我希望按 TeachingUnit 增量构建题目模板库，以便在不阻塞用户操作的情况下持续扩充题库。

#### 验收标准

1. WHEN QuestionBuildJob 创建时，THE QuestionBuildJob SHALL 包含以下字段：subject、target_unit_ids（目标 TeachingUnit ID 列表，JSON 数组）、questions_per_unit（每个单元生成的题目数量）、status（pending / processing / completed / failed）、progress（0-100 整数）、created_at、updated_at
2. WHEN QuestionBuildJob 执行时，THE QuestionBuildJob SHALL 逐个处理 target_unit_ids 中的 TeachingUnit，调用 question_builder 生成 QuestionTemplate，并在每个单元完成后更新 progress
3. IF QuestionBuildJob 在处理某个 TeachingUnit 时遇到 LLM 调用失败，THEN THE QuestionBuildJob SHALL 记录错误日志并跳过该单元，继续处理剩余单元
4. WHEN QuestionBuildJob 的全部 TeachingUnit 处理完成后，THE QuestionBuildJob SHALL 将 status 更新为 completed 并记录生成的 QuestionTemplate 总数

### 需求 14：ExamGenerateJob — 组卷异步任务

**用户故事：** 作为学习者，我希望系统异步生成个性化试卷，以便在后台完成组卷后通知我开始答题。

#### 验收标准

1. WHEN ExamGenerateJob 创建时，THE ExamGenerateJob SHALL 包含以下字段：subject、user_id、exam_mode（ExamMode 枚举）、num_questions、status（pending / processing / completed / failed）、exam_paper_id（组卷完成后填充）、created_at、updated_at
2. WHEN ExamGenerateJob 执行时，THE ExamGenerateJob SHALL 调用 paper_assembler 生成 ExamPaper，并将生成的 ExamPaper.id 写入 exam_paper_id 字段
3. IF ExamGenerateJob 执行时当前 subject 没有 published 状态的 CurriculumSnapshot，THEN THE ExamGenerateJob SHALL 将 status 设为 failed 并记录错误信息
4. WHEN ExamGenerateJob 完成后，THE ExamGenerateJob SHALL 将 status 更新为 completed

### 需求 15：ExamGradeJob — 判卷异步任务

**用户故事：** 作为学习者，我希望系统异步完成判卷和错因分析，以便在后台处理完成后查看详细结果。

#### 验收标准

1. WHEN ExamGradeJob 创建时，THE ExamGradeJob SHALL 包含以下字段：exam_paper_id（外键引用 ExamPaper）、status（pending / processing / completed / failed）、score（判卷完成后填充的总分）、created_at、updated_at
2. WHEN ExamGradeJob 执行时，THE ExamGradeJob SHALL 调用 answer_grader 对 ExamPaper 的全部 UserAnswerAttempt 进行判分和错因标注
3. WHEN ExamGradeJob 判卷完成后，THE ExamGradeJob SHALL 计算总分（score = 正确题数 / 总题数 × 100）并写入 score 字段
4. WHEN ExamGradeJob 完成后，THE ExamGradeJob SHALL 自动触发 MasteryUpdateJob 以更新用户掌握度

### 需求 16：MasteryUpdateJob — 掌握度更新异步任务

**用户故事：** 作为系统开发者，我希望判卷完成后自动触发掌握度更新和复习任务生成，以便形成完整的测评-反馈闭环。

#### 验收标准

1. WHEN MasteryUpdateJob 创建时，THE MasteryUpdateJob SHALL 包含以下字段：exam_paper_id（外键引用 ExamPaper）、exam_grade_job_id（外键引用 ExamGradeJob）、status（pending / processing / completed / failed）、states_updated（更新的 UserKnowledgeState 数量）、tasks_created（生成的 ReviewTask 数量）、created_at、updated_at
2. WHEN MasteryUpdateJob 执行时，THE MasteryUpdateJob SHALL 调用 Profile_Engine 更新 UserKnowledgeState，然后调用 Review_Scheduler 生成或更新 ReviewTask
3. WHEN MasteryUpdateJob 完成后，THE MasteryUpdateJob SHALL 将 states_updated 和 tasks_created 写入对应字段，并将 status 更新为 completed
4. IF MasteryUpdateJob 执行过程中遇到错误，THEN THE MasteryUpdateJob SHALL 将 status 设为 failed 并记录错误信息到 error_message 字段


### 需求 17：两阶段题目生成策略

**用户故事：** 作为系统开发者，我希望题目生成分为模板构建（Phase A）和轻量变体（Phase B）两个阶段，以便在保证题目质量的同时提高组卷效率。

#### 验收标准

1. WHEN QuestionBuildJob 执行 Phase A 时，THE question_builder SHALL 为每个 TeachingUnit 生成完整的 QuestionTemplate（包含题干、选项、标准答案、解析），作为题目模板库的基础储备
2. WHEN paper_assembler 执行 Phase B 组卷时，THE paper_assembler SHALL 对选中的 QuestionTemplate 进行轻量变体处理（如数值替换、选项顺序打乱），生成 ExamPaperItem 的快照内容
3. WHEN Phase B 对 SINGLE_CHOICE 类型题目进行变体处理时，THE paper_assembler SHALL 随机打乱选项顺序，并同步更新 snapshot_answer 以匹配新的选项顺序
4. THE paper_assembler SHALL 确保 Phase B 变体处理后的 ExamPaperItem 快照内容与原始 QuestionTemplate 在语义上等价（正确答案对应的知识点和解题逻辑不变）

### 需求 18：测评层与现有三层架构的集成约束

**用户故事：** 作为系统开发者，我希望测评层严格依赖现有三层架构，以便保证数据一致性和架构完整性。

#### 验收标准

1. THE Assessment_Layer SHALL 通过 TeachingUnitMembership 获取 TeachingUnit 与 KnowledgeNode 的关联关系，作为题目生成和掌握度追踪的基础
2. THE Assessment_Layer SHALL 通过 ThemeTree（ThemeTreeVersion + ThemeTreeNode + UnitTreeMembership）获取主题层级结构，用于 practice 和 mock_final 模式的组卷
3. THE Assessment_Layer SHALL 通过 PrereqDag（PrereqDagVersion + UnitDependency）获取教学单元间的先修依赖关系，用于 weakpoint_boost 模式的先修补漏和 Weakness_Analyzer 的先修缺口检测
4. THE Assessment_Layer SHALL 在组卷时引用 CurriculumSnapshot 以确保试卷生成基于一致的课程结构版本
5. WHEN CurriculumSnapshot 更新（新版本发布）时，THE Assessment_Layer SHALL 继续使用已生成 ExamPaper 中记录的 curriculum_snapshot_id 对应的旧版本数据，确保已有试卷的稳定性
6. THE Assessment_Layer SHALL 仅通过 services 层编排 Examine_Engine 和 Profile_Engine，Examine_Engine 和 Profile_Engine 之间不直接互相调用

### 需求 19：API 接口层

**用户故事：** 作为前端开发者，我希望通过 RESTful API 访问测评层的全部功能，以便在前端实现完整的测评交互流程。

#### 验收标准

1. THE Assessment_Layer SHALL 提供以下 API 端点，全部使用 /api/v1 前缀：POST /{subject}/exam/generate（触发组卷）、POST /{subject}/exam/{exam_paper_id}/submit（提交答卷）、POST /{subject}/exam/{exam_paper_id}/grade（触发判卷，支持 regrade 参数）、GET /{subject}/exam/{exam_paper_id}（获取试卷详情）、GET /{subject}/exam/history（分页获取试卷历史）、GET /{subject}/exam/generate-jobs/{job_id}（查询组卷任务状态）、GET /{subject}/exam/grade-jobs/{job_id}（查询判卷任务状态）、GET /{subject}/question-build-jobs/{job_id}（查询题目构建任务状态）、GET /{subject}/mastery（获取用户掌握度概览）、GET /{subject}/mastery/unit/{target_id}（获取单个 TeachingUnit 掌握度详情）、GET /{subject}/mastery/node/{target_id}（获取单个 KnowledgeNode 掌握度详情）、GET /{subject}/review/tasks（获取待复习任务列表）、POST /{subject}/review/tasks/{task_id}/complete（标记复习任务完成）
2. THE Assessment_Layer 的 API 层 SHALL 仅负责参数校验和响应格式化，全部业务逻辑通过 services 层调用
3. WHEN API 请求中的 subject 对应的数据库不存在时，THE Assessment_Layer SHALL 返回 HTTP 404 错误
4. THE Assessment_Layer 的 API 响应 SHALL 使用统一的 JSON 格式，包含 code、message、data 字段

### 需求 20：MVP 分阶段实施约束

**用户故事：** 作为项目管理者，我希望测评层按三个阶段渐进实施，以便在每个阶段交付可用的功能闭环。

#### 验收标准

1. WHILE 处于 Phase 1（闭环阶段），THE Assessment_Layer SHALL 实现以下功能：基于 TeachingUnit 的 QuestionTemplate 生成、SINGLE_CHOICE / FILL_BLANK / SHORT_ANSWER 三种题型支持、diagnostic / practice / weakpoint_boost 三种考试模式的组卷、自动判卷、TeachingUnit 粒度的 mastery_score 更新、基于简单间隔重复的 ReviewTask 生成
2. WHILE 处于 Phase 2（下钻阶段），THE Assessment_Layer SHALL 在 Phase 1 基础上新增：KnowledgeNode 粒度的掌握度追踪、error_cause_label 错因标注、基于 PrereqDag 的先修缺口分析、完整的复习队列管理、掌握度历史趋势记录
3. WHILE 处于 Phase 3（预测模型阶段），THE Assessment_Layer SHALL 在 Phase 2 基础上新增：BKT/DKT 预测模型替代统计方法、遗忘风险预测、自适应难度调整
4. THE Assessment_Layer SHALL 确保每个阶段的数据模型向后兼容，Phase 2 和 Phase 3 新增的字段使用可空类型或默认值

### 需求 21：ErrorCauseLabel 枚举与错因分类体系

**用户故事：** 作为学习者，我希望系统对我的错误进行分类标注，以便了解错误的类型和根本原因。

#### 验收标准

1. THE Assessment_Layer SHALL 定义 ErrorCauseLabel 枚举，包含以下值：concept_confusion（概念混淆）、calculation_error（计算错误）、prerequisite_gap（先修缺失）、careless_mistake（粗心失误）、incomplete_understanding（理解不完整）、method_misapplication（方法误用）、unknown（未知原因）
2. WHEN answer_grader 为错误答案标注 error_cause_label 时，THE answer_grader SHALL 基于题目的 knowledge_node_id 关联的知识内容和用户答案进行 LLM 分析，选择最匹配的 ErrorCauseLabel 值
3. WHEN error_cause_label 为 prerequisite_gap 时，THE Weakness_Analyzer SHALL 通过 PrereqDag 查找该 TeachingUnit 的先修单元，并将先修单元加入薄弱分析结果

### 需求 22：掌握度计算的不变量约束

**用户故事：** 作为系统开发者，我希望掌握度计算满足数学不变量，以便保证数据的一致性和正确性。

#### 验收标准

1. FOR ALL UserKnowledgeState 记录，THE Profile_Engine SHALL 确保 0.0 ≤ mastery_score ≤ 1.0
2. FOR ALL UserKnowledgeState 记录，THE Profile_Engine SHALL 确保 0.0 ≤ confidence_score ≤ 1.0
3. FOR ALL UserKnowledgeState 记录，THE Profile_Engine SHALL 确保 0.0 ≤ stability_score ≤ 1.0
4. FOR ALL UserKnowledgeState 记录，THE Profile_Engine SHALL 确保 correct_attempts ≤ total_attempts
5. FOR ALL UserKnowledgeState 记录，THE Profile_Engine SHALL 确保 total_attempts ≥ 0 且 correct_attempts ≥ 0
6. FOR ALL ReviewTask 记录，THE Review_Scheduler SHALL 确保 ease_factor ≥ 1.3
7. FOR ALL ReviewTask 记录，THE Review_Scheduler SHALL 确保 interval_days ≥ 1
8. FOR ALL ExamPaper 记录，THE Assessment_Layer SHALL 确保 ExamPaperItem 的数量等于该试卷的实际题目数

### 需求 23：SM-2 间隔重复算法的幂等性与收敛性

**用户故事：** 作为系统开发者，我希望复习调度算法满足幂等性和收敛性，以便保证调度结果的可预测性。

#### 验收标准

1. WHEN Review_Scheduler 对同一 ReviewTask 使用相同的输入参数（正确率、当前 ease_factor、当前 interval_days）重复计算时，THE Review_Scheduler SHALL 产生相同的输出（新 ease_factor、新 interval_days、新 scheduled_at），满足幂等性
2. WHEN 用户持续正确作答时，THE Review_Scheduler SHALL 确保 interval_days 单调递增（复习间隔逐渐延长）
3. WHEN 用户持续错误作答时，THE Review_Scheduler SHALL 确保 interval_days 不低于 1 天（最小复习间隔下限）
4. FOR ALL SM-2 计算结果，THE Review_Scheduler SHALL 确保 1.3 ≤ ease_factor ≤ 2.5

### 需求 24：试卷快照的不可变性保证

**用户故事：** 作为系统开发者，我希望已生成试卷的题目内容不受后续模板更新影响，以便保证历史试卷的可追溯性。

#### 验收标准

1. WHEN ExamPaperItem 创建后，THE Assessment_Layer SHALL 确保 snapshot_stem、snapshot_options、snapshot_answer、snapshot_explanation 字段不可被修改
2. WHEN QuestionTemplate 的内容更新（新版本）后，THE Assessment_Layer SHALL 确保已有 ExamPaperItem 的快照内容保持不变
3. FOR ALL ExamPaperItem 记录，THE Assessment_Layer SHALL 确保 snapshot_answer 字段非空（每道题必须有标准答案快照）

