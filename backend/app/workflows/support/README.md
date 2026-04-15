# Support 模块说明

最后更新：2026-04-16

`backend/app/workflows/support/` 是 workflows 单层化后的支撑业务区，承接原本不属于五大 AI 引擎、但仍属于后端业务层的模块。

## 目标

- 放置 `auth`、`files`、`subjects`、`system`、`export_import`、`teaching_tools` 这类非引擎业务模块
- 避免把这类逻辑重新塞回 `api/` 或 `shared.infra/`
- 与 `ingest / digest / interact / examine / profile` 保持平级，但不强制使用 LangGraph

## 默认模板

```text
workflows/support/<module>/
  __init__.py
  README.md
  commands.py
  queries.py
  streams.py      # 可选
  lib/            # 可选
```

## 当前已落地模块

- `files/`
  文件上传、列表、删除与解析触发的 canonical 代码位置，承接原 `app.services.file_service`。
- `system/`
  系统初始化与运行时信息查询的 canonical 代码位置，承接原 `app.services.system_service`。
- `teaching_tools/`
  教学工具实现的 canonical 代码位置。工具注册语义在 `app.shared.infra.tools.teaching_registry`，具体工具函数在这里。

## 一句话总结

`support/` 不是新的杂项目录，而是 workflows 单层化之后承接“非引擎业务用例”的正式区域。
