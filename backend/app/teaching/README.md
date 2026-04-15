# Teaching 兼容层说明

最后更新：2026-04-16

`app.teaching` 不再是后端长期正式架构层。当前它的角色只有一个：

> 为历史导入面提供兼容 facade，帮助仓库逐步迁移到新的 workflows 单层架构。

## 1. 当前定位

新的推荐依赖方向已经改为：

```text
api -> workflows -> repositories / shared.infra / models / schemas
```

因此：

- `teaching/` 不再承接新增正式能力
- 新代码不要再从 `workflows/` 直接 import `app.teaching.*`
- 这里只保留迁移期 shim、兼容 facade 和少量尚未彻底挪走的实现

## 2. Canonical 去向

| 当前兼容入口 | Canonical 位置 |
| --- | --- |
| `teaching.py` | `app.shared.infra.tools.teaching_registry` |
| `tools.py` | `app.workflows.support.teaching_tools` |
| `runtime_config.py` | `app.workflows.digest._shared.runtime_config` |
| `documents/*` | `app.workflows.digest._shared.pedagogy/*` |
| `checker.py` | `app.shared.infra.checker` |
| `memory/*` | `app.shared.infra.memory` |
| `skill_tools.py` | 兼容 shim，最终删除 |

## 3. 现在还能怎么用

历史代码仍然可以继续这样导入：

```python
from app.teaching import (
    list_teaching_functions,
    run_teaching_function,
    teaching_function,
)
```

但这已经不再代表 canonical 位置；它只是兼容门面。

## 4. 当前还值得关注的部分

- `context.py`
  仍是一个历史上下文组装器，但不是新的正式架构模板
- `checker.py`
  纯兼容 facade
- `memory/`
  纯兼容 facade

## 5. 一句话总结

`app.teaching` 现在是 legacy compatibility layer，不是新的架构落点。
