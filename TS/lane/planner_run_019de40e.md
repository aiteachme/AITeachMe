# Planner 运行复盘：run-019de40e

来源文件：`E:\ChromeDownload\run-019de40e-70bc-7cb2-8fba-4f430ecc2dee.json`

这份导出只有根 run 的 `inputs / outputs / metadata / langsmith`，没有展开子 run。因此这里的“真实发生”以导出的根信息为准，再对照当前 `digest/planner` 代码说明每个阶段应当做了什么。

## 1. 本次输入

本轮是一次新建学习规划：

| 字段 | 值 |
| --- | --- |
| `workflow` | `digest.planner` |
| `lane` | `planner` |
| `planner_operation` | `create` |
| `course_id` | `course_x8iqbgjs81mw` |
| `user_id` | `usr_5e217330381e4abe872c` |
| `planner_session_id` | `cc7318e93d044cc1bc103d46f948edb1` |
| `digest_mode` | `sprint` |
| `model_override` | `deepseek-v4-flash` |
| `requested_file_id_count / file_id_count` | `0 / 0` |
| `message_history_count` | `1` |

用户目标预览：

```text
详细看下这里的这几个文件！！帮我生成一份系统详细的关于这个人工智能课程的教学课！
```

这说明 Planner 本轮主要承担“根据用户目标生成可确认构建方案”的职责。导出里没有具体文件 ID，后续 DocGen run 里才看到实际 15 个 PDF 进入构建。

## 2. 实际流程

```text
create_build_planner_session
  创建 build_planner 会话，记录 digest_mode、model_override 和用户首条消息。
  |
  v
run_build_planner_workflow
  以 planner_session_id 启动 Planner graph。
  |
  v
load_planner_materials
  组装课程、资料摘要、历史知识文档和已有 plan 上下文。
  本次导出没有子 run，无法从 LangSmith 直接看到资料包细节。
  |
  v
stream_brief_and_extract_intent
  面向用户流式输出规划判断，同时内部抽取 plan_intent。
  model_override 已在根 run 出现，说明入口层已经带入首页选择模型。
  |
  v
stream_and_parse_plan_draft
  生成 Markdown 可读规划，并解析隐藏结构化 JSON 为 build_plan_draft。
  |
  v
generate_course_name
  create 分支生成课程展示名和图标 key。
  |
  v
normalize_and_persist_plan
  规范化章节、构建约束和摘要，写入 build_planner 的 ChatSession / ChatMessage。
```

## 3. 输出结果

根 run 输出：

| 字段 | 值 |
| --- | --- |
| `failed` | `false` |
| `error` | 空 |
| `has_plan` | `true` |
| `plan_chapter_count` | `7` |
| `workflow_elapsed_ms` | `39088` |

这表示 Planner 在约 39 秒内成功生成了 7 章方案，并且没有在根 run 层报错。

## 4. 数据写入与交接

Planner 的持久化目标不是 KnowledgeDoc，而是构建规划会话：

| 写入对象 | 本次作用 |
| --- | --- |
| `ChatSession(source="build_planner")` | 保存规划会话、状态、digest_mode、model_override、latest_plan 快照 |
| `ChatMessage(source="build_planner")` | 保存用户输入、assistant 规划输出和结构化 meta |
| confirmed plan | 用户确认后才形成 DocGen 唯一可信合同 |

关键交接字段是 `model_override=deepseek-v4-flash`。本次 Planner 根 run 已带这个字段，说明首页模型选择至少到达了 Planner workflow boundary。后续 DocGen 是否生效，要看 confirmed plan 是否继续携带它。

## 5. 结论

本次 Planner 链路本身是成功的：创建会话、生成 7 章 plan、耗时正常、模型覆盖字段已进入根 run。

真正需要关注的是 trace 可观测性和跨链路传递：

| 问题 | 判断 |
| --- | --- |
| LangSmith 导出没有子 run | 无法单靠这份 JSON 验证每个 Planner 节点的模型参数和 LLM 输入输出 |
| DocGen run 里的 `confirmed_plan.model_override` 为空 | 说明当时 Planner -> confirmed plan -> DocGen 的模型覆盖没有完整落下，或者这份 DocGen run 发生在修复之前 |
| Planner 不应继续加重 | 当前边界合理，后续不要把检索、证据绑定、章节写作放进 Planner |
