# Profile 模块说明

最后更新：2026-04-15

`profile/` 负责掌握度更新、复习计划和画像刷新。

当前 canonical 结构：

```text
profile/
  __init__.py
  README.md
  pipeline/
```

说明：

- `pipeline/` 是唯一真实链路
- 根目录旧 `graph.py / runtime.py / state.py` 保留兼容
