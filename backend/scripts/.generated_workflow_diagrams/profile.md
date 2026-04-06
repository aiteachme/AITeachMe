# 📊 Profile Engine · 显影引擎

> 掌握度计算 → 遗忘曲线复习排期 → 弱势排行 → 学习报告生成，驱动用户能力雷达图。

## Profile Workflow

> High-level profile workflow from mastery updates to review scheduling, weakness ranking, and report suggestions.

📊 **4** 个处理节点 · **5** 条边

```mermaid
flowchart TD
    __start__(["▶ START"])
    mastery_updated["❶ Mastery Updated"]
    review_scheduled["❷ Review Scheduled"]
    weaknesses_ranked["❸ Weaknesses Ranked"]
    report_generated["❹ Report Generated"]
    __end__(["⏹ END"])

    __start__ --> mastery_updated
    mastery_updated --> review_scheduled
    review_scheduled --> weaknesses_ranked
    weaknesses_ranked --> report_generated
    report_generated --> __end__

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
| Mastery Updated | ⚙ 处理节点 | → Review Scheduled |
| Review Scheduled | ⚙ 处理节点 | → Weaknesses Ranked |
| Weaknesses Ranked | ⚙ 处理节点 | → Report Generated |
| Report Generated | ⚙ 处理节点 | → END |

---

## 🧬 核心 Prompt 指纹

> 本引擎共使用 **1** 个核心提示词模板。点击展开查看完整内容。

<details>
<summary><b>Report Suggestions</b> (<code>report_suggestions</code>)</summary>

```
请根据下面的学习情况，给出 3 到 5 条简洁、可执行的复习建议。
要求：
1. 每条建议一行
2. 不要编号
3. 不要空话，要能直接执行

学科：
{{ subject }}

整体掌握度：
{{ overall_mastery }}

薄弱知识点：
{{ weak_points }}
```

</details>
