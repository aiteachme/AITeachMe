# 📝 Examine Engine · 诊断引擎

> 智能出卷 → AI 判卷 → 错因归类 → 掌握度更新 → 复习调度，形成完整的考试闭环。

**本模块包含以下子工作流：**

1. [Examine Question Build Workflow](#examine-question-build)
2. [Examine Exam Grade Workflow](#examine-exam-grade)
3. [Examine Workflow](#examine-flow)

---

## Examine Question Build Workflow

> Question template build workflow driven by teaching-unit validation and template generation.

📊 **4** 个处理节点 · **7** 条边

```mermaid
flowchart TD
    __start__(["▶ START"])
    load_units["❶ Load Units"]
    generate_templates["❷ Generate Templates"]
    finalize_build(["❸ Finalize Build"])
    __end__(["⏹ END"])

    subgraph error_zone ["⚠ 错误处理"]
    direction TB
        fail_build["⚠ Fail Build"]
    end

    __start__ --> load_units
    generate_templates -. "✗ fail" .-> fail_build
    generate_templates -->|"✓"| finalize_build
    load_units -. "✗ fail" .-> fail_build
    load_units -->|"✓"| generate_templates
    fail_build --> __end__
    finalize_build --> __end__

    %% ── Styling ──
    classDef startCls fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#a7f3d0
    classDef endCls fill:#7f1d1d,stroke:#ef4444,stroke-width:2px,color:#fecaca
    classDef failCls fill:#4c0519,stroke:#f43f5e,stroke-width:2px,color:#fecdd3
    classDef termCls fill:#1e3a5f,stroke:#3b82f6,stroke-width:2px,color:#93c5fd
    classDef default fill:#1e293b,stroke:#475569,stroke-width:1px,color:#e2e8f0
    style error_zone fill:#1a0a0e,stroke:#f43f5e,stroke-width:1px,color:#fecdd3,stroke-dasharray:5
    class __start__ startCls
    class finalize_build termCls
    class fail_build failCls
    class __end__ endCls
    linkStyle 1,3 stroke:#f43f5e,stroke-dasharray:5
```

**节点参考：**

| 节点 | 角色 | 路由 |
|------|------|------|
| Load Units | 🔀 条件路由 | `fail` -> Fail Build / `continue` -> Generate Templates |
| Generate Templates | 🔀 条件路由 | `fail` -> Fail Build / `continue` -> Finalize Build |
| Finalize Build | ✅ 终结节点 | → END |
| Fail Build | ❌ 错误处理 | → END |

## Examine Exam Grade Workflow

> Exam grading workflow including grading, mastery update, and review scheduling.

📊 **5** 个处理节点 · **9** 条边

```mermaid
flowchart TD
    __start__(["▶ START"])
    grade_answers["❶ Grade Answers"]
    update_mastery["❷ Update Mastery"]
    schedule_reviews["❸ Schedule Reviews"]
    finalize_grade(["❹ Finalize Grade"])
    __end__(["⏹ END"])

    subgraph error_zone ["⚠ 错误处理"]
    direction TB
        fail_grade["⚠ Fail Grade"]
    end

    __start__ --> grade_answers
    grade_answers -. "✗ fail" .-> fail_grade
    grade_answers -->|"✓"| update_mastery
    schedule_reviews -. "✗ fail" .-> fail_grade
    schedule_reviews -->|"✓"| finalize_grade
    update_mastery -. "✗ fail" .-> fail_grade
    update_mastery -->|"✓"| schedule_reviews
    fail_grade --> __end__
    finalize_grade --> __end__

    %% ── Styling ──
    classDef startCls fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#a7f3d0
    classDef endCls fill:#7f1d1d,stroke:#ef4444,stroke-width:2px,color:#fecaca
    classDef failCls fill:#4c0519,stroke:#f43f5e,stroke-width:2px,color:#fecdd3
    classDef termCls fill:#1e3a5f,stroke:#3b82f6,stroke-width:2px,color:#93c5fd
    classDef default fill:#1e293b,stroke:#475569,stroke-width:1px,color:#e2e8f0
    style error_zone fill:#1a0a0e,stroke:#f43f5e,stroke-width:1px,color:#fecdd3,stroke-dasharray:5
    class __start__ startCls
    class finalize_grade termCls
    class fail_grade failCls
    class __end__ endCls
    linkStyle 1,3,5 stroke:#f43f5e,stroke-dasharray:5
```

**节点参考：**

| 节点 | 角色 | 路由 |
|------|------|------|
| Grade Answers | 🔀 条件路由 | `fail` -> Fail Grade / `continue` -> Update Mastery |
| Update Mastery | 🔀 条件路由 | `fail` -> Fail Grade / `continue` -> Schedule Reviews |
| Schedule Reviews | 🔀 条件路由 | `fail` -> Fail Grade / `continue` -> Finalize Grade |
| Finalize Grade | ✅ 终结节点 | → END |
| Fail Grade | ❌ 错误处理 | → END |

## Examine Workflow

> High-level examine workflow from question-template build to grading and review scheduling.

📊 **3** 个处理节点 · **4** 条边

```mermaid
flowchart TD
    __start__(["▶ START"])
    question_templates_ready["❶ Question Templates Ready"]
    exam_paper_ready["❷ Exam Paper Ready"]
    exam_graded["❸ Exam Graded"]
    __end__(["⏹ END"])

    __start__ --> question_templates_ready
    exam_paper_ready --> exam_graded
    question_templates_ready --> exam_paper_ready
    exam_graded --> __end__

    %% ── Styling ──
    classDef startCls fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#a7f3d0
    classDef endCls fill:#7f1d1d,stroke:#ef4444,stroke-width:2px,color:#fecaca
    classDef failCls fill:#4c0519,stroke:#f43f5e,stroke-width:2px,color:#fecdd3
    classDef termCls fill:#1e3a5f,stroke:#3b82f6,stroke-width:2px,color:#93c5fd
    classDef default fill:#1e293b,stroke:#475569,stroke-width:1px,color:#e2e8f0
    style error_zone fill:#1a0a0e,stroke:#f43f5e,stroke-width:1px,color:#fecdd3,stroke-dasharray:5
    class __start__ startCls
    class __end__ endCls
```

**节点参考：**

| 节点 | 角色 | 路由 |
|------|------|------|
| Question Templates Ready | ⚙ 处理节点 | → Exam Paper Ready |
| Exam Paper Ready | ⚙ 处理节点 | → Exam Graded |
| Exam Graded | ⚙ 处理节点 | → END |

---

## 🧬 核心 Prompt 指纹

> 本引擎共使用 **5** 个核心提示词模板。点击展开查看完整内容。

<details>
<summary><b>Exam Generate</b> (<code>exam_generate</code>)</summary>

```
You are building a structured exam blueprint for the subject: {{ subject }}.
Return JSON only.

Requirements:
- Generate {{ num_questions }} questions.
- Allowed question types: {{ question_types }}.
- Allowed difficulty values: {{ difficulties }}.
- The paper should align with the requested knowledge points, weak points, and recent mistakes.
- Every question must be answerable from the provided teaching context.
- Keep wording clear, exam-like, and specific.

Requested knowledge points:
{{ requested_knowledge_points }}

Available knowledge points:
{{ available_knowledge_points }}

Weak knowledge points:
{{ weak_knowledge_points }}

Recent mistakes:
{{ recent_mistake_stems }}
```

</details>

<details>
<summary><b>Exam Generate From Text</b> (<code>exam_generate_from_text</code>)</summary>

```
You are generating high-quality exam questions from curated teaching context.
Return JSON only in the shape {"questions": [...]}.

Requirements:
- Generate exactly {{ num_questions }} questions.
- Allowed question types: {{ question_types }}.
- Allowed difficulty values: {{ difficulties }}.
- Use only the provided knowledge packet.
- Questions must feel like a real teacher-made paper, not flash cards.
- Prefer clear stems, unambiguous answers, and concise explanations.
- If the style profile mentions a sample paper, follow that tone and section style when reasonable.
- Each question item must include:
  - question_type
  - difficulty
  - stem
  - options (only for single_choice)
  - answer
  - explanation
  - knowledge_unit_id (pick the best matching node when possible)

Knowledge packet:
{{ knowledge_packet }}
```

</details>

<details>
<summary><b>Short Answer Grade</b> (<code>short_answer_grade</code>)</summary>

```
Judge whether the user answer should receive full credit.
Return only `1` or `0`.

Rules:
- `1` means the answer is substantially correct.
- `0` means the answer misses a key idea, contains a wrong claim, or is too incomplete.
- Be strict but fair.
- Use the knowledge context if it is helpful.

Question:
{{ stem }}

Reference answer:
{{ answer }}

User answer:
{{ user_answer }}

Knowledge context:
{{ knowledge_context }}
```

</details>

<details>
<summary><b>Error Cause Label</b> (<code>error_cause_label</code>)</summary>

```
Pick the single best error cause label for the wrong answer.
Return only one of these labels:
concept_confusion
calculation_error
prerequisite_gap
careless_mistake
incomplete_understanding
method_misapplication
unknown

Question:
{{ stem }}

Reference answer:
{{ answer }}

User answer:
{{ user_answer }}

Knowledge context:
{{ knowledge_context }}
```

</details>

<details>
<summary><b>Mistake Analysis</b> (<code>mistake_analysis</code>)</summary>

```
Write a concise mistake analysis in under 120 Chinese characters.
Focus on why the answer is wrong and what to review next.

Question:
{{ stem }}

Reference answer:
{{ answer }}

User answer:
{{ user_answer }}

Knowledge point:
{{ knowledge_point }}
```

</details>
