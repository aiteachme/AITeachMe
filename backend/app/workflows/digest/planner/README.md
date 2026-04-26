# Planner 链路说明

最后更新：2026-04-17

`digest/planner/` 负责在正式生成知识文档前，产出一份用户可确认的构建方案。

当前原则很简单：

- Planner 只理解资料、识别目标、合成计划。
- Planner 不做本地 RAG 检索。
- Planner 不做外部 Web 检索。
- 后续真正写文档时，DocGen 自己决定是否检索。
- Planner 的 `call_purpose + model slot` 分配统一由 `lib/model_policy.py` 维护，节点里不再硬编码模型层级。

## 命名约定

- LangGraph 节点 id：英文 snake_case，和代码定位一致。
- 中文名：只用于文档、LangSmith 展示和前端文案。
- 子步骤：可以有更细的英文名，例如 `stream_planner_brief`，但它不是 LangGraph 节点。

## 当前流程

```text
load_planner_materials              # 读取资料
  -> stream_brief_and_extract_intent # 理解目标
       ├─ stream_planner_brief
       └─ extract_plan_intent
  -> stream_and_parse_plan_draft     # 合成大纲
  -> generate_subject_name           # 并行生成学科名
  -> normalize_and_persist_plan      # 保存方案
```

## 推荐总流程

Planner 的流程直接按下面理解。它只做“确认前规划”，不做本地 RAG 或外部 Web research。

```text
load_planner_materials
  输入：planner_operation / requested_file_uids / file_ids / user_prompt / message_history / latest_plan
    - planner_operation：create / append / generate_only，决定是否读写 planner session。
    - requested_file_uids：用户本轮选择的文件 UID。
    - file_ids：实际进入资料准备的文件 ID。
    - user_prompt：用户本轮学习目标。
    - message_history：Planner 会话历史和修改意见。
    - latest_plan：append 时上一版 plan。
  输出：material_context / digest_mode / selected_file_ids / selected_file_uids / planner_record / planner_turns
    - material_context：资料理解包，包含文件、切片、画像、统计、材料 digest。
    - digest_mode：sprint 或 systematic。
    - selected_file_ids / selected_file_uids：会话绑定的文件选择。
    - planner_record / planner_turns：来自 `chat_session` / `chat_message` 的 Planner 对话快照。
  作用：准备会话、文件选择和资料上下文。正文未解析时可用文件名和目标生成 seed context。

stream_brief_and_extract_intent
  ├─ stream_planner_brief
  │    输入：material_context / user_prompt / digest_mode / message_history
  │    输出：planner_brief
  │      - planner_brief：用户可见的资料边界和思考过程。
  │    作用：流式输出“我理解到什么”，给前端即时可见内容。
  └─ extract_plan_intent
       输入：material_context / user_prompt / digest_mode / message_history
       输出：plan_intent
         - plan_intent：一小段内部规划意图和 3-8 条 plan_queries。
       作用：把用户提示转成后续综合计划用的内部抓手。

stream_and_parse_plan_draft
  输入：material_context / planner_brief / plan_intent / latest_plan / user_prompt / message_history
  输出：plan_outline_markdown / build_plan_draft
    - plan_outline_markdown：给用户看的计划大纲文本。
    - build_plan_draft：从 `<PLAN_JSON>` 解析出的计划说明、动作步骤和章节草稿。
  作用：一次 reason 流式调用，同时生成可见计划说明和机器可解析 JSON 初步大纲。
  内部步骤：
    1. 先流式输出用户可见 Markdown。
    2. 遇到 `<PLAN_JSON>` 后停止向前端透出机器合同。
    3. 解析 `plan_text / plan_steps / chapters`。
    4. 转成待 normalize 的 `chapter_plan`。

normalize_and_persist_plan
  输入：build_plan_draft / material_context / latest_plan / planner_brief / plan_intent / generated_subject_name
  输出：plan / plan_summary / planner_record / planner_turns
    - plan：API、确认接口和 DocGen 消费的最终 plan payload。
    - plan_summary：计划摘要。
    - planner_record / planner_turns：保存到 `chat_session` / `chat_message` 后的会话快照。
  作用：规范化章节数、模式、媒体计划、构建约束；吸收并行标题结果；最后保存 assistant turn。
```

## Planner -> DocGen 交接

用户确认后，Planner 的 `plan` 会冻结成 `confirmed_plan`，DocGen 只消费这份合同。

```text
confirmed_plan
  subject：展示用主题名
  user_prompt：用户学习提示
  digest_mode：sprint / systematic
  chapter_plan：用户确认的章节合同，DocGen 不默认新增、删除、重排
  build_constraints：章节数、目标长度、是否含练习和来源等约束
  plan_summary：方案摘要
  plan_steps：方案动作步骤，给调试、聊天镜像和未来 UI 复用
  selected_file_ids：DocGen 读取资料和检索本地切片的文件范围
  planner_context：Planner 会话摘要、最新大纲、修订次数
  docgen_history_brief：给 DocGen 的精简历史修改意见
```

交接原则：

- Planner 负责确认“学什么、按什么章节学”。
- DocGen 负责决定“每章怎么写、查哪些资料、怎么增强”。
- Planner 不把检索词、来源或证据写死给 DocGen。

## 手写流程图

```mermaid
flowchart TD
    A["读取资料<br/>load_planner_materials"]
    B["理解目标<br/>stream_brief_and_extract_intent"]
    B1["生成可见判断<br/>stream_planner_brief"]
    B2["生成规划抓手<br/>extract_plan_intent"]
    C["合成大纲<br/>stream_and_parse_plan_draft"]
    E["生成学科名<br/>generate_subject_name"]
    D["保存方案<br/>normalize_and_persist_plan"]

    A --> B
    B --> B1
    B --> B2
    B1 --> C
    B2 --> C
    B1 --> E
    B2 --> E
    C --> D
    E --> D
```

## 节点职责

| LangGraph 节点 id | 中文展示名 | 代码定位 | 做什么 |
| --- | --- | --- | --- |
| `load_planner_materials` | 读取资料 | `nodes/load_planner_materials.py` | 读取 Planner 对话会话、文件和历史消息，生成并打包 `DigestMaterialContext` |
| `stream_brief_and_extract_intent` | 理解目标 | `nodes/stream_brief_and_extract_intent.py` | 并行做两件事：流式输出思考过程；生成内部 `plan_intent / plan_queries` |
| `stream_and_parse_plan_draft` | 合成大纲 | `nodes/stream_and_parse_plan_draft.py` | 一次 reason 流式调用，输出可见计划说明和 `<PLAN_JSON>` 初步大纲 |
| `generate_subject_name` | 生成学科名 | `nodes/generate_subject_name.py` | 基于 brief、intent 和资料线索并行生成展示标题 |
| `normalize_and_persist_plan` | 保存方案 | `nodes/normalize_and_persist_plan.py` | 规范化 plan，保存 Planner 对话 session 和 assistant message |

## LLM 调用

一次正常 planner run 有 4 个逻辑 LLM 步骤：

| 顺序 | 步骤 | 模型 | 产物 |
| --- | --- | --- | --- |
| 1 | `stream_planner_brief` | `reason` | 用户可见的思考过程 |
| 2 | `extract_plan_intent` | `primary` | `PlanIntent` |
| 3 | `stream_and_parse_plan_draft` | `reason` | 可见计划说明 + 极简 JSON 初步大纲 |
| 4 | `generate_subject_name` | `light` | 基于可见判断、规划抓手和资料线索生成学科名 |

模型策略来源：`lib/model_policy.py`。这里的 `reason / primary / light` 是逻辑模型槽位，最终 provider 模型名仍由运行时 settings 决定。

## State

核心业务字段只保留：

| 字段 | 作用 |
| --- | --- |
| `material_context` | 资料上下文、切片、主题画像 |
| `planner_brief` | 用户可见的思考过程原文 |
| `plan_intent` | 内部规划意图与 plan_queries |
| `plan_outline_markdown` | 最终合成阶段展示给前端的计划说明 |
| `build_plan_draft` | 由极简 JSON 草稿转成的待 normalize plan |
| `plan` | 对外返回和持久化的最终 plan |

运行时统计保留：

- `prepare_ms`
- `bootstrap_ms`
- `compose_ms`
- `finalize_ms`

## SSE 事件

Planner 当前事件：

- `planner.material.loading`
- `planner.material.pending`
- `planner.material.ready`
- `planner.context.started`
- `planner.context.ready`
- `planner.thinking.started`
- `planner.thinking.failed`
- `planner.thinking.empty`
- `planner.intent.ready`
- `planner.intent.failed`
- `planner.plan.composing`
- `planner.plan.ready`
- `planner.plan.failed`

可见文本增量统一走 `token` SSE；`status` 只承载阶段变化和结构化结果；`done` 表示本次提交结束。
