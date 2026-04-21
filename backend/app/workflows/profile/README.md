# Profile 模块说明

最后更新：2026-04-16

`profile/` 负责掌握度更新、复习计划和画像刷新。

当前 canonical 结构：

```text
profile/
  __init__.py
  README.md
  pipeline/
```

说明：

- `pipeline/` 是唯一真实链路，掌握度更新、复习调度、画像刷新与报告建议都已下沉到 `pipeline/`
- 模块根只保留稳定导入面与 README，不再保留 `application/`、`events.py`、`exports.py` 这类根层包装文件
