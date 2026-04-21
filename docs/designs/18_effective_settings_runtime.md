# effective settings 运行时解析

本文档说明 AITeachMe 运行时最终生效的配置如何解析，以及为什么不能再让模块在深层逻辑里各自散读项目 settings 文件。

## 1. 目标

解决这个问题：

> 设置页保存成功，但后端模块运行时没有真正使用这份设置。

为避免这种错位，运行时配置需要收敛成一份统一真相：

```text
code defaults
  -> optional project override
  -> system runtime settings
  -> effective settings
```

## 2. project settings 与 effective settings

### code defaults

来源：

- `backend/app/shared/infra/settings/defaults.py`

作用：

- 提供系统默认行为
- 是当前唯一默认值真源

### optional project override

来源：

- `PROJECT_SETTINGS_PATH` 指向的外部文件

作用：

- 只在显式配置时参与 merge
- 用于叠加少量项目级策略覆盖

### effective settings

来源：

- code defaults
- optional project override
- `system_runtime_settings`

作用：

- 作为当前进程里真正被业务模块消费的配置对象

对应入口：

- `backend/app/shared/infra/settings/settings.py::get_settings()`

## 3. 当前 merge 规则

当前实现采用：

```text
effective settings = code defaults + optional project override + system runtime settings
```

其中：

- code defaults 和递归 merge 逻辑统一由 `defaults.py` 提供
- external override 来自 `PROJECT_SETTINGS_PATH`
- system runtime settings 来自数据库 `system_runtime_settings`
- merge 后再通过 `Settings.model_validate(...)` 做统一校验

## 4. 为什么这样做

如果模块直接把项目 settings 文件当成最终真相，就会出现：

- 设置页保存到了数据库
- 但模块行为没有变化

这是配置系统最危险的错位状态。

现在通过把 `get_settings()` 升级为返回 effective settings，可以在不重写全部调用点的前提下，让大多数模块自然吃到系统级覆盖。

## 5. 为什么 repo 不再自带 settings_default.yaml

原因很直接：

1. 默认值放在代码里更集中
2. 本地用户主要只需要维护 `.env`
3. 外部项目 override 只有在确实需要时才应该出现

也就是说：

- code defaults 负责“系统能跑起来的默认行为”
- external project override 负责“某个项目 / 环境额外想覆盖什么”
- 数据库覆盖负责“本地运行时临时调优”

## 6. system_runtime_settings 的加载时机

数据库初始化完成后，会从 `system_runtime_settings` 表读取全局覆盖，并写入当前进程内的 settings override。

因此：

- 本地模式下，保存系统级配置后当前进程可立刻生效
- 重启后，数据库中的覆盖仍会重新装载

## 7. 本地与云端差异

### 本地模式

- 设置页可写 `.env`
- 设置页可写 `system_runtime_settings`
- effective settings 会随着系统级覆盖更新

### 云端模式

- 普通用户设置页只读
- 不存在普通用户写入 `system_runtime_settings` 的路径
- 未来管理员模式可以在这里扩展写入能力

## 8. 一句话

现在没有 repo 必备的默认 settings 文件；`effective settings` 才是运行时真相。
