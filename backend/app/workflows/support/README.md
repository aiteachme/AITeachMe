# Support 工作流

最后更新：2026-06-15

`support/` 承接不属于五大 AI 引擎、但仍属于后端业务层的 API-facing 用例。

```text
api route
  -> workflows/support/<module>
  -> repositories / schemas / shared infra
```

## 目录

```text
support/
  auth/           # 访客、注册登录、token、验证码
  courses/        # 课程 CRUD、删除、图标、学习上下文
  export_import/  # .atmx 课程包导入导出、demo course
  system/         # 前端初始化、设置页、运行时信息
```

对应文档：

- [auth/README.md](auth/README.md)
- [courses/README.md](courses/README.md)
- [export_import/README.md](export_import/README.md)
- [system/README.md](system/README.md)

## 边界

Support 默认不是 LangGraph。

Support 不复制五大引擎能力；需要 AI 长链路时调用 `ingest/digest/interact/examine/profile` 的稳定入口。

Support 不放进 `api/`，也不下沉到 `shared.infra`；它是业务用例层。

## 当前模块

| 模块 | 输入 | 输出 |
| --- | --- | --- |
| `auth` | 登录注册、访客身份、验证码请求 | 用户身份、token、会话响应 |
| `courses` | 课程创建/更新/删除请求 | Course、删除预览、学习上下文 |
| `export_import` | `.atmx` 包、课程 ID、demo course 标识 | 导出包、导入课程、demo course 列表 |
| `system` | 当前运行环境和设置请求 | 前端初始化 payload、设置页数据 |

## 文件规则

```text
workflows/support/<module>/
  __init__.py
  README.md
  <use_case>.py
  lib/        # 仅放该模块内部共享实现
```

新增文件按用例命名，例如 `catalog.py`、`settings.py`、`deletion.py`。
