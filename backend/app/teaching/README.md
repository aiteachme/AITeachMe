# Teaching 分层说明

最后更新：2026-04-15

`app.teaching` 是教学语义层。它负责回答“怎么教、怎么解释、怎么组织教学表达”，但不负责数据库接入、工具注册表实现、workflow 编排或 API 控制流。

一句话理解：
> `teaching` 负责“教学表达是什么”，不是“底层能力怎么接”。

## 1. 当前边界

推荐依赖方向：

```text
api -> services -> workflows -> teaching -> shared.infra -> shared.kernel
```

这条链里要特别注意：

- `teaching` 可以依赖 `shared.infra`
- `workflows` 和 `services` 可以消费 `teaching`
- `teaching` 不反向依赖 `workflows`

## 2. 这层和 Planner / DocGen 的关系

当前 planner-confirm-docgen 主线里，`teaching` 主要提供两类直接能力：

| 目录或文件 | 对 planner / docgen 的作用 |
| --- | --- |
| `runtime_config.py` | 把项目配置投影成教学视角下的 planner/docgen 默认值 |
| `documents/` | 提供章节脚手架、标题整理、overview / recap / 学习目标等教学表达组件 |

这两处是当前知识构建链最值得先看的 teaching 入口。

## 3. 公开入口怎么用

### 3.1 `app.teaching`

`teaching/__init__.py` 当前提供的是最轻的公共入口：

```python
from app.teaching import (
    list_teaching_functions,
    run_teaching_function,
    teaching_function,
)
```

适合上层只想消费 teaching tool 公共接口的场景。

### 3.2 `teaching.py`

`teaching.py` 是 teaching tool 的 canonical 业务入口。

它负责：

- 提供 `@teaching_function(...)`
- 暴露 `list_teaching_functions()` 和 `run_teaching_function()`
- 把 teaching-owned tool 挂到 `app.shared.infra.tools` 的统一注册表
- 在模块加载时注册 tool registry sync hook，保证注册表重建后 teaching tool 能重新同步

重要结论：

- teaching 可以拥有“工具语义”
- 真正的工具注册表仍然在 `infra.tools`

## 4. `runtime_config.py` 的定位

`runtime_config.py` 不是在定义底层环境变量，而是在定义教学视角下如何解释这些配置。

当前最重要的内容是 planner / docgen 相关默认值，例如：

- 默认语气 `tone`
- 默认 digest 模式 `digest_mode`
- `sprint` / `systematic` 的章节范围
- 目标篇幅和默认教学节奏

如果想调整“构建方案默认更像冲刺复习还是系统梳理”，先看这里。

## 5. `documents/` 的定位

`documents/` 是 teaching 对 docgen 最直接的输入面。

当前重点文件：

- `documents/content_blocks.py`
  教学块原语，例如术语速览、学习目标、对照块
- `documents/report_generation.py`
  标题收敛、章节导学、overview / recap 等更复杂的教学文档辅助

这层表达的是：

- 标题该怎么落地
- 一章应该先讲什么
- 学习目标和 recap 应该怎样呈现得像“老师在讲”

它不决定 docgen graph 先跑 research 还是先跑 writer。

## 6. 其他目录怎么理解

| 目录或文件 | 当前定位 |
| --- | --- |
| `tools.py` | teaching-owned 内建工具实现 |
| `context.py` | 教学上下文组装，偏 teaching 语义表达 |
| `checker.py` | 兼容 facade，底层 canonical checker 在 `shared.infra.checker` |
| `memory/` | teaching 侧 facade，canonical memory 在 `shared.infra.memory` |
| `skill_tools.py` | 历史兼容 shim，不作为新能力入口 |

对这轮而言，`checker.py` 和 `memory/` 的结论很明确：

- 保留兼容入口可以
- 不要继续把它们发展成第二套底层系统

## 7. Tool / Toolpack / Skillpack 要区分

### `teaching tool`

- 真正可执行
- 由 `@teaching_function(...)` 定义
- 最终注册进 `infra.tools` 的统一 registry

### `toolpack`

- 一组外部工具扩展
- 由 `shared.infra.tools.tool_loader` 加载
- 属于运行时扩展机制

### `skillpack`

- `SKILL.md` 风格提示策略包
- 提供 prompt guidance、默认值、推荐 tag
- 不执行代码

所以：

- teaching tool 仍然是 tool
- skillpack 不是 teaching tool
- toolpack 也不是 `teaching/tools.py` 的替代品

## 8. 什么不该放进 Teaching

下面这些内容不要放到 `teaching`：

- 数据库、存储、LLM、retriever、reader 的底层接入
- workflow graph、state、node、router
- workflow-local runtime
- API 请求编排
- 第二套 tool registry / memory store / checker engine

判断方法：

- 在描述“怎么教”，放 `teaching`
- 在描述“流程怎么跑”，放 `workflows`
- 在描述“能力怎么接”，放 `shared.infra`

## 9. 阅读顺序

第一次读 `teaching`，建议按下面顺序：

1. `teaching.py`
2. `runtime_config.py`
3. `documents/__init__.py`
4. `documents/content_blocks.py`
5. `documents/report_generation.py`
6. `tools.py`
7. 最后再看 `checker.py`、`memory/`、`skill_tools.py`

## 10. 一句话总结

`teaching` 是教学语义层。
它定义“怎么解释、怎么组织、怎么让知识更像老师在讲”，并把这些表达提供给 planner / docgen / interact；底层接入仍然来自 `infra`，流程顺序仍然来自 `workflows`。
