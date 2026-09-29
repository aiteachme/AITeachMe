# AITeachMe 题型 Skill 包 V2（通用文本表单）

状态：当前新建题型和六个官方示例统一使用本协议。已接入 V1 兼容、单/多字段生成、自动评分、展示、混合选择与按类型补题。更新：2026-09-29。先前功能验收见 [P4 记录](../development/question-type-p4-review.md)，本次统一见 [统一记录](../development/question-type-unification-20260929.md)。

V2 是唯一推荐的题型编写协议；V1 仅用于读取旧包和旧数据。两种输入均编译成同一个 `CompiledQuestionTypeDefinition`，共用单次主观题执行链路。V1 的原合同、包哈希和历史冻结定义保持不变。

## V2 当前范围

V2 包使用：

```yaml
schema: aiteachme.question-skill/v2
template_key: generic_text_form_v2
runtime_key: structured_subjective_v1
renderer_key: structured_text_v1
grader_key: rubric_llm_v1
```

题型作者可以自由定义 1–8 个 `short_text` / `long_text` 字段，包括字段 key、显示名称、顺序、是否必填、长度限制和占位文案。key 匹配 `[a-z][a-z0-9_]{1,31}`，不得重复；各字段最大长度之和不得超过 20,000。评分维度、权重、Prompt、参考案例和工具仍然必须通过声明式清单引用。

可选的题干结构约束：

```yaml
generation_constraints:
  numbered_task_count: 4
```

`numbered_task_count` 是 1–8 的整数。声明后，生成题干必须包含恰好指定数量、由空行分隔的 `(1)` 至 `(N)` 编号任务。平台向模型传递约束并在保存前校验，失败沿现有生成重试流程处理。具体教学内容和顺序由包内提示词指定；此能力不依赖包名，也不允许包提供可执行校验代码。省略时不强制任务数量。

包格式 `schema`、题型内容版本 `version` 与 runtime/renderer/grader 的能力版本各自独立，通用包继续使用已发布的 `*_v1` 执行能力。

V2 仍然禁止包内代码执行、任意前端组件、任意 Provider 配置和多轮会话。上传包的 `profile_eligible` 固定为 `false`，不能自行打开；混合试卷的自定义题成绩也不进入长期掌握度。

## 兼容规则

- V1 继续使用 `atqskill-v1.schema.json`，不得通过 V2 规则重新解释旧包。
- V2 使用独立 Schema 和参考案例 Schema。
- 编译后的定义仍然使用同一份 `CompiledQuestionTypeDefinition`，由 `schema_version` 区分协议版本。
- 题型版本、包哈希、课程归属和试卷快照继续由服务端冻结。
- V2 包只有在运行时、Renderer、grader 和必需工具均可用时才会进入训练配置；当前 `structured_text_v1` 已支持字段式文本作答。

## 多字段数据合同

多字段参考答案必须保存为字段映射，例如：

```json
{
  "hypothesis": "可检验的假设",
  "procedure": "按顺序执行步骤",
  "controls": "保持其他变量一致",
  "interpretation": "根据结果判断假设"
}
```

生成时依据冻结字段构造结构化输出约束，返回后再验证必填字段、文本类型和长度。多字段参考答案不得为空或折叠进第一个字段。V2 参考案例的 `question.reference_answer` 和 `answers[].content` 同样按字段校验。

学生的空字符串表示未作答，可以随整卷提交；整卷请求省略某道题时，服务端也将其全部字段按未作答处理。非空文本必须满足字段长度。显式提交的对象缺少必填 key、包含未知 key 或非文本值，属于格式错误。闯关前端要求补齐必填字段后逐题提交。模型结构/证据校验最终失败属于评分失败，不能计成答错或零分。

多字段评分证据使用 `{"field_key":"controls","quote":"学生原文"}`，每条引用独立定位，允许同一评分维度引用不同字段。兼容旧的 `evidence: string[]` 加维度级 `field_key`；单字段旧题可省略定位。服务端检验引用、保存字段标签、计算加权总分和通过结果；正分必须有证据，零分不要求编造引用。

前端草稿、提交和存储均保留字段映射。测验、考卷、闯关共用 `QuestionAnswerFields`，按冻结定义的标签和顺序展示。`.atmx` 继续沿原同步链路保存定义、参考答案、学生答案及版本引用。

评分权重的舍入容差、提示词变量的阶段来源及同次反馈规则沿用 [V1 的运行说明](atqskill-v1.md#提示词变量)。

## 题型选择与数量

新接口使用 `question_type_selections`，例如总题量为 6 时：

```json
[
  {"question_type":"single_choice","count":2},
  {"registry_id":101,"version_id":501,"count":2},
  {"registry_id":102,"count":2}
]
```

这里的 ID 仅作示例。每项选择一个内置题型或课程注册项；`version_id` 仅适用于注册项。服务端校验课程归属、启用状态、版本对应关系和真实能力，再冻结实际版本。

- 不得与非空的旧 `question_types` / `question_type_registry_ids` 同时提交。
- 旧字段继续兼容，也支持显式的内置/上传类型组合；不是把两类题型互斥。
- 新列表允许内置题与多个上传题；同一题型不能重复选择多个版本。
- `count` 要么全部省略，要么全部给出且总和等于总题量。省略时均衡分配，余数按列表顺序分配；题量不得少于类型数。
- 网页配置支持多选并采用均衡分配；指定版本和精确配额由接口支持。
- 生成配置及缓存包含冻结版本、包哈希与数量；补题计算各类型缺口，不能用其他类型的富余题目抵扣。
- 空选择继续使用内置自动搭配。闯关每轮重新准备符合当前版本的题库，保留一次性训练语义。

## 当前验收示例

`examples/question-type-skills/` 下的费曼、答辩、面试、辩论、实验设计、案例分析六个示例均使用本协议。题型身份使用稳定 `package_key`；示例列表和下载使用 `example_id`。四个旧示例以相同题型身份发布 `2.0.0` 新版本，安装升级不修改历史版本或试卷。旧包源码和原始发布文件保存在 `backend/tests/fixtures/question_type_packages/v1/`，用于兼容回归。

兼容层保留 V1 固定字段合同和历史费曼生成规则。新题型的单/多字段参考答案采用字段映射；展示文本从同一份字段数据生成。不要把 V1 的整段多字段参考说明机械塞入首字段：维护新版本案例时需提供相应字段答案，并保留原有参考说明。参考答案及强、部分正确、错误案例均需通过字段长度和类型校验。

## LLM 接口边界

题型运行时可以依赖 `app.workflows.examine.question_types.llm.llm()` 作为单次模型调用入口。它只是现有 `acompletion_with_fallback` 的薄适配，不重复实现重试、超时、限流、模型路由或批量调度；批量工作仍使用平台的 `run_llm_tasks`。
