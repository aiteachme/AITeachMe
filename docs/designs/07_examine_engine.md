# 07. Examine 引擎设计

## 1. 文档定位

Examine 负责把 Digest 已经沉淀出来的知识资产，转成可练、可测、可判、可回流的考试闭环。

当前实现已经不再是“孤立题库随机组卷”，而是围绕下面几类资产工作：

- Digest 产出的知识文档 `knowledge_markdowns/merged.md` 或 build 版本
- Curriculum 产出的 `teaching_unit`、membership、课程快照
- KG 里的 `knowledge_node` 与当前 revision 内容
- Profile 里的掌握度、薄弱点、近期错题、待复习状态
- 用户补充的样卷文件、风格提示、重点提示

本篇只描述 Examine 当前已经落地的实现和约束，不再保留旧版 `question_template -> assemble_paper -> grade` 的空壳设计。

---

## 2. 当前目标

Examine 当前承担四件事：

1. 基于知识文档、图谱锚点和用户画像，批量生成可复用题模板。
2. 按不同考试模式，从模板池中组装出一份试卷。
3. 接收用户作答并完成并行判题。
4. 把判题结果回流给 Profile，更新掌握度并安排复习任务。

它不是独立知识源，所有出题与判题都默认依赖 Digest 和 Profile 的现有产物。

---

## 3. 输入资产

### 3.1 来自 Digest 的输入

- 知识文档：优先读取已发布 `merged.md`，没有时回退到 build 中的 merged 文档。
- Teaching unit：读取 `teaching_unit` 的标题、摘要、正文、学习目标。
- Curriculum membership：把 unit 和知识节点的关联关系拿来构造知识锚点。
- KG revision：优先读取节点当前 revision 的 summary/body，没有 revision 才回退到节点主表字段。

### 3.2 来自 Profile 的输入

- `user_knowledge_state` 中的单元掌握度
- `user_knowledge_state` 中的节点掌握度与薄弱节点
- 最近错题摘要
- 到期复习状态、薄弱单元状态

### 3.3 来自用户的输入

`/api/v1/subjects/{subject}/exams/generate` 当前支持：

- `exam_mode`
- `num_questions`
- `user_prompt`
- `style_prompt`
- `focus_prompt`
- `sample_file_uids`
- `theme_tree_node_id`
- `teaching_unit_ids`

其中：

- `sample_file_uids` 指向当前学科下已上传的原始文件。
- 样卷文件只有在 ingest 已完成并且 `parsed_markdown` 可用时，才会真正参与风格画像。
- `style_prompt` 用来描述卷面风格、题型习惯、措辞风格。
- `focus_prompt` 用来描述考试重点、压轴方向、希望强化的能力点。

---

## 4. 核心流程

当前主链路如下：

1. `trigger_exam_generate()`
2. `build_exam_style_profile()`
3. `trigger_question_build()`
4. `assemble_paper()`
5. `submit_exam_answers()`
6. `trigger_exam_grade()`
7. `grade_paper()`
8. `update_mastery_from_exam()` + `schedule_reviews()`

补充说明：当前 Examine 仍是 `services + workflows` 混合编排。`backend/app/services/exams_service.py` 负责请求级入口、事务边界、锁和返回对象封装；`backend/app/workflows/examine/*` 负责题模板生成、组卷、判题等核心能力。

### 4.1 风格画像构建

文件：`backend/app/workflows/examine/context.py`

`build_exam_style_profile()` 会综合样卷 markdown、`style_prompt`、`focus_prompt`、`user_prompt` 产出 `ExamStyleProfile`：

- `title_hint`
- `format_hint`
- `section_titles`
- `preferred_question_types`
- `question_type_bias`
- `recommended_question_count`
- `notes`

当前策略：

- 会从样卷中检测标题风格、分节标题、题型偏好、估计题量。
- `real_exam` 默认强制带上正式试卷语气和 section-based 提示。
- 如果样卷文件还没完成 ingest，不会报错，但只会留下提示 notes，不会真正参与画像。

### 4.2 单元考试上下文构建

文件：`backend/app/workflows/examine/context.py`

`build_unit_exam_contexts()` 会为每个教学单元构造一份 `UnitExamContext`，主要包含：

- 单元标题、摘要、正文、学习目标
- 从知识文档中按单元名和节点名抽出来的 `doc_excerpt`
- 图谱锚点 `node_contexts`
- 单元掌握度 `unit_mastery_score`
- 薄弱节点名 `weak_node_names`
- 最近错题 `recent_mistakes`
- 风格画像 `style_profile`
- `user_prompt` 与 `focus_prompt`

这一步是当前 Examine 和 Digest/Profile 接得最深的位置，后续无论是出题还是判题，都依赖这份上下文而不是裸 prompt。

### 4.3 题模板生成

文件：

- `backend/app/workflows/examine/question_build_workflow.py`
- `backend/app/workflows/examine/question_builder.py`

题模板生成按教学单元并行执行。

当前实现特征：

- `build_question_templates()` 先批量构造所有 `UnitExamContext`。
- 每个 unit 用 LLM 生成一批题模板。
- 并发上限由 `_MAX_CONCURRENT_TEMPLATE_CALLS = 4` 控制。
- 每个 unit 的 LLM 失败时，会回退到确定性模板 `_build_deterministic_templates()`，避免整批出题直接归零。
- 所有新模板最后一次性 `flush + commit`，不再逐条提交。

题模板持久化时会额外写两份关键快照：

- `node_refs_json`：记录题目关联的知识节点及权重。
- `selection_hints_json`：记录考试模式、题型偏好、学习目标、style profile、focus prompt、preferred node 等信息。

这两份快照后面会被组卷页、题库页和判题链路继续消费。

### 4.4 组卷

文件：`backend/app/workflows/examine/paper_assembler.py`

`assemble_paper()` 负责按模式从模板池挑题并生成 `exam_paper` 与 `exam_paper_item`。

当前支持模式：

- `diagnostic`
- `practice`
- `weakpoint_boost`
- `review`
- `mock_final`
- `real_exam`

当前策略：

- `practice`：按指定单元或主题范围覆盖。
- `weakpoint_boost`：优先弱项，再补先修，再补迁移题。
- `review`：优先到期复习状态。
- `mock_final`：按 curriculum 分布比例覆盖。
- `real_exam`：沿用 curriculum 分配，但会额外生成 `section_plan` 和正式卷面标题。

组卷时会把上下文写入 `exam_paper.selection_context_json`，当前至少包括：

- `selection_reasons`
- `target_theme_tree_node_id`
- `weakness_state_ids`
- `review_task_ids`
- `excluded_template_ids`
- `sample_file_uids`
- `user_prompt`
- `focus_prompt`
- `style_profile`
- `resolved_teaching_unit_ids`
- `paper_title`
- `section_plan`

前端详情页和真实考试模式展示都直接消费这份 `selection_context`。

### 4.5 提交与判题

文件：

- `backend/app/services/exams_service.py`
- `backend/app/workflows/examine/answer_grader.py`

`submit_exam_answers()` 只负责写回答题内容并把试卷状态推进到 `submitted`。

`trigger_exam_grade()` 会：

1. 把试卷状态推进到 `grading`
2. 调用 `grade_paper()`
3. 非 regrade 情况下更新掌握度和复习任务

判题策略：

- 客观题走精确匹配。
- 简答题走 LLM 判题。
- 简答题错误原因再单独走一次并行 LLM 归因。
- 简答题判题时会先调用 `build_grading_knowledge_context()`，把单元摘要、节点锚点、知识文档片段一起送进评分 prompt。

也就是说，当前判题已经不只是“拿标准答案对字符串”，而是会回看 Digest 生成的知识上下文。

---

## 5. 与 Digest / Profile 的闭环关系

### 5.1 与 Digest 的关系

Examine 当前依赖 Digest 三层产物：

- 知识文档：决定题目表述与判题上下文
- Curriculum：决定按什么单元出题和组卷
- KG：决定题目绑定哪些知识节点、判题时参考哪些知识锚点

如果 Digest 没有发布 curriculum snapshot，`trigger_exam_generate()` 会直接拒绝生成试卷。

### 5.2 与 Profile 的关系

Examine 当前会消费并回写 Profile：

- 消费：弱项、掌握度、近期错题、到期复习任务
- 回写：试卷评分结果会更新掌握度，并生成新的 review task

因此 Examine 不是一次性功能，而是学习闭环的一部分。

---

## 6. API 契约

### 6.1 生成试卷

接口：`POST /api/v1/subjects/{subject}/exams/generate`

请求新增重点字段：

- `style_prompt`
- `focus_prompt`
- `sample_file_uids`

返回重点字段：

- `exam_paper_id`
- `teaching_unit_ids`
- `sample_file_uids`

### 6.2 查看试卷详情

接口：`POST /api/v1/subjects/{subject}/exams/{exam_paper_id}`

当前详情返回：

- `selection_context`
- `items[].node_links`
- `items[].correct_answer`，仅在 `graded` 后返回
- `items[].mastery` 不是单独字段，而是挂在 `node_links[].mastery_score`

### 6.3 题库视图

接口：`POST /api/v1/subjects/{subject}/exams/question-bank`

当前会额外返回：

- `knowledge_points`
- `style_summary`

其中：

- `knowledge_points` 来自 `question_template.node_refs_json` 解析后的节点名称。
- `style_summary` 来自 `selection_hints_json.style_profile` 的简要摘要。

---

## 7. 前端页面行为

文件：`frontend/src/pages/ExamsPage.tsx`

当前考试页已经支持：

- 切换六种考试模式
- 输入题量、风格提示、重点提示
- 上传样卷文件并把文件 UID 回传给后端
- 查看真实考试模式卷面
- 查看节点回链、掌握度、标准答案、风格摘要
- 打印 `real_exam` 样式卷面

`real_exam` 模式当前不是单独后端引擎，而是在同一套模板池和组卷器上，通过：

- 更正式的风格画像
- 更偏正式试卷的 section plan
- 前端专门的卷面渲染

来实现“更像真实考试”的体验。

---

## 8. 并行与性能策略

当前已落地的并行点：

- 题模板生成按 unit 并行
- 简答题判题并行
- 错因归因并行

当前已落地的降级策略：

- 单元级 LLM 出题失败时回退确定性模板
- 样卷文件没准备好时只降级风格画像，不阻塞生成
- 题模板不足时会在组卷阶段逐步放宽 recent exclusion / type filter

当前仍然保守的点：

- 出题并发上限固定为 4，还没有按模型配额或系统负载动态调节
- Profile 与 KG 查询仍存在一定 N+1 倾向，后续可以继续收敛
- `real_exam` 目前是“正式卷面风格 + curriculum 分配”的增强模式，还不是完整的教研级仿真命题系统

---

## 9. 数据落点

当前关键数据对象：

- `question_template`
- `exam_paper`
- `exam_paper_item`
- `user_knowledge_state`
- `subject.profile_json`

当前关键 JSON 快照：

- `question_template.node_refs_json`
- `question_template.selection_hints_json`
- `exam_paper.selection_context_json`

设计约束：

- 题目生成上下文要尽量固化到模板层，不要等组卷时再临时推断。
- 组卷选择原因要固化到试卷层，保证后续可以回溯“为什么选这道题”。
- 判题引用的知识上下文可以运行时动态生成，但必须可由 Digest 当前产物稳定重建。

---

## 10. 当前边界与下一步

当前已经落地：

- Examine 正式接入 Digest 文档、Curriculum、KG、Profile
- 支持样卷 + 风格提示 + 重点提示
- 支持 `real_exam`
- 支持并行出题与并行判题
- 支持题库页知识点与风格摘要展示

当前还没做的事：

- 真正的 A3 纸级试卷导出与分页排版引擎
- 样卷风格的更细粒度学习，例如分值结构、版头版尾、答题卡信息
- 按知识点覆盖率和难度曲线做更严格的命题约束
- Examine 自身的 timing/token 观测总表

后续如果继续增强，优先顺序建议是：

1. 把样卷解析从“弱规则风格画像”升级到“结构化考试蓝图”。
2. 让 `real_exam` 支持更真实的题量、分值和 section 配比约束。
3. 给 Examine 也补上和 Digest 同级别的 timing/token observability。
4. 继续收敛 context 构建中的 N+1 查询，尤其是 unit/node/profile 联查。
