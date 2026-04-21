# Examine 模块说明

最后更新：2026-04-21

`examine/` 负责题目生成、试卷构建与判卷相关流程。

当前 canonical 结构：

```text
examine/
  __init__.py
  README.md
  question_build/
  exam_grade/
```

说明：

- `question_build/` 是题目与试卷构建链路，负责把知识单元转换成结构化题目草稿。
- `exam_grade/` 是判卷链路，负责按答案与评分规则生成结果。
- 模块根只保留稳定导入面，不承载业务实现。

上层稳定入口：

```python
from app.workflows.examine import (
    build_exam_grade_graph,
    build_question_build_graph,
    run_question_build_workflow,
)
```
