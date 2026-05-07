# Examine Exam Grade 链路说明

最后更新：2026-04-21

`examine/exam_grade/` 是 Examine 模块的判卷链路。

目录角色：

- `graph.py`：判卷图定义
- `__init__.py`：稳定导出面

当前口径：

- 该链路负责根据试卷、用户答案与评分规则生成判卷结果。
- 当前结构较轻，但仍作为独立 lane 保持边界清晰。
- LLM 调用的 `call_purpose`、模型槽位、`max_tokens` 和 metadata 统一由 `lib/model_policy.py` 维护。
