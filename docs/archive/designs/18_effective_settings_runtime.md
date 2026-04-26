# effective settings 运行时解析

本文档说明 AITeachMe 运行时最终生效的项目级配置如何解析，以及为什么不能再让模块在深层逻辑里各自散读项目 settings 文件。

## 1. 真相链路

运行时配置统一收敛为：

```text
code defaults
  -> optional project override
  -> system_runtime_settings
  -> effective settings
```

对应入口：

- `backend/app/shared/infra/settings/settings.py::get_settings()`

设置页暴露的 env 类配置另有一层轻量运行时覆盖：

```text
system_runtime_settings.__env_overrides__
  -> .env / deployment env
  -> get_env()
```

也就是说，本地用户在设置页保存的模型网关、搜索、解析服务授权会优先于 `.env`；某个 key 没有数据库覆盖时，才继续使用 `.env` / 部署平台变量。

## 2. 什么进入 effective settings

只有明确属于“项目级运行策略”的配置才进入 `Settings` schema，例如：

- 模型路由
- 上传限制
- planner / docgen 的教学策略项
- rag / local_rag
- `search.retriever_profile`
- `knowledge_graph.sync_after_docgen`
- 粗粒度 observability 开关

## 3. 什么不再进入 effective settings

以下内容已经从 `Settings` schema 中收回：

- parser chain 内部常量
- workflow 私有 timeout / 并发 / cache / fusion 参数
- LLM 并发与默认 token budget
- embedding 分批参数
- LangSmith 输入/输出截断与保留条数细节

这些值现在由对应模块中的代码常量负责，不再走 settings 数据库覆盖。

## 4. 为什么这样做

如果把“项目级运行策略”和“模块内部执行常量”都混在一个 settings 面里，会出现两个问题：

1. 设置页暴露了很多其实不该调的低层旋钮
2. 数据库里会写入看似可改、实际并不会改变核心行为的伪配置

收缩后：

- `get_settings()` 只表达真正需要跨模块共享的项目级策略
- lane 内部预算和执行细节回到对应模块，减少错位

## 5. system_runtime_settings 的加载时机

数据库初始化完成后，会从 `system_runtime_settings` 表读取全局覆盖，并写入当前进程内的 settings override；同时会加载 `__env_overrides__`，让 `get_env()` 先读数据库覆盖值。

因此：

- 本地模式下，保存系统级配置后当前进程可立刻生效
- 重启后，数据库中的覆盖仍会重新装载
- 已废弃 key 会在规范化阶段被忽略，并在 overview 构建时回写清洗

## 6. 一句话

`effective settings` 是运行时真相，但它现在只承载项目级策略，不再承载模块内部常量。
