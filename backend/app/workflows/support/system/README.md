# System Support

最后更新：2026-06-15

职责：提供系统级 API 用例，包括前端初始化、设置页目录、设置读取/更新和社区信息。

```text
输入: runtime/settings request
输出: frontend init payload / settings overview
```

## 文件

```text
init.py       # 前端运行时初始化 payload
catalog.py    # 设置页 tabs/groups/items 声明
settings.py   # 设置概览和本地设置更新
community.py  # 社区/公开信息
```

## 1. 前端初始化

输入：当前运行环境、用户上下文、系统配置

动作：组合前端启动所需的 runtime 信息。

输出：初始化 payload。

## 2. 设置页

输入：设置查询或本地设置更新请求

动作：读取设置目录、当前配置、可编辑项和运行状态；本地模式下可写入允许更新的配置。

输出：

```text
settings tabs
settings groups
settings entries
updated local settings
```

## 边界

`system` 是 support 用例，不是 LangGraph lane。

它可以组合 `shared.infra` 的运行时信息，但不承载引擎业务逻辑。
