# Toolpacks

`backend/toolpacks/` 是项目内真实可执行的外部工具扩展目录。

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

## 优先级

- 项目内：`backend/toolpacks`
- 用户目录：`~/.atm/toolpacks`

同名 toolpack 后加载者覆盖先加载者，因此用户目录可以覆盖项目内实现。
