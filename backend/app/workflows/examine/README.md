# Examine 模块说明

最后更新：2026-04-15

`examine/` 负责组卷与判卷。

当前 canonical 结构：

```text
examine/
  __init__.py
  README.md
  question_build/
  exam_grade/
```

说明：

- `question_build/` 负责出题模板构建
- `exam_grade/` 负责阅卷与掌握度回写
- 根目录历史平铺文件暂时保留兼容
