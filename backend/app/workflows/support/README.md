# Support 模块说明

最后更新：2026-04-16

`backend/app/workflows/support/` 是 workflows 单层化后的支撑业务区，承接原本不属于五大 AI 引擎、但仍属于后端业务层的模块。

## 目标

- 放置 `auth`、`subjects`、`system`、`export_import` 这类非引擎业务模块
- 避免把这类逻辑重新塞回 `api/` 或 `shared.infra/`
- 与 `ingest / digest / interact / examine / profile` 保持平级，但不强制使用 LangGraph

## 默认模板

```text
workflows/support/<module>/
  __init__.py
  README.md
  <use_case_a>.py
  <use_case_b>.py
  streams.py                # 可选
  lib/                      # 可选
```

推荐做法：

- 按用例或链路命名文件，例如 `catalog.py`、`sessions.py`、`settings.py`、`deletion.py`
- 没有真实调用方的旧兼容壳直接删除，不保留空门面

## 当前已落地模块

- `auth/`
  访客身份、邮箱注册登录、token 与验证码的 canonical 代码位置，承接原 `app.services.auth_service`。
- `auth/identity.py`、`auth/sessions.py`、`auth/smtp.py`
  当前鉴权模块的 canonical 子入口。
- `export_import/`
  学科级课程包导入导出的 canonical 代码位置，承接原 `app.services.export_import_service`。
- `export_import/exports.py`、`export_import/imports.py`、`export_import/courses.py`
  当前课程包模块的 canonical 子入口。
- `system/`
  系统初始化与运行时信息查询的 canonical 代码位置，承接原 `app.services.system_service`。
- `system/init.py`、`system/settings.py`
  当前系统模块的 canonical 子入口。
- `subjects/`
  学科注册、归属校验、删除预览与级联删除的 canonical 代码位置，承接原 `app.services.subject_service` 与 `subject_deletion_service`。
- `subjects/catalog.py`、`subjects/deletion.py`
  当前学科模块的 canonical 子入口。

## 一句话总结

`support/` 不是新的杂项目录，而是 workflows 单层化之后承接“非引擎业务用例”的正式区域。

文件上传、列表、删除与解析触发已经收口到 `workflows/ingest/intake/`，因为它们直接管理 Ingest 的 `RawFile` 生命周期。
