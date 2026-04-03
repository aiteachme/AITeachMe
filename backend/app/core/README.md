# Core — 应用基础设施层

> `core/` 是纯基础设施层，**只包含应用启动和运行所需的最底层依赖**。
> 不包含任何业务逻辑或 AI 能力。AI 平台引擎已迁移至 [`infra/`](../infra/README.md)。

---

## 目录结构

```
core/
├── config.py          # 配置中心（Settings, get_settings）
├── database.py        # SQLite 数据库（sqlite-vec 支持）
├── exceptions.py      # 全局异常层级
├── logger.py          # structlog 结构化日志
└── runtime_paths.py   # 运行时数据路径
```

---

## 模块说明

### config.py — 配置中心

```python
from app.core.config import get_settings

settings = get_settings()
print(settings.data_dir)
print(settings.app_version)
```

基于 Pydantic `BaseSettings`，支持 `.env` 和环境变量覆盖。

### database.py — SQLite 数据库

```python
from app.core.database import init_db, managed_session, get_engine, is_vec_ready

# 启动时一次性调用
init_db()

# 业务代码中使用
async with managed_session() as session:
    ...
```

集成 `sqlite-vec` 向量检索扩展，通过 `is_vec_ready()` / `require_vec_ready()` 守卫。

### exceptions.py — 全局异常层级

```python
from app.core.exceptions import AITeachMeError, LLMCallError, FileParseError
```

所有自定义异常继承自 `AITeachMeError`，带有 `status_code` 和 `error_code` 属性，
在 `main.py` 中统一处理为 JSON 响应。

### logger.py — 结构化日志

```python
from app.core.logger import configure_logging
import structlog

configure_logging()          # 启动时调用一次
logger = structlog.get_logger()
logger.info("event_name", key="value")
```

### runtime_paths.py — 运行时数据路径

```python
from app.core.runtime_paths import get_runtime_data_dir

data_dir = get_runtime_data_dir()  # → Path("backend/data")
```

---

## 依赖方向

```
api → services → workflows → infra → core
                                 ↓
                           repositories → models
```

- `infra/` 可以 import `core/`
- `core/` **绝不** import `infra/`
- `core/` **绝不** import `services/`、`workflows/` 等上层模块
