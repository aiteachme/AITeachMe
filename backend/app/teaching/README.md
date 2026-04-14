# Teaching 分层说明

最后更新：2026-04-14

`app.teaching` 是教学语义层。
它负责回答：

- 这个系统应该怎样“教”用户
- 教学表达应该长什么样
- 教学工具应该提供什么能力
- 教学上下文应该如何拼装

它**不**负责：

- 数据库、存储、LLM、检索这些底层接入
- workflow graph 的编排
- API 请求流程控制

对新同学来说，先记住这句区分：

> `teaching` 负责“怎么教”，不是负责“能力怎么接”或“流程怎么排”。

## 1. 它在整体架构中的位置

当前推荐依赖方向：

```text
api -> services -> workflows -> teaching -> shared.infra -> shared.kernel
```

含义是：

- `teaching` 建立在 `infra` 之上。
- `teaching` 可以调用 `infra` 的 LLM、search、memory、tool registry。
- `workflows` 再把 `teaching` 提供的教学语义组织成具体流程。

## 2. 新同学先用这张“找东西地图”

| 我想找什么 | 应该先看哪里 |
| --- | --- |
| 教学工具注册入口 | `teaching.py` |
| 内置教学工具实现 | `tools.py` |
| 教学上下文拼装 | `context.py` |
| 教学配置投影 | `runtime_config.py` |
| 教学文档脚手架 | `documents/` |
| 学习报告与章节标题处理 | `documents/report_generation.py` |
| 术语表、学习目标块 | `documents/content_blocks.py` |
| 教学事件日志 | `app.shared.infra.events` |
| checker 旧导入兼容 | `checker.py` |
| 共享 memory 入口 | `memory/`、`app.shared.infra.memory` |
| 历史 skill 导入兼容 | `skill_tools.py` |

## 3. `teaching` 里现在实际有哪些模块

### 3.1 `teaching.py`

这是教学工具层的主入口。

它做的事不是“自己实现一套工具系统”，而是：

- 提供 `@teaching_function(...)`
- 把 teaching-owned tool 注册到 `app.shared.infra.tools`
- 提供 `list_teaching_functions()` 和 `run_teaching_function()`

所以团队要明确：

- `teaching` 可以拥有工具语义
- 但工具注册表本体仍然在 `infra.tools`

### 3.2 `tools.py`

这里放教学工具的具体实现。

当前内置工具包括：

- `solve_step_by_step`
- `generate_similar_problems`
- `explain_formula`
- `compare_concepts`

这些函数属于教学层，因为它们输出的是教学化结果；
但它们的运行时注册与执行，仍然走 `infra.tools`。

### 3.3 `context.py`

这是教学上下文组装器。

它负责把下面这些信息拼成一份适合 LLM 使用的教学消息列表：

- 系统提示词
- 用户画像
- 本地知识片段
- 历史记忆
- 对话历史
- 可用工具名

它会调用：

- `shared.infra.memory`
- `shared.infra.search`

但它之所以放在 `teaching`，是因为它的核心价值是“教学上下文怎么表达”，不是“底层搜索怎么接”。

### 3.4 `runtime_config.py`

这里负责把项目配置投影成教学层可直接消费的配置对象。

当前最重要的是 planner 相关默认值，例如：

- 默认语气 `tone`
- 默认 digest 模式 `digest_mode`
- `sprint` / `systematic` 各自的章节范围和目标篇幅

这个文件不是在定义环境变量，而是在定义“教学视角下怎么解释这些配置”。

### 3.5 `documents/`

这是教学表达最集中的目录。

当前主要分成两部分：

- `content_blocks.py`
  通用教学内容块，例如术语速览、学习目标对照。
- `report_generation.py`
  更复杂的教学文档与报告辅助，例如：
  - 章节标题清洗与收敛
  - 章节导学与 recap
  - 文档概览生成
  - 教学脚手架补齐

如果你要改“章节该怎么讲、标题该怎么写、报告该怎么组织”，通常应该先看这里。

### 3.6 事件与记忆的真实归属

这一轮已经删掉：

- `teaching/events.py`
- `memory_compat.py`

原因很简单：

- 教学事件日志本来就是共享学习闭环能力，应该统一归 `app.shared.infra.events`
- memory 的 canonical 实现本来就在 `app.shared.infra.memory`
- 开发期继续保留第二套历史入口，只会让团队继续误判边界

现在团队应明确：

- 事件日志入口看 `app.shared.infra.events`
- 共享 memory 入口看 `app.shared.infra.memory`
- `teaching/memory/` 只是面向 teaching 语义的 facade，不再是第二套实现

### 3.7 `checker.py`

这是 checker 的兼容 facade。
它只是把：
- `check_answer`
- `check_exact`
- `check_keywords`
- `check_with_llm`
- rubric 相关类型

从 `shared.infra.checker` 重新暴露回教学侧旧入口。
结论：
- checker 的共享实现属于 `infra`
- `teaching.checker` 只适合作为历史过渡入口，后续也应继续收敛

### 3.8 `skill_tools.py`

这是历史兼容 shim。

它只是为了兼容旧的 skill 导入路径，把 `tools.py` 里的教学工具再导出一次。
新代码不要继续往这里加能力。

## 4. teaching tool、toolpack、skillpack 到底怎么区分

这是最容易混的地方之一。

### `teaching tool`

- 真正可执行
- 例如 `solve_step_by_step`
- 最终注册进 `infra.tools` 的工具注册表

### `toolpack`

- 一组外部工具扩展包
- 由 `shared.infra.tools.tool_loader` 加载
- 是运行时扩展模型

### `skillpack`

- `SKILL.md` 风格的提示策略包
- 只提供 prompt guidance、默认值和推荐 tag
- 不执行代码

结论：

- teaching-owned tool 仍然是 `tool`
- skillpack 不是教学工具
- toolpack 也不是教学工具目录的替代品

## 5. 真实调用链怎么理解

### 5.1 教学工具的调用链

1. 在 `tools.py` 里用 `@teaching_function(...)` 定义工具
2. `teaching.py` 内部转发到 `infra.tools.tool(...)`
3. `infra.tools.registry.ToolRegistry` 统一注册
4. 上层通过 `run_teaching_function(...)` 或 `run_agent_tool(...)` 执行

这条链说明：

- 教学语义在 `teaching`
- 执行体系在 `infra`

### 5.2 教学上下文的组装链

`build_teaching_context(...)` 会：

1. 读取用户画像
2. 检索本地知识
3. 回忆历史记忆
4. 拼装成一组 LLM messages

这里“用什么能力”来自 `infra`，但“最后怎么讲给学生”来自 `teaching`。

### 5.3 Digest 对教学文档能力的复用

DocGen 在生成章节时会复用 `teaching.documents` 中的能力，比如：

- 标题清洗
- 章节导学
- 术语表块
- 学习目标对照
- recap / overview

这说明 `teaching` 提供的是“教学原料”，`workflows` 决定这些原料何时被调用。

## 6. 哪些东西不应该放进 `teaching`

下面这些内容不要回流到 `teaching`：

- 数据库、存储、LLM、retriever、reader、tracing 的底层接入
- workflow graph、state、node、router
- workflow-local runtime
- API 请求编排
- 第二套 tool registry
- 第二套 memory store
- 第二套 checker engine

简单判断：

- 如果你在描述“能力怎么接”，它更像 `infra`
- 如果你在描述“这轮流程怎么跑”，它更像 `workflows`
- 如果你在描述“给学生看什么、怎么讲、怎么引导”，它更像 `teaching`

## 7. 新代码放置速查

| 需求 | 更合适的目录 |
| --- | --- |
| 新增一个教学工具 | `teaching/tools.py` 或拆出新的 teaching tool 模块 |
| 新增一个章节导学块 | `teaching/documents/content_blocks.py` |
| 新增章节标题优化规则 | `teaching/documents/report_generation.py` |
| 新增教学上下文拼装字段 | `teaching/context.py` |
| 新增 planner 教学默认值 | `teaching/runtime_config.py` |
| 新增共享 memory 存储能力 | `shared.infra.memory` |
| 新增 workflow 节点 | `workflows/...` |

## 8. 阅读建议

第一次读 `teaching`，建议顺序如下：

1. `teaching.py`
2. `tools.py`
3. `context.py`
4. `runtime_config.py`
5. `documents/__init__.py`
6. `documents/content_blocks.py`
7. `documents/report_generation.py`
8. 最后再看 `checker.py`、`memory/`、`skill_tools.py` 这些兼容入口

## 9. 一句话总结

`teaching` 是教学语义层。
它负责定义“怎么教、怎么解释、怎么组织教学表达”，但底层能力仍然来自 `infra`，流程编排仍然来自 `workflows`。
