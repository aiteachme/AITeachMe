# 03. Tools Refactor

## 1. 目标

把“可执行工具”和“策略包”彻底拆开，并把用户自定义扩展变成真功能。

## 2. 最终模型

### 2.1 Tool

- 原子动作
- 运行时真正可调用
- 有稳定的输入输出契约
- 统一注册到 canonical tool registry

### 2.2 Skillpack

- 文件形态：`SKILL.md`
- 作用：注入 prompt guidance、defaults、recommended tool tags
- 不执行代码
- 不注册 handler

### 2.3 Toolpack

- 文件形态：`manifest.yaml + handler.py`
- 作用：向 canonical registry 注册真实可执行工具
- 支持项目内与用户目录

## 3. 目录约定

```text
backend/tools/              # 过渡态 YAML 元信息
backend/toolpacks/<name>/   # 真正外部工具扩展
backend/skills/<name>/      # Prompt Skillpack
~/.atm/toolpacks/<name>/    # 用户工具扩展
~/.atm/skills/<name>/       # 用户 skillpack
```

## 4. Loader 行为

### 4.1 Toolpack Loader

- 扫描 `backend/toolpacks`
- 扫描 `~/.atm/toolpacks`
- 读取 `manifest.yaml`
- 导入 `handler.py`
- 调用 `register_toolpack()` 或 `register_toolpack(registry)`
- 最终注册到 canonical tool registry

### 4.2 Skillpack Loader

- 扫描 `backend/skills`
- 扫描 `~/.atm/skills`
- 解析 `SKILL.md` frontmatter
- 暴露 `prompt_scope`、`defaults`、`recommended_tool_tags`

## 5. 兼容口径

- `backend/tools/*.yaml` 继续保留，但仅视为过渡态元信息。
- 不再把 YAML-only 目录宣称成完整扩展入口。
- 真正的“用户自己写 tool 并接入”必须走 `toolpack`。

## 6. Canonical API

### 6.1 Tool

- `ensure_project_tool_modules_loaded()`
- `list_agent_tools()`
- `run_agent_tool()`
- `load_external_toolpacks()`

### 6.2 Skillpack

- `list_skills()`
- `resolve_skillpacks()`
- `render_prompt_scoped_skillpacks()`
- `collect_skillpack_defaults()`
- `collect_recommended_tool_tags()`

## 7. 主流程接入

- planner 读取 `selected_skillpacks`
- prompt 侧注入 skillpack guidance
- docgen research / writer 读取 skillpack 并生成 scoped prompt context
- tool 仍然是最终唯一可执行能力

## 8. LangSmith 影响

- tool 调用继续落在原子工具层
- workflow-local runtime 使用 `workflow_runtime.*`
- 不再把 skillpack 当成 capability span
