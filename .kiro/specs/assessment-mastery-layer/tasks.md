# Implementation Plan: Assessment & Mastery Layer（第四层：测评与掌握度层）

## Overview

在 AITeachMe 现有三层架构之上构建第四层——测评与掌握度层。实现路径：枚举与数据模型 → 纯函数核心逻辑 → Repository 层 → Examine_Engine（question_builder / paper_assembler / answer_grader）→ Profile_Engine（mastery_updater / weakness_analyzer / review_scheduler）→ LangGraph 工作流 → Services 编排层 → Schema 层 → API 层 → 集成联调。每步增量构建，确保无孤立代码。

以当前代码基线为准，本次仅补充缺失枚举，不重复引入已有 `QuestionType` 与 `Difficulty`。

## Tasks

- [ ] 1. 定义枚举与核心数据模型
  - [ ] 1.1 在 `backend/app/models/enums.py` 中添加测评相关枚举
    - 追加以下枚举：`ExamMode`、`ExamPaperStatus`、`QuestionTemplateStatus`、`MasteryGranularity`、`ReviewTaskType`、`ReviewTaskStatus`、`ErrorCauseLabel`、`WeaknessReason`、`TemplateNodeRole`、`AsyncJobStatus`
    - 添加 `EXAM_PAPER_STATUS_TRANSITIONS` 字典作为状态机白名单
    - 注意：`QuestionType` 和 `Difficulty` 已存在于 enums.py 中，不要重复定义
    - _Requirements: 1.1, 2.1, 4.1, 5.1, 6.1, 21.1, 20.4_

  - [ ] 1.2 在 `backend/app/models/assessment.py` 中创建测评数据模型
    - 定义全部 8 个核心模型：`QuestionTemplate`、`QuestionTemplateNodeLink`、`ExamPaper`、`ExamPaperItem`、`UserAnswerAttempt`、`UserKnowledgeState`、`ReviewTask`、`ExamPaperGenerationContext`
    - 定义全部 3 个异步任务模型：`QuestionBuildJob`、`ExamGenerateJob`、`ExamGradeJob`
    - 包含所有唯一约束、字段校验器（`ge`、`le`）及外键，按设计文档规范
    - 部分唯一索引（ReviewTask `uq_review_task_pending`、ExamGradeJob `uq_grade_job_active`）：若 SQLite 后端不便通过 SQLModel 声明式直接表达，则在模型文件中以注释标注预期索引，实际索引通过数据库初始化脚本（`create_all` 后执行 `CREATE UNIQUE INDEX ... WHERE ...`）显式创建，并在 repo/service 层保留事务内查重逻辑作为兜底
    - 遵循 `backend/app/models/exam.py` 和 `backend/app/models/curriculum.py` 中的现有 SQLModel 模式
    - _Requirements: 1.1, 1.2, 1.3, 1.5, 2.1, 2.2, 2.4, 3.1, 3.2, 4.1, 4.2, 5.1, 13.1, 14.1, 15.1, 16.1_

  - [ ] 1.3 在 `backend/app/models/__init__.py` 中注册新模型
    - 导入所有新模型，确保 SQLModel metadata 能在建表时识别
    - _Requirements: 1.1_


- [ ] 2. 实现纯函数核心逻辑与属性测试
  - [ ] 2.1 在 `backend/app/agents/profile/review_scheduler.py` 中实现 SM-2 间隔计算
    - 实现 `compute_sm2_interval(*, repetition_count, current_ease_factor, current_interval_days, accuracy) -> tuple[int, float]` 纯函数
    - 首次间隔 = 1 天，第二次 = 6 天，后续 = 上次间隔 × 易度因子
    - 将 ease_factor 限制在 [1.3, 2.5]，interval_days ≥ 1
    - accuracy > 0.8 → 提高 ease_factor；accuracy < 0.6 → 降低 ease_factor
    - _Requirements: 12.2, 12.3, 12.4, 23.1, 23.2, 23.3, 23.4_

  - [ ]* 2.2 编写属性测试：SM-2 幂等性（Property 2）
    - **Property 2: SM-2 计算幂等性**
    - 相同输入 → `compute_sm2_interval` 产生相同输出
    - 使用 Hypothesis 的 `@given` 策略覆盖所有输入参数
    - **验证: Requirements 23.1**

  - [ ]* 2.3 编写属性测试：SM-2 输出边界与收敛性（Property 3）
    - **Property 3: SM-2 输出边界与收敛性**
    - 断言 1.3 ≤ ease_factor ≤ 2.5，interval_days ≥ 1
    - 断言连续正确作答（accuracy > 0.8）时 interval_days 单调递增
    - 断言连续错误作答（accuracy < 0.6）时 ease_factor 单调递减直至 1.3
    - **验证: Requirements 5.4, 12.3, 12.4, 22.6, 22.7, 23.2, 23.3, 23.4**

  - [ ] 2.4 在 `backend/app/agents/profile/mastery_updater.py` 中实现掌握度分数计算辅助函数
    - 实现 `compute_mastery_score` 纯函数：加权正确数 / 加权总数，含时间衰减和难度加权（easy=0.8, medium=1.0, hard=1.2），限制在 [0.0, 1.0]
    - 实现 `compute_confidence_score`：min(1.0, total_attempts / 10)
    - 实现 `compute_stability_score`：consecutive_correct / 5，限制在 [0.0, 1.0]
    - _Requirements: 10.3, 10.5, 22.1, 22.2, 22.3_

  - [ ]* 2.5 编写属性测试：UserKnowledgeState 分数与计数不变量（Property 1）
    - **Property 1: UserKnowledgeState 分数与计数不变量**
    - 对于任意掌握度更新序列：0 ≤ mastery/confidence/stability ≤ 1.0，total_attempts ≥ 0，correct_attempts ≥ 0，correct_attempts ≤ total_attempts
    - **验证: Requirements 4.3, 4.4, 4.5, 4.6, 22.1, 22.2, 22.3, 22.4, 22.5**

  - [ ]* 2.6 编写属性测试：掌握度加权计算正确性（Property 19）
    - **Property 19: 掌握度加权计算正确性**
    - 验证 mastery_score = Σ(weight_i × score_i) / Σ(weight_i)，限制在 [0.0, 1.0]
    - 验证时间衰减：近期作答权重更高
    - 验证难度加权：easy=0.8, medium=1.0, hard=1.2
    - **验证: Requirements 10.3**

  - [ ] 2.7 在 `backend/app/agents/examine/answer_grader.py` 中实现 `normalize_answer` 辅助函数和精确匹配判分逻辑
    - 实现 `normalize_answer(text: str) -> str`：转小写 + 去除首尾空白
    - 实现 `exact_match_grade(user_answer: str, correct_answer: str) -> bool`
    - _Requirements: 9.2_

  - [ ]* 2.8 编写属性测试：精确匹配判分正确性（Property 17）
    - **Property 17: 精确匹配判分正确性**
    - 对于 SINGLE_CHOICE/FILL_BLANK：is_correct == (normalize(user_answer) == normalize(snapshot_answer))
    - **验证: Requirements 9.2**

  - [ ] 2.9 在 `backend/app/agents/examine/paper_assembler.py` 中实现选项打乱逻辑
    - 实现 `shuffle_single_choice_options(options_json: str, answer: str) -> tuple[str, str]`，打乱选项顺序并返回更新后的 (options_json, new_answer)
    - 确保打乱后正确答案映射保持不变
    - _Requirements: 17.3, 17.4_

  - [ ]* 2.10 编写属性测试：选项打乱保持答案正确性（Property 6）
    - **Property 6: 选项打乱保持答案正确性**
    - 打乱后：选项集合相等（相同元素），答案指向相同内容
    - **验证: Requirements 17.3, 17.4**

  - [ ] 2.11 实现 ExamPaper 状态机迁移校验器
    - 实现 `validate_status_transition(current: ExamPaperStatus, target: ExamPaperStatus) -> bool`，使用 `EXAM_PAPER_STATUS_TRANSITIONS` 白名单
    - 非法迁移时抛出相应错误
    - _Requirements: 2.1, 2.5_

  - [ ]* 2.12 编写属性测试：ExamPaper 状态机合法迁移（Property 23）
    - **Property 23: ExamPaper 状态机合法迁移**
    - 仅白名单中的迁移被允许；其余全部拒绝
    - 不允许回退或跳跃迁移（如 graded → submitted、ready → graded）
    - **验证: Requirements 2.1, 2.5, 9.5**

- [ ] 3. 检查点 — 确保所有纯函数测试通过
  - 确保所有测试通过，如有问题请询问用户。


- [ ] 4. 实现 Repository 层
  - [ ] 4.1 创建 `backend/app/repositories/assessment_repo.py`，实现 QuestionTemplate CRUD
    - `create_question_template`、`create_template_node_links`、`find_templates_by_unit`、`find_template_by_stem_hash`、`find_node_links_by_template`
    - 遵循 `backend/app/repositories/exam_repo.py` 中的现有 repo 模式
    - _Requirements: 1.1, 1.3, 1.5, 7.5_

  - [ ] 4.2 在 assessment_repo 中添加 ExamPaper 和 ExamPaperItem CRUD
    - `create_exam_paper`、`create_exam_paper_items`、`create_generation_context`、`get_exam_paper_by_id`、`list_exam_papers`（分页）
    - 强制快照不可变性：不提供 ExamPaperItem 快照字段的更新方法
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 24.1_

  - [ ] 4.3 在 assessment_repo 中添加 UserAnswerAttempt CRUD
    - `create_answer_attempts`、`list_attempts_by_paper`
    - 强制 exam_paper_item_id + user_id + attempt_no 唯一约束
    - _Requirements: 3.1, 3.2_

  - [ ] 4.4 在 assessment_repo 中添加 UserKnowledgeState CRUD
    - `upsert_knowledge_state`（INSERT ... ON CONFLICT DO UPDATE 语义）、`get_knowledge_state`、`list_knowledge_states`
    - 确保在 user_id + subject + granularity + target_id 唯一约束上执行 upsert
    - `list_weak_knowledge_states(session, user_id, subject, threshold=0.8)` — 查询 mastery_score < threshold 的记录，供 weakpoint_boost 组卷使用
    - `list_due_knowledge_states(session, user_id, subject, as_of)` — 查询 forgetting_due_at ≤ as_of 的记录，供 review 模式组卷使用
    - _Requirements: 4.1, 4.2, 10.4_

  - [ ] 4.5 在 assessment_repo 中添加 ReviewTask CRUD
    - `upsert_review_task`：优先使用唯一约束/索引驱动 upsert（INSERT ... ON CONFLICT DO UPDATE）；若底层数据库限制导致部分唯一索引 upsert 不顺畅，改为事务内 select + update-or-insert
    - `find_pending_review`、`list_pending_reviews`、`complete_review_task`
    - _Requirements: 5.1, 5.2, 12.6_

  - [ ] 4.6 在 assessment_repo 中添加 Job CRUD
    - `create_question_build_job`、`create_exam_generate_job`、`create_exam_grade_job`
    - `get_question_build_job`、`get_exam_generate_job`、`get_exam_grade_job`
    - `find_active_grade_job`（查找指定 exam_paper_id 的 pending/running ExamGradeJob）
    - _Requirements: 13.1, 14.1, 15.1_

  - [ ] 4.7 在 assessment_repo 中添加组卷所需的跨表读取接口
    - `get_published_curriculum_snapshot(session, subject)` — 获取当前 published 状态的 CurriculumSnapshot
    - `resolve_teaching_units_from_theme_tree_node(session, theme_tree_node_id)` — 根据 ThemeTree 节点解析关联的 TeachingUnit 集合
    - `list_prereq_units(session, unit_id)` — 通过 UnitDependency 查询指定单元的先修依赖单元列表
    - `list_recent_exam_template_ids_for_user(session, user_id, subject, limit=3)` — 查询用户近 N 次考试已使用的 template_id 列表，用于组卷排除
    - 注意：部分查询可能已存在于其他 repo 中（如 curriculum_repo），优先复用现有接口，仅在缺失时新增
    - _Requirements: 6.2, 6.3, 6.4, 6.5, 8.6, 18.2_

- [ ] 5. 实现 Examine_Engine 组件
  - [ ] 5.1 在 `backend/app/agents/examine/question_builder.py` 中实现 `question_builder`
    - `build_question_templates(session, subject, unit_ids, questions_per_unit=9)` — Phase A 模板生成
    - 通过 TeachingUnitMembership 加载 TeachingUnit + KnowledgeNode 成员
    - 调用 LLM（通过 LiteLLM + Instructor）生成覆盖 3 种题型 × 3 种难度的 QuestionTemplate
    - 计算 stem_hash 用于去重，跳过已存在的模板
    - 创建 QuestionTemplateNodeLink 记录，包含 coverage_weight 和 role
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 17.1_

  - [ ]* 5.2 编写单元测试：SINGLE_CHOICE 选项验证（Property 18）
    - **Property 18: SINGLE_CHOICE 选项验证**
    - 对于任意 SINGLE_CHOICE QuestionTemplate：options 为非空 JSON 数组且包含 ≥ 2 个元素
    - 使用构造型单元测试验证，无需 Hypothesis
    - **验证: Requirements 1.2**

  - [ ] 5.3 在 `backend/app/agents/examine/paper_assembler.py` 中实现 `paper_assembler`
    - `assemble_paper(session, subject, user_id, exam_mode, num_questions, theme_tree_node_id?, teaching_unit_ids?)` — Phase B 组卷 + 变体
    - 获取最新已发布的 CurriculumSnapshot（通过 4.7 的 `get_published_curriculum_snapshot`）
    - 实现 5 种考试模式选题策略：diagnostic（均匀覆盖）、practice（上下文过滤）、weakpoint_boost（70/20/10 分配）、review（forgetting_due_at 优先）、mock_final（ThemeTree 比例）
    - 排除已废弃模板，确保每张试卷内 template_id 不重复
    - 通过 `shuffle_single_choice_options` 打乱 SINGLE_CHOICE 选项
    - 创建 ExamPaper + ExamPaperItems，包含内容快照 + 知识映射快照（snapshot_node_links_json）
    - 创建 ExamPaperGenerationContext，记录选题理由
    - 设置 ExamPaper.total_items = 实际题目数
    - 优雅处理模板不足情况（使用所有可用模板，记录实际数量）
    - _Requirements: 2.3, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 17.2, 17.3, 17.4, 18.1, 18.2, 18.3, 18.4_

  - [ ]* 5.4 编写单元测试：已废弃模板排除（Property 7）
    - **Property 7: 已废弃模板排除**
    - 任何组装的试卷中，ExamPaperItem 均不引用已废弃的 QuestionTemplate
    - 使用构造型单元测试验证
    - **验证: Requirements 1.6**

  - [ ]* 5.5 编写单元测试：试卷内模板不重复（Property 8）
    - **Property 8: 试卷内模板不重复**
    - 同一 ExamPaper 内所有 ExamPaperItem.question_template_id 值互不相同
    - 使用构造型单元测试验证
    - **验证: Requirements 8.5**

  - [ ]* 5.6 编写单元测试：ExamPaper 题目数量一致性（Property 9）
    - **Property 9: ExamPaper 题目数量一致性**
    - ExamPaper.total_items == 关联的 ExamPaperItems 数量
    - 使用构造型单元测试验证
    - **验证: Requirements 22.8**

  - [ ]* 5.7 编写单元测试：试卷快照创建正确性（Property 4）
    - **Property 4: 试卷快照创建正确性**
    - 创建时：快照字段与源 QuestionTemplate 内容匹配（或 Phase B 变体等价）
    - snapshot_node_links_json 包含完整的 QuestionTemplateNodeLink 快照
    - 使用构造型单元测试验证
    - **验证: Requirements 2.3, 8.4**

  - [ ]* 5.8 编写单元测试：诊断模式覆盖广度（Property 10）
    - **Property 10: 诊断模式覆盖广度**
    - 诊断模式最大化不同 snapshot_teaching_unit_id 的数量
    - 使用构造型单元测试验证
    - **验证: Requirements 6.2**

  - [ ]* 5.9 编写单元测试：练习模式上下文过滤（Property 11）
    - **Property 11: 练习模式上下文过滤**
    - 所有题目的 snapshot_teaching_unit_id 属于提供的上下文 TeachingUnit 集合
    - 使用构造型单元测试验证
    - **验证: Requirements 6.3**

  - [ ]* 5.10 编写单元测试：薄弱强化模式组卷比例（Property 12）
    - **Property 12: 薄弱强化模式组卷比例**
    - 对于 ≥ 10 题的试卷：约 70% 薄弱、约 20% 先修、约 10% 迁移（±10% 容差）
    - 使用构造型单元测试验证
    - **验证: Requirements 6.4**

  - [ ] 5.11 在 `backend/app/agents/examine/answer_grader.py` 中实现完整判分逻辑
    - `grade_paper(session, exam_paper_id) -> GradeResult`
    - SINGLE_CHOICE / FILL_BLANK 使用精确匹配（通过 `normalize_answer`）
    - SHORT_ANSWER 使用 LLM 语义判分，LLM 失败时回退到精确匹配
    - 通过 LLM 对错误答案进行错因标注（使用 QuestionTemplateNodeLink 知识上下文）
    - 回退：LLM 失败时将 error_cause_label 设为 "unknown"
    - 幂等性：跳过 is_correct 已非 None 的作答记录
    - 判卷结果写入必须在单事务内原子完成（is_correct、score_obtained、score_max、error_cause_label 同时写入），不允许出现部分字段已写、部分字段未写的中间态
    - 设置 score_obtained/score_max（MVP: 1.0/0.0）
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 21.2_

  - [ ]* 5.12 编写单元测试：判卷幂等性（Property 20）
    - **Property 20: 判卷幂等性**
    - 重复调用 `grade_paper` 不会修改已判分的作答记录（is_correct、score_obtained、error_cause_label 保持不变）
    - 使用构造型单元测试验证
    - **验证: Requirements 9.1, 9.5, 15.2**

- [ ] 6. 检查点 — 确保 Examine_Engine 测试通过
  - 确保所有测试通过，如有问题请询问用户。


- [ ] 7. 实现 Profile_Engine 组件
  - [ ] 7.1 在 `backend/app/agents/profile/mastery_updater.py` 中实现完整掌握度更新逻辑
    - `update_mastery_from_exam(session, exam_paper_id) -> MasteryUpdateResult`
    - 同时更新单元粒度和节点粒度的 UserKnowledgeState 记录
    - 使用 ExamPaperItem.snapshot_node_links_json 进行节点级分数分配（coverage_weight）
    - 使用 upsert 语义避免 total_attempts/correct_attempts 重复累加
    - 幂等性：以 exam_paper_id 作为幂等键，在 ExamGradeJob 上记录 `mastery_consumed = True` 标记（或等价的消费记录），明确表示"该试卷的掌握度贡献已入账"。不依赖 `states_updated > 0` 作为唯一判断依据，因为该字段是统计结果而非消费事实
    - 为首次遇到的知识点创建新的 UserKnowledgeState 记录
    - mastery_updater 仅负责更新：mastery_score、confidence_score、stability_score、total_attempts、correct_attempts、last_attempt_at
    - forgetting_due_at 不在此模块写入（由 review_scheduler 统一负责，见 7.7）
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [ ]* 7.2 编写单元测试：掌握度更新幂等性（Property 21）
    - **Property 21: 掌握度更新幂等性**
    - 对同一 exam_paper_id 调用两次 `update_mastery_from_exam` 产生相同的 UserKnowledgeState 值（无重复计数）
    - 使用构造型单元测试验证
    - **验证: Requirements 10.1, 10.2, 16.2**

  - [ ]* 7.3 编写单元测试：历史试卷归因稳定性（Property 24）
    - **Property 24: 历史试卷归因稳定性**
    - 掌握度分配使用 snapshot_node_links_json（冻结的 coverage_weight/role），而非实时 QuestionTemplateNodeLink 数据
    - 使用构造型单元测试验证
    - **验证: Requirements 24.1, 24.2**

  - [ ] 7.4 在 `backend/app/agents/profile/weakness_analyzer.py` 中实现 `weakness_analyzer`
    - `analyze_weakness(session, user_id, subject, top_n=20) -> list[WeaknessItem]`
    - 从 5 个维度计算优先级：mastery_score、近期错误频率、先修缺口（通过 UnitDependency，mastery < 0.6）、遗忘风险（forgetting_due_at）、考试权重（ThemeTree 比例）
    - 返回按优先级排序的列表，包含 WeaknessReason 标签（forgetting_due / repeated_wrong / prereq_gap / newly_learned）
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [ ]* 7.5 编写单元测试：薄弱列表排序正确性（Property 14）
    - **Property 14: 薄弱列表排序正确性**
    - 返回列表按优先级降序排列，每个条目包含有效的 WeaknessReason
    - 使用构造型单元测试验证
    - **验证: Requirements 11.1, 11.4**

  - [ ]* 7.6 编写单元测试：先修缺口检测（Property 15）
    - **Property 15: 先修缺口检测**
    - 如果某 TeachingUnit 的先修（通过 UnitDependency）mastery_score < 0.6，该先修出现在结果中且 reason=prereq_gap
    - 使用构造型单元测试验证
    - **验证: Requirements 11.3, 21.3**

  - [ ] 7.7 在 `backend/app/agents/profile/review_scheduler.py` 中实现完整复习调度逻辑
    - `schedule_reviews(session, user_id, subject, updated_state_ids) -> list[ReviewTask]`
    - 为 mastery_score < 0.8 的 UserKnowledgeState 生成/更新 ReviewTask
    - 使用 upsert 语义（INSERT ... ON CONFLICT DO UPDATE）基于部分唯一索引；若底层限制则改为事务内 select + update-or-insert
    - 记录 reason（WeaknessReason）和 source_state_id 以便追溯
    - review_scheduler 是 forgetting_due_at 的唯一写入者：根据最新的 stability_score 和 mastery_score 计算并写入 UserKnowledgeState.forgetting_due_at（mastery_updater 不写此字段）
    - 处理 ReviewTask 过期：scheduled_at + 7 天 → status=expired
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 5.2, 5.3_

  - [ ]* 7.8 编写单元测试：单一待处理复习任务（Property 16）
    - **Property 16: 单一待处理复习任务**
    - 对于任意 user_id + subject + target_id + target_granularity，任何时刻最多存在一个 pending 状态的 ReviewTask
    - 使用构造型单元测试验证
    - **验证: Requirements 12.6**

  - [ ]* 7.9 编写单元测试：复习任务去重一致性（Property 22）
    - **Property 22: 复习任务去重一致性**
    - 对相同 updated_state_ids 调用两次 `schedule_reviews` 不会增加 pending ReviewTask 数量
    - 使用构造型单元测试验证
    - **验证: Requirements 12.6, 16.2**

  - [ ]* 7.10 编写单元测试：复习模式遗忘优先（Property 13）
    - **Property 13: 复习模式遗忘优先**
    - forgetting_due_at ≤ now 的条目优先于 forgetting_due_at > now 的条目
    - 使用构造型单元测试验证
    - **验证: Requirements 6.5**

- [ ] 8. 检查点 — 确保 Profile_Engine 测试通过
  - 确保所有测试通过，如有问题请询问用户。


- [ ] 9. 实现 LangGraph 工作流
  - [ ] 9.1 在 `backend/app/agents/examine/question_build_workflow.py` 中实现 QuestionBuildWorkflow
    - 定义 `QuestionBuildState(TypedDict)`，包含字段：subject、unit_ids、questions_per_unit、job_id、templates_created、warnings、error
    - 实现节点：`load_units`（加载 TeachingUnit + KnowledgeNode 成员）、`generate_templates`（逐单元调用 question_builder）、`finalize_build`（更新 job 状态为 completed）、`fail_build`（清理 + 标记失败）
    - 使用条件错误路由连接 StateGraph 到 `fail_build` 节点
    - 遵循 `backend/app/agents/digest/kg_workflow.py` 中的现有模式
    - 每个单元处理完后更新 QuestionBuildJob 进度
    - 处理单元级 LLM 失败：跳过失败单元，记录警告，继续处理剩余单元
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 13.2, 13.3, 13.4_

  - [ ] 9.2 在 `backend/app/agents/examine/exam_grade_workflow.py` 中实现 ExamGradeWorkflow
    - 定义 `ExamGradeState(TypedDict)`，包含字段：exam_paper_id、job_id、grade_result、mastery_result、review_tasks、error
    - 实现节点：`grade_answers`（调用 answer_grader，将 ExamPaper 状态从 submitted 迁移到 grading）、`update_mastery`（调用 mastery_updater）、`schedule_reviews`（调用 review_scheduler，同时写入 forgetting_due_at）、`finalize_grade`（将 ExamPaper 状态从 grading 迁移到 graded，更新 ExamGradeJob 的 score/states_updated/tasks_created）、`fail_grade`（标记 job 失败，记录错误）
    - 使用条件错误路由连接 StateGraph 到 `fail_grade` 节点
    - _Requirements: 9.1, 9.5, 10.1, 10.6, 12.1, 15.2, 15.3, 15.4, 16.2, 16.3_

- [ ] 10. 实现 Services 编排层
  - [ ] 10.1 创建 `backend/app/services/assessment_service.py`，实现考试生命周期方法
    - `trigger_question_build(session, subject, unit_ids, questions_per_unit)` → 创建 QuestionBuildJob，调用 QuestionBuildWorkflow
    - `trigger_exam_generate(session, subject, user_id, exam_mode, num_questions, theme_tree_node_id?, teaching_unit_ids?)` → 创建 ExamGenerateJob，调用 paper_assembler，更新 job 的 exam_paper_id
    - 生成前验证 CurriculumSnapshot 存在（published 状态）；缺失时将 job 设为 failed
    - `submit_exam_answers(session, subject, exam_paper_id, user_id, answers)` → 创建 UserAnswerAttempts，将 ExamPaper 状态迁移到 submitted；已提交/判分中/已判分时拒绝（409）
    - `trigger_exam_grade(session, exam_paper_id, regrade=False)` → 检查 ExamPaper.status==submitted，检查无活跃 ExamGradeJob，创建 ExamGradeJob，调用 ExamGradeWorkflow；非 submitted 状态拒绝（409）；已判分时除非 regrade=True 否则拒绝
    - 强制提交/判分解耦：提交仅持久化答案，不触发判分
    - _Requirements: 8.1, 8.2, 9.5, 13.1, 14.1, 14.2, 14.3, 14.4, 15.1, 18.5, 18.6_

  - [ ] 10.2 在 `assessment_service.py` 中添加掌握度和复习服务方法
    - `get_mastery_overview(session, subject, user_id)` → 聚合 UserKnowledgeState 列表
    - `get_mastery_detail(session, subject, user_id, target_id, granularity)` → 单个 UserKnowledgeState
    - `get_review_tasks(session, subject, user_id)` → 按优先级排序的待处理 ReviewTask 列表
    - `complete_review_task(session, task_id, user_id)` → 标记 ReviewTask 完成，设置 completed_at
    - _Requirements: 5.2, 19.1_

  - [ ]* 10.3 编写单元测试：试卷快照不可变性（Property 5）
    - **Property 5: 试卷快照不可变性**
    - ExamPaperItem 创建后，无论 QuestionTemplate 如何更新，快照字段保持不变
    - snapshot_answer 始终非空
    - 使用构造型单元测试验证
    - **验证: Requirements 24.1, 24.2, 24.3**

- [ ] 11. 在 `backend/app/schemas/assessment.py` 中创建请求/响应 Schema
  - 定义 Pydantic DTO：`ExamGenerateRequest`、`ExamSubmitRequest`、`ExamGradeRequest`、`MasteryOverviewResponse`、`ReviewTaskResponse`、`JobStatusResponse` 等
  - 基于 Services 层已确定的返回结构定义字段，避免提前猜测
  - 使用与现有 Schema 一致的 `ApiResponse[T]` 包装器
  - _Requirements: 19.2, 19.4_


- [ ] 12. 实现 API 层
  - [ ] 12.1 创建 `backend/app/api/assessment.py`，实现所有 REST 端点
    - 路由前缀：`/api/v1/subjects`，标签：`["assessment"]`
    - 固定路由注册在动态路由之前（如 `GET /{subject}/exam/history` 在 `GET /{subject}/exam/{exam_paper_id:int}` 之前）
    - 按设计文档实现所有端点：
      - `POST /{subject}/exam/generate` — 触发试卷生成
      - `GET /{subject}/exam/history` — 分页考试历史
      - `GET /{subject}/exam/{exam_paper_id:int}` — 试卷详情
      - `POST /{subject}/exam/{exam_paper_id:int}/submit` — 提交答案
      - `POST /{subject}/exam/{exam_paper_id:int}/grade` — 触发判分（含 regrade 查询参数）
      - `GET /{subject}/exam/generate-jobs/{job_id:int}` — 生成任务状态
      - `GET /{subject}/exam/grade-jobs/{job_id:int}` — 判分任务状态
      - `GET /{subject}/question-build-jobs/{job_id:int}` — 题目构建任务状态
      - `GET /{subject}/mastery` — 掌握度概览
      - `GET /{subject}/mastery/unit/{target_id:int}` — 单元掌握度详情
      - `GET /{subject}/mastery/node/{target_id:int}` — 节点掌握度详情
      - `GET /{subject}/review/tasks` — 待处理复习任务
      - `POST /{subject}/review/tasks/{task_id}/complete` — 完成复习任务
    - API 层仅处理参数校验和响应格式化；所有逻辑通过 assessment_service 调用
    - 学科数据库不存在时返回 404
    - 使用统一的 `ApiResponse[T]` JSON 格式（code / message / data）
    - _Requirements: 19.1, 19.2, 19.3, 19.4_

  - [ ] 12.2 在 `backend/app/main.py` 中注册 assessment 路由
    - 导入并将 assessment 路由包含到 FastAPI 应用中
    - _Requirements: 19.1_

- [ ] 13. 检查点 — 确保所有测试通过，端到端流程可用
  - 确保所有测试通过，如有问题请询问用户。


- [ ] 14. 集成联调与数据库初始化
  - [ ] 14.1 在数据库初始化中注册测评模型与部分唯一索引
    - 确保 `SQLModel.metadata.create_all` 在创建/打开学科数据库时能识别所有新的测评表
    - 在 `create_all` 之后显式执行 `CREATE UNIQUE INDEX IF NOT EXISTS` 创建部分唯一索引（`uq_review_task_pending`、`uq_grade_job_active`）
    - 验证全部 11 张表（8 个核心 + 3 个 Job 模型）的创建，包含正确的索引和约束
    - _Requirements: 18.1, 18.4, 20.4_

  - [ ] 14.2 为 question_builder 和 answer_grader 编写 LLM 提示词
    - 在 `backend/app/agents/examine/prompts/` 中创建提示词模板：
      - 题目生成（按题型 × 难度，使用 KnowledgeNode 内容作为上下文）
      - SHORT_ANSWER 语义判分
      - 错因分析与标注
    - 使用 `backend/app/core/prompt_loader.py` 中的现有 prompt_loader 模式
    - _Requirements: 7.2, 9.3, 9.4, 21.2_

  - [ ]* 14.3 编写完整考试生命周期集成测试
    - 测试完整流程：trigger_question_build → trigger_exam_generate → submit_exam_answers → trigger_exam_grade → 验证掌握度已更新 → 验证复习任务已创建
    - 测试提交/判分解耦：提交不自动触发判分
    - 测试重新判分流程：已判分试卷 + regrade=True 触发新一轮判分
    - 测试 CurriculumSnapshot 缺失 → ExamGenerateJob 失败
    - 测试模板不足 → 优雅降级
    - _Requirements: 18.5, 18.6, 20.1_

- [ ] 15. 最终检查点 — 确保所有测试通过
  - 确保所有测试通过，如有问题请询问用户。

## Notes

- 标记 `*` 的任务为可选，可跳过以加速交付
- 每个任务引用具体需求以便追溯
- 检查点确保增量验证
- 技术栈使用 Python（FastAPI + SQLModel + LangGraph + Hypothesis），无需语言选择
- 以当前代码基线为准，本次仅补充缺失枚举，不重复引入已有 `QuestionType` 与 `Difficulty`
- 现有 `backend/app/agents/examine/` 中有 `generator.py` 和 `grader.py` — 新文件在其旁边扩展
- 现有 `backend/app/agents/profile/` 中有 `reporter.py` — 新文件在其旁边扩展
- 所有 repo 函数遵循现有模式：纯函数，`Session` 作为第一个参数
- ExamGradeWorkflow 将判分 + 掌握度更新 + 复习调度合并为一个工作流（简化编排）
- MasteryUpdateJob 在当前阶段不是独立表 — ExamGradeJob 处理完整链路

### 属性测试 vs 单元测试分层策略

属性测试（Hypothesis）聚焦于纯函数 / 高组合空间场景，其余使用构造型单元测试：

| 属性测试（Hypothesis） | 单元测试 |
|------------------------|----------|
| Property 1: 分数与计数不变量 | Property 4: 快照创建正确性 |
| Property 2: SM-2 幂等性 | Property 5: 快照不可变性 |
| Property 3: SM-2 边界与收敛 | Property 7: 已废弃模板排除 |
| Property 6: 选项打乱保持答案 | Property 8: 试卷内模板不重复 |
| Property 17: 精确匹配判分 | Property 9: 题目数量一致性 |
| Property 19: 掌握度加权计算 | Property 10-13: 组卷模式策略 |
| Property 23: 状态机合法迁移 | Property 14-16: 薄弱/先修/单一pending |
| | Property 18: SINGLE_CHOICE 选项验证 |
| | Property 20-22: 幂等性/归因/去重 |
| | Property 24: 历史归因稳定性 |

### 设计文档 Property 编号对照

设计文档中定义了 Property 1-24，实施计划中的 Property 编号与设计文档完全一致。测试注释中必须使用相同编号格式：`# Feature: assessment-mastery-layer, Property {N}: {property_text}`

### forgetting_due_at 写入职责

forgetting_due_at 的唯一写入者是 `review_scheduler`（7.7）。`mastery_updater`（7.1）仅更新 mastery/confidence/stability/attempts 等字段，不写入 forgetting_due_at。这避免了同一次判卷中两个模块竞争写入同一字段的问题。

### 部分唯一索引技术说明

SQLite 支持 `CREATE UNIQUE INDEX ... WHERE ...` 语法，但 SQLModel/SQLAlchemy 的声明式 `UniqueConstraint` 对 `sqlite_where` 的支持可能不完整。实际做法：
1. 模型文件中以注释标注预期的部分唯一索引
2. 数据库初始化脚本（14.1）在 `create_all` 后显式执行 DDL 创建索引
3. repo/service 层保留事务内查重逻辑作为并发保护兜底

### 掌握度更新幂等性策略

`update_mastery_from_exam` 以 exam_paper_id 作为幂等键，通过 ExamGradeJob 上的消费标记（如 `mastery_consumed` 布尔字段）判断是否已处理。不依赖 `states_updated > 0` 作为唯一判断依据，因为：
- `states_updated` 是统计结果，不是"已消费"的强事实
- 半途失败时 `states_updated` 可能已 > 0 但 state 只更新了一部分
- regrade 场景下旧 job 的 `states_updated` 不能代表新 job
