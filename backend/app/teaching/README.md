# Teaching 层说明

`app.teaching` 是教学领域复用层。

它位于 `shared/infra` 之上、`workflows` 之下，负责沉淀“教学语义”本身，而不是模型接入细节，也不是 LangGraph 编排细节。

一句话理解：

- `shared/infra` 解决“能力怎么接、怎么跑、怎么观测”。
- `teaching` 解决“这些能力在教学场景里怎么表达和复用”。
- `workflows` 解决“在五大引擎里按什么顺序执行”。

## 1. Teaching 层当前负责什么

当前 `teaching/` 主要承担三类职责：

- 教学上下文组装
- 教学函数/技能的复用封装
- 面向知识文档的教学脚手架与文档结构辅助

它不是单独的“第六个引擎”，而是五大引擎的教学语义支撑层。

## 2. 当前目录说明

| 文件/目录 | 作用 | 备注 |
| --- | --- | --- |
| `context.py` | 教学上下文组装 | 把用户消息、画像、知识片段、历史记忆装成适合 LLM 的 messages |
| `checker.py` | 教学判卷/评估辅助 | 给 examine / profile 一类能力提供基础判定逻辑 |
| `events.py` | 教学领域事件定义与记录辅助 | 记录教学行为而不是底层系统行为 |
| `teaching.py` | 教学函数注册中心 | 统一 `@teaching_function`、`run_teaching_function()`、`list_teaching_functions()` |
| `skill_tools.py` | 轻量教学技能 | 例如分步讲解、概念对比、相似题生成 |
| `documents/` | 教学文档脚手架 | 负责知识文档 overview、章节导读、 recap 等结构辅助 |
| `memory/` | 教学语义下的记忆封装 | 更贴近 learner profile / learner doc 的表达 |
| `memory_compat.py` | 兼容层 | 迁移阶段的桥接文件，避免上层一次性大改 |

## 3. 关键模块怎么理解

### 3.1 `context.py`

这是教学场景的消息组装器。

它做的事不是“检索”本身，而是把这些来源拼成一个教学上下文：

- 系统角色设定
- 学习者画像
- 相关知识片段
- 历史记忆
- 当前用户消息

适合给这些场景使用：

- 伴读式问答
- 苏格拉底式追问
- 习题讲解
- 章节总结

不适合放在这里的内容：

- 某个 workflow 节点专属的 state 字段拼接
- 与某个 API schema 强绑定的 request/response 逻辑

### 3.2 `teaching.py`

这里是教学函数注册中心，抽象的是“教学动作”，不是“底层工具”。

两者区别：

- Tool：原子能力，例如搜索、抓取、记忆读写、文本处理。
- Teaching Function：教学动作，例如解释概念、追问理解、生成练习、总结会话。

后续如果我们要把教学策略抽成更稳定的接口，这里会是核心承载点之一。

### 3.3 `skill_tools.py`

这里放的是轻量教学技能，偏模板化、可快速复用。

当前更像是“教学技能样例库”，作用有两个：

- 给技能体系提供教育域原型
- 给后续重构 Teaching Skills 提供落点

后续如果某个教学能力需要：

- 多步编排
- 多来源检索
- 压缩上下文
- 富媒体输出

那它应该进一步升级到 `shared/infra/skills/` 的重量级 Skill，而不是一直停留在这里。

### 3.4 `documents/report_generation.py`

这是目前 digest 文档生成里最重要的 teaching 侧模块。

它负责的不是整条 docgen workflow，而是知识文档的教学化结构辅助，例如：

- 文档总览页
- 章节导读
- recap / 本章要点
- 稳定的章节脚手架

它的价值在于把“教学表达”从 workflow 节点里剥出来，让：

- `workflows/digest/docgen/publish.py`
- `shared/infra/skills/writer.py`

都可以复用一套教学文档骨架。

## 4. 当前与其他层的关系

### 4.1 与 `shared/infra` 的关系

`teaching` 可以依赖 `shared/infra`，例如：

- `context.py` 依赖 memory / search / llm
- `teaching.py` 内置函数依赖 `app.shared.infra.llm`
- `skill_tools.py` 通过 `app.shared.infra.skills.base.skill` 注册轻量技能

但反过来，`infra` 不应该依赖 `teaching` 的教学语义。

唯一需要谨慎的点是当前迁移期存在少量桥接用法，例如 skill 注册时触发 teaching 侧导入，这种情况可以接受，但不要继续扩大。

### 4.2 与 `workflows` 的关系

`teaching` 不负责 LangGraph 编排。

典型分工：

- `workflows/digest/*` 决定什么时候生成章节、什么时候发布。
- `teaching/documents/*` 决定章节导读、文档总览怎么写得更像教学文档。
- `workflows/interact/*` 决定对话流程。
- `teaching/context.py` 决定教学上下文如何拼装。

### 4.3 与 `profile / examine` 的关系

未来 `teaching` 会更多承担“教学解释层”的角色：

- `examine` 给出诊断结果
- `profile` 给出掌握度变化
- `teaching` 决定如何把这些结果解释给学习者听

## 5. 当前存在的现实状态

这个目录现在处于“过渡但可用”的阶段，有两个明显特征：

### 5.1 已经有价值的部分

- `documents/report_generation.py` 已经在 digest 文档链路里实际生效
- `context.py`、`teaching.py`、`skill_tools.py` 提供了教学层抽象原型
- `memory/` 提供了更贴近 learner 语义的接口模型

### 5.2 还不够收敛的部分

- 部分能力和 `shared/infra` 的边界还在迁移中
- `memory_compat.py` 说明还有兼容债务
- 部分教学函数仍然偏样例性质，尚未完全融入主流程

这意味着后续开发应该坚持一个方向：

- 不要为了快，再把教学语义直接写回 workflow 节点
- 应继续把“可复用的教学表达”沉回 `teaching/`

## 6. 后续设计与开发方向

### 6.1 Teaching Skills 体系化

后续应把教学技能分成两层：

- 轻量教学技能：保留在 `skill_tools.py` 或独立小模块中
- 重量级教学 Skill：放入 `shared/infra/skills/`，支持多步编排和 LangSmith 追踪

适合继续建设的能力包括：

- 分步讲解题目
- 公式解释与易错点提醒
- 概念对比
- 从错题反推薄弱知识点
- 章节学习后的形成性提问

### 6.2 Rich Teaching Content

你后续要做“比 PPT 更好看”的知识文档，这一层会继续承担“教学表达”职责，而不是只做纯 Markdown。

重点方向：

- 章节导读结构更稳定
- 公式解释块、易错点块、速记块模板化
- Mermaid 占位与教学脚手架衔接
- 图片/示意图/交互 HTML 的教学化插槽设计

换句话说：

- 生成能力放 `infra/skills`
- 教学呈现规范放 `teaching/documents`

### 6.3 诊断与画像联动

后续 `teaching` 应逐步接住这些输入：

- `profile` 输出的掌握度、薄弱点、复习建议
- `examine` 输出的错题、判卷反馈、知识点命中情况

然后在 `teaching` 层统一转换成：

- 面向学生的解释文本
- 面向文档的个性化提示
- 面向伴读对话的追问策略

### 6.4 LangSmith 适配

Teaching 层以后新增模块时，建议统一带上这些 metadata：

- `subject`
- `workflow`
- `scene`，例如 `digest_doc`, `interact_chat`, `examine_feedback`
- `planner_session_id`
- `confirmed_plan_id`
- `chapter_index`
- `teaching_function` 或 `skill_name`

原则是：

- 教学动作要可追踪
- 教学输出要能回溯到上游构建方案
- 不做“只有文本结果、没有运行上下文”的黑盒教学模块

## 7. 新增代码时该放哪里

可以按这个标准判断：

放在 `teaching/`：

- 讲解模板
- 追问策略
- 教学脚手架
- 教学层记忆表达
- 学习报告/章节导读/本章要点等输出结构

放在 `shared/infra/`：

- LLM 调用
- 检索与抓取
- 技能基类
- 工具注册
- LangSmith tracing
- 存储与缓存

放在 `workflows/`：

- 节点顺序
- state 演进
- fan-out / fan-in
- build lane 的运行控制

## 8. 给后续重构的建议

如果后面继续推进你文档里写的 refactor 计划，`teaching/` 应该成为这几个能力的稳定落点：

1. 统一的教学输出模板库
2. 富媒体教学块规范
3. examine/profile 到文档与对话的解释适配层
4. 可复用的教学函数与教学技能目录
5. 面向 LangSmith 的教学语义 metadata 规范

这样后续无论是：

- docgen 生成结构化知识文档
- interact 做伴读式解释
- examine 给出诊断反馈

都不会重复各写一套“教学表达逻辑”。

---

如果你现在主要在做 digest 重构，可以把 `teaching/` 当作“教学表达与教学脚手架层”：

- 想改模型能力，去 `shared/infra`
- 想改教学表达，来 `teaching`
- 想改流程编排，去 `workflows`
