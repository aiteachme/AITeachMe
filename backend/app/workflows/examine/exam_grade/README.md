# Exam Grade 链路说明

最后更新：2026-04-15

`exam_grade/` 是 examine 的判卷链路门面。

当前 canonical 文件：

- `graph.py`
- `state.py`
- `nodes/`
- `prompts/`
- `lib/`

迁移期说明：

- 历史实现仍有一部分在模块根 `exam_grade_workflow.py`
- 新的 LangGraph 入口和模块门面统一从 `exam_grade/` 暴露
