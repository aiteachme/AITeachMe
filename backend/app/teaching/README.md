# Teaching 层说明

`app.teaching` 是教学任务适配层。

它位于 `shared/infra` 之上、`workflows` 之下，负责把通用 AI 能力适配成 AITeachMe 的教学任务、教学表达和教学文档结构。

一句话理解：

- `shared/infra` 解决“能力怎么抽象、怎么接、怎么跑、怎么观测”
- `teaching` 解决“这些能力如何服务 AITeachMe 的教学目标”
- `workflows` 解决“这些能力在五大引擎里按什么顺序执行”

---

## 1. Teaching 层到底负责什么

Teaching 层不是第二个基础设施层，也不是第六个引擎。  
它更像是 AITeachMe 的“教学策略与教学表达层”。

当前最适合放在这里的，是三类内容：

- 教学上下文组装
- 教学动作与教学模板
- 面向知识文档、练习和反馈的教学脚手架

换句话说：

- `infra` 提供能力
- `teaching` 决定怎样把这些能力变成“会教”的内容

---

## 2. 当前目录说明

| 文件/目录 | 作用 | 备注 |
| --- | --- | --- |
| `context.py` | 教学上下文组装 | 把用户消息、画像、知识片段、历史记忆装成更适合教学的 messages |
| `checker.py` | 教学判卷/评估辅助 | 给 examine / profile 一类能力提供教学解释辅助 |
| `events.py` | 教学领域事件定义与记录辅助 | 记录教学行为而不是底层系统行为 |
| `teaching.py` | 教学函数注册中心 | 统一 `@teaching_function`、`run_teaching_function()`、`list_teaching_functions()` |
| `skill_tools.py` | 轻量教学技能原型区 | 例如分步讲解、概念对比、相似题生成 |
| `documents/` | 教学文档脚手架 | 负责 overview、章节导读、recap、术语块、学习目标对照等 |
| `memory/` | 迁移期教学记忆兼容层 | 不应继续扩张为第二套 canonical memory |
| `memory_compat.py` | 兼容桥接 | 避免上层一次性大改 |

---

## 3. 和 `infra` 的边界怎么理解

### 3.1 `infra` 负责什么

- LLM / retriever / scraper / memory / storage / tracing
- 通用 tool 与组合 skill
- 通用策略与 runtime 规则

### 3.2 `teaching` 负责什么

- 教学语义
- 课程模式适配
- 教学文档结构
- 错因解释、学习建议、题解表达

### 3.3 当前代码里已经能看到的边界事实

有两个事实很关键：

1. `teaching/context.py` 直接调用 `app.shared.infra.memory.get_user_profile` 和 `recall`
2. `shared/infra/skills/writer.py` 生成草稿后，再调用 `app.teaching.documents.ensure_chapter_learning_scaffold`

这两个事实很适合写进架构文档，因为它们说明：

- canonical memory 在 `infra`
- 教学脚手架在 `teaching`
- writer skill 负责执行，teaching documents 负责“像不像 AITeachMe 的课程”

同时也要说清楚一条边界纪律：

- 这类 `infra -> teaching` 调用属于显式教学表达 hook，不代表 `infra` 可以继续吸收教学语义
- 目标态仍应以 `teaching -> infra` 为主依赖方向

---

## 4. 关键模块怎么理解

## 4.1 `context.py`

这是教学场景的上下文组装器。

它不是在做底层检索，而是在做“教学视角的组织”：

- 系统角色设定
- 学习者画像
- 相关知识片段
- 历史记忆
- 当前用户消息

适合场景：

- 伴读式问答
- 苏格拉底式追问
- 题目讲解
- 章节总结

不适合放在这里的内容：

- 某个 workflow 节点专属 state
- 直接调第三方 SDK 的底层逻辑

## 4.2 `teaching.py`

这里抽象的是“教学动作”，不是“底层工具”。

两者区别：

- Tool：搜索、抓取、记忆读写、文本处理
- Teaching Function：解释概念、追问理解、生成练习、总结会话

所以这里更像“教学任务目录”，而不是“底层能力目录”。

## 4.3 `skill_tools.py`

这里适合放轻量教学原型：

- 模板化
- 短逻辑
- 易试错

如果某个教学动作逐渐变成：

- 多步检索
- 多轮压缩
- 富媒体生成
- 独立 trace 很重要

那它就该升级到 `shared/infra/skills/`，由 `teaching` 继续定义任务语义和输出契约。

## 4.4 `documents/`

这是当前最能体现“teaching 是任务适配层”的目录。

它不负责：

- 检索
- 模型路由
- 存储
- tracing

它负责：

- 文档总览页
- 章节导读
- glossary
- 学习目标对照
- recap / 本章要点
- 课程模式相关的教学块

这正是“把通用写作结果变成教学文档”的典型任务适配。

---

## 5. 当前最需要明确的约束

## 5.1 `teaching/memory` 不是 canonical memory

当前它更适合作为迁移期 facade。

推荐约束：

- 不再在这里新增底层存储逻辑
- 不再在这里定义新的 runtime path 语义
- 所有新实现统一站到 `app.shared.infra.memory` 之上

## 5.2 `teaching` 不负责造底层接口

不要把下面这些继续塞进 `teaching`：

- retriever 基类
- tool registry
- llm provider
- storage adapter
- sandbox / mcp 入口

这些都属于 `infra`。

## 5.3 `teaching` 负责定义“什么叫更会教”

这才是它真正的中心任务，例如：

- 速成课和系统课的输出差异
- 什么叫合格的章节导读
- 公式解释块和易错点块怎么组织
- examine / profile 的结果如何翻译给学习者

---

## 6. 与 workflows 的关系

`teaching` 不负责 LangGraph 编排。

典型分工：

- `workflows/digest/*` 决定什么时候研究、什么时候写作、什么时候发布
- `shared/infra/skills/*` 决定研究、写作、媒体生成怎样执行
- `teaching/*` 决定结果怎样更像教学内容

例如当前已存在的实际协作：

- `workflows/digest/docgen/publish.py` 调用 `app.teaching.documents.build_document_overview`
- `shared/infra/skills/writer.py` 调用 `app.teaching.documents.ensure_chapter_learning_scaffold`

这正是比较理想的协作方式：

- workflow 编排
- infra 执行
- teaching 适配

---

## 7. 后续建议怎么建设

## 7.1 面向文档

继续沉淀到 `teaching/documents`：

- 课程模式模板
- 例题块
- 易错点块
- 总结块
- 延伸学习块

## 7.2 面向对话

继续沉淀到 `teaching/context` / `teaching.py`：

- 苏格拉底追问
- 陪伴式解释
- 错因追问
- 学习建议

## 7.3 面向诊断闭环

继续让 `teaching` 接住：

- `examine` 的错题诊断
- `profile` 的薄弱点和掌握度变化

然后统一转成：

- 给学生看的解释
- 给文档插入的教学提示
- 给对话系统使用的追问策略

---

## 8. LangSmith 适配建议

Teaching 层新增模块时，建议带这些 metadata：

- `subject`
- `workflow`
- `scene`
- `planner_session_id`
- `confirmed_plan_id`
- `chapter_index`
- `teaching_action`

其中 `teaching_action` 很重要，因为它能明确区分：

- 是章节导读
- 还是错因解释
- 还是 recap
- 还是概念对比

---

## 9. 一句话结论

`teaching` 这一层最重要的价值，不是“再做一套底层能力”，而是：

- 把 `infra` 的能力适配成 AITeachMe 的教学任务
- 把执行结果适配成 AITeachMe 的教学表达
- 把知识文档、练习、画像和对话逐步统一成同一种教学语言
