# Toolpacks

`backend/toolpacks/` 是项目内可选的外部工具扩展目录，当前只保留说明，没有内置 toolpack 实现。

这不是普通学习用户上传工具的产品入口。它面向开发者、部署管理员和企业私有扩展场景；普通用户不需要也不应该编写 Python `handler.py`。

如果短期没有私有工具集成，也可以让这个目录保持只有 README。真正删除目录前，需要同步调整 `app.shared.infra.tools.tool_loader` 和 `shared/infra` 文档里的项目内 toolpack 入口说明。

## 目录约定

```text
backend/toolpacks/
└── <toolpack_name>/
    ├── manifest.yaml
    └── handler.py
```

## manifest.yaml

```yaml
name: demo_pack
description: 示例工具包
entrypoint: handler.py:register_toolpack
enabled: true
```

## handler.py

- 推荐提供 `register_toolpack(registry)` 或 `register_toolpack()`。
- 可以直接返回一个 `ToolDefinition`，或返回 `list[ToolDefinition]`。
- 也可以在函数内部自行往 canonical registry 注册工具。

只有带有 `handler.py` 并返回真实 `ToolDefinition` 的 toolpack 才会注册为运行时工具。单纯的 YAML 描述不会创建可执行工具。

## 优先级

- 项目内：`backend/toolpacks`
- 本机/部署方覆盖目录：`~/.atm/toolpacks`

同名 toolpack 后加载者覆盖先加载者，因此本机或部署方可以覆盖项目内实现。

## 与 Prompt 策略的区别

- toolpack：注册可执行工具，适合搜索、计算、系统集成、MCP 桥接等动作。
- prompt 策略：由 Planner、DocGen 节点和 confirmed plan 显式组织，不再通过独立 prompt 扩展目录维护。
