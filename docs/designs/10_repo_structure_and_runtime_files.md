# 10. 仓库结构与运行时文件

最后更新：2026-04-10

本文档同时描述两套口径：

- 当前代码状态：仓库里今天已经落地的结构。
- 目标架构状态：接下来几轮 refactor 收敛后的最终语义。

## 1. 总体依赖方向

```text
api -> services -> workflows -> teaching -> shared/infra -> shared/kernel
```

## 2. 当前代码状态

### 2.1 `shared/infra`

- canonical tool registry 已在 `shared/infra/tools`。
- `skills` 已明确为 `SKILL.md` prompt skillpack。
- `traced_execution.py` 已是通用 traced execution helper。
- `execution.py` 只保留兼容 shim。
- `shared/infra/runtime.py` 已删除，避免和 `workflows/.../runtime` 语义冲突。
- `runtime_paths.py` 只保留本地运行路径 helper。
- `orchestrators/` 已删除。
- `prompt_builders/` 已删除，业务 prompt 全部回到 workflow 内部。
- `prompt_loader.py` 仍可保留在 `infra`，因为它只是模板渲染 helper，不是 prompt 内容归属层。
- `llm_support/` 是当前 canonical LLM 层。
- `llm.py` 只保留兼容 shim。
- `llm_support/routing.py` 是当前 canonical 模型路由位置。
- `model_router.py` 只保留兼容 shim。
- external `toolpack` loader 已进入 `shared/infra/tools/tool_loader.py`。

### 2.2 `teaching`

- `teaching/documents` 继续拥有教学脚手架与 overview。
- `teaching/tools.py` 注册 teaching-owned 原子函数。
- teaching 不再拥有第二套 registry。

### 2.3 `workflows`

- graph/state 继续在 `workflows`。
- Digest DocGen 的 concrete runtime 已迁回 `workflows/digest/docgen/runtime`。
- workflow-local runtime trace 命名改为 `workflow_runtime.docgen.*`。
- `shared/infra` 不再新增 `runtime` 入口文件，避免和 workflow-local runtime 混淆。

## 3. 目标架构状态

### 3.1 `shared/infra`

长期只保留：

- tool registry
- toolpack loader
- skillpack loader
- search / llm / storage / memory / tracing
- 一个通用 traced execution helper
- 少量跨引擎可复用 helper

长期不再保留业务专属 orchestrator 类，也不再保留 workflow-local prompt builder。

### 3.2 `teaching`

长期只保留教学语义：

- 课程块
- 文档脚手架
- 练习与反馈表达
- teaching-owned tool implementations

### 3.3 `workflows`

长期承载：

- graph/state/router
- workflow-local runtime
- subgraph
- workflow-local prompt assembly

## 4. 权威判断句

- 离开 Digest/Interact/Examine 仍然成立的东西才进 `infra`。
- 回答“怎么教”的东西进 `teaching`。
- 回答“这轮流程怎么跑”的东西进 `workflows`。

## 5. 扩展模型

### 5.1 Tool

- 原子动作
- 可执行
- 稳定输入输出
- canonical registry 唯一注册

### 5.2 Toolpack

- 真实外部工具扩展
- 目录：`backend/toolpacks/<name>/manifest.yaml + handler.py`
- 也支持用户目录：`~/.atm/toolpacks/<name>/...`

### 5.3 Skillpack

- 策略包
- 目录：`backend/skills/<name>/SKILL.md` 或 `~/.atm/skills/<name>/SKILL.md`
- 不执行代码
- 只提供 prompt guidance、defaults、recommended tool tags

## 6. 当前已确认的结构问题

- `infra/orchestrators` 与 workflow node 职能重叠。
- `infra/prompt_builders` 与 workflow prompts 分层冲突。
- `PedagogyWriter` 同时踩进 `infra` 和 `teaching`。
- 旧 `tool_loader.py` 只有 YAML 元数据，没有 handler 绑定。
- `skills` 之前几乎没有进入 planner/docgen 主运行链。

这些问题现在都不再作为“推荐结构”继续扩张。
