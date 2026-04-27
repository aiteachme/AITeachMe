# 17. 设置与配置归属

最后更新：2026-04-27

本文是设置系统的当前事实源：哪些值来自部署环境，哪些进入 `Settings`，哪些只是模块内部常量。

## 1. 真相链路

项目级运行策略：

```text
code defaults
  -> optional PROJECT_SETTINGS_PATH override
  -> system_runtime_settings
  -> get_settings()
```

env 风格的授权与连接信息：

```text
system_runtime_settings.__env_overrides__
  -> .env / deployment env
  -> get_env()
```

含义：

- `.env` 和部署平台变量仍是基础设施输入。
- 本地设置页保存到数据库，不回写 `.env`。
- 本地保存后的授权、模型网关、搜索和解析配置会优先于 `.env`。
- 云端普通用户只读，不写全局 `system_runtime_settings`。
- 用户级非敏感覆盖保存在 `user.runtime_settings_json`，不再使用单独的一对一用户设置表。
- 当前有效 settings 快照保存在 `system_runtime_settings.effective_settings_json`，不再使用单独快照表。

## 2. 分层职责

| 层 | 负责什么 | 典型例子 | 写入者 |
| --- | --- | --- | --- |
| deployment env / `.env` | 部署、密钥、连接串、首次启动默认值 | `APP_MODE`、`DATABASE_URL`、`AUTH_*`、`S3_*`、`LLM_API_KEY`、`LLM_BASE_URL`、搜索 provider key | 部署平台或本地用户 |
| code defaults | 项目级默认行为 | 模型路由默认值、上传限制、Planner/DocGen 策略、RAG、搜索画像、图谱同步、观测开关 | 代码 |
| `PROJECT_SETTINGS_PATH` | 可选外部项目 override | 开发/部署侧临时覆盖非敏感项目策略 | 显式配置者 |
| `system_runtime_settings` | 本地设置页全局覆盖与有效配置快照 | `models.*`、`ingest.*`、`planner.*`、`docgen.*`、`rag.*`、`search.retriever_profile`、`knowledge_graph.sync_after_docgen`、粗粒度 observability、`settings_hash` | 设置页/API |
| module constants | 模块内部执行细节 | timeout、并发、cache/fusion、parser chain 常量、LLM token budget、embedding batch | 对应模块代码 |

代码默认值集中在：

- `backend/app/shared/infra/settings/defaults.py`

运行时入口：

- `backend/app/shared/infra/settings/settings.py::get_settings()`
- `backend/app/shared/infra/env_support.py::get_env()`

## 3. 不进入 Settings 的内容

这些值不再放进 `shared/infra/settings` 的可写面，也不暴露到设置页：

- workflow/lane 私有执行预算
- parser chain 内部常量
- search cache、timeout、fusion、并发细节
- LLM 并发和默认 token budget
- embedding 分批参数
- LangSmith 输入/输出截断细节

原则：只有跨模块共享、用户确实能理解并安全修改的项目级策略才进入 `Settings`。

## 4. 设置页规则

设置页只消费后端 `/api/v1/system/settings` 返回的 section/entry 元数据。

后端字段职责：

- `SettingSection.id / label / description` 决定 tab。
- `SettingEntry.ui_group` 决定 tab 内分组。
- `SettingEntry.ui_order` 决定稳定排序。
- `SettingEntry.source / editable / secret` 决定控件和读写策略。

前端不维护 `tab -> key` 映射，也不维护浏览器本机设置。

当前面板分区：

1. `connection`
2. `models`
3. `learning`
4. `search`
5. `observability`

## 5. 一句话

`get_settings()` 只承载项目级策略；`get_env()` 承载部署和授权；模块私有预算回到模块代码里。
