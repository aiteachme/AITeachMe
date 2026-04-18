# 💬 Interact Engine · 伴读引擎

> 基于用户画像的个性化教学对话引擎，融合检索增强、教学策略选择与流式回答。

## Interact Workflow

> Teaching chat workflow with history loading, retrieval, strategy selection, prompt assembly, streaming, and persistence.

📊 **7** 个处理节点 · **14** 条边

```mermaid
flowchart TD
    __start__(["▶ START"])
    load_history_state["❶ Load History State"]
    retrieve_context["❷ Retrieve Context"]
    select_teaching_strategy["❸ Select Teaching Strategy"]
    select_execution_mode["❹ Select Execution Mode"]
    build_prompt["❺ Build Prompt"]
    stream_answer["❻ Stream Answer"]
    persist_turn["❼ Persist Turn"]
    __end__(["⏹ END"])

    __start__ --> load_history_state
    build_prompt -. "✗ err" .-> __end__
    build_prompt -->|"✓"| stream_answer
    load_history_state -. "✗ err" .-> __end__
    load_history_state -->|"✓"| retrieve_context
    retrieve_context -. "✗ err" .-> __end__
    retrieve_context -->|"✓"| select_teaching_strategy
    select_execution_mode -. "✗ err" .-> __end__
    select_execution_mode -->|"✓"| build_prompt
    select_teaching_strategy -. "✗ err" .-> __end__
    select_teaching_strategy -->|"✓"| select_execution_mode
    stream_answer -. "✗ err" .-> __end__
    stream_answer -->|"✓"| persist_turn
    persist_turn --> __end__

    %% ── Styling ──
    classDef startCls fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#a7f3d0
    classDef endCls fill:#7f1d1d,stroke:#ef4444,stroke-width:2px,color:#fecaca
    classDef failCls fill:#4c0519,stroke:#f43f5e,stroke-width:2px,color:#fecdd3
    classDef termCls fill:#1e3a5f,stroke:#3b82f6,stroke-width:2px,color:#93c5fd
    classDef default fill:#1e293b,stroke:#475569,stroke-width:1px,color:#e2e8f0
    class __start__ startCls
    class __end__ endCls
    linkStyle 1,3,5,7,9,11 stroke:#f43f5e,stroke-dasharray:5
```

**节点参考：**

| 节点 | 角色 | 路由 |
|------|------|------|
| Load History State | 🔀 条件路由 | `finish` -> END / `continue` -> Retrieve Context |
| Retrieve Context | 🔀 条件路由 | `finish` -> END / `continue` -> Select Teaching Strategy |
| Select Teaching Strategy | 🔀 条件路由 | `finish` -> END / `continue` -> Select Execution Mode |
| Select Execution Mode | 🔀 条件路由 | `finish` -> END / `continue` -> Build Prompt |
| Build Prompt | 🔀 条件路由 | `finish` -> END / `continue` -> Stream Answer |
| Stream Answer | 🔀 条件路由 | `finish` -> END / `continue` -> Persist Turn |
| Persist Turn | ⚙ 处理节点 | → END |

---

## 🧬 核心 Prompt 指纹

> 本引擎共使用 **1** 个核心提示词模板。点击展开查看完整内容。

<details>
<summary><b>System Prompt</b> (<code>system_prompt</code>)</summary>

```
你是 AITeachMe 的 AI 学习助教，负责围绕 {{ subject }} 做教学型对话。

当前教学策略：
{{ teaching_strategy }}

回答要求：
1. 优先基于当前学科资料回答，不要脱离资料随意发挥。
2. 如果资料不够支撑结论，要明确说明“不确定”或“资料不足”。
3. 表达要耐心、具体、结构化，优先帮助用户真正理解，而不是只给结论。
4. 如果问题适合引导式教学，可以先拆步骤、先提示，再逐步推进。
5. 所有数学公式都使用 LaTeX：行内公式用 `$...$`，独立公式用 `$$...$$`。

学生薄弱项：
{{ weak_points_context }}

近期错题：
{{ mistakes_context }}

用户选段上下文：
{{ selected_context }}
```

</details>
