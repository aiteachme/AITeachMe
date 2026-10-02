# AITeachMe 题型 Skill 包 V1 规范

最后更新：2026-09-29

本规范现在仅用于旧包和历史数据兼容。新建题型及六个官方示例统一使用 [V2 通用文本表单](atqskill-v2.md)。原四个 V1 示例源码与发布文件保存在 `backend/tests/fixtures/question_type_packages/v1/`，不再作为默认下载示例。

`.atqskill` 是一个声明式 ZIP 包，用于描述一种可被 AITeachMe 编译的课程题型。本规范定义文件合同和安全校验；课程页面已提供导入接口，但题型能否用于训练取决于服务端是否已发布对应运行能力。

这里的 `SKILL.md` 是 AITeachMe 项目内的题型描述文件，与 Codex Skill/插件无关，不会被代理框架直接发现或执行。

## 设计边界

- 一个包只定义一个题型。
- `SKILL.md` Frontmatter 是清单，正文仅供人阅读。
- 出题、判分、反馈提示词必须通过 `files` 显式引用。
- 包只能选择系统允许的 runtime、renderer、grader 和 tool ID。
- 包内 Python、JavaScript、HTML、SVG、二进制程序和嵌套压缩包一律拒绝。
- 包不能声明 `source`、`is_system`、用户、课程、状态或存储位置。
- V1 只支持单题单次提交，不支持多轮会话。

## 目录合同

```text
SKILL.md
prompts/generate.md
prompts/grade.md
prompts/feedback.md       # 可选
references/cases.json
tools/bindings.json       # 可选
assets/*                  # 可选，仅 PNG/JPEG/WebP
```

包内路径必须是 ASCII 小写目录和文件名（根文件 `SKILL.md` 除外）、使用 `/`、Unicode NFC、最长 240 字符且目录深度不超过五层。未被清单引用的文件会导致校验失败。

## 权威 Schema

- [`atqskill-v1.schema.json`](../../backend/app/workflows/support/question_type_packages/schemas/atqskill-v1.schema.json)
- [`reference-cases-v1.schema.json`](../../backend/app/workflows/support/question_type_packages/schemas/reference-cases-v1.schema.json)
- [`tool-bindings-v1.schema.json`](../../backend/app/workflows/support/question_type_packages/schemas/tool-bindings-v1.schema.json)

Schema 使用 JSON Schema Draft 2020-12。Frontmatter 通过受限 YAML 解析为 JSON 对象后执行 Schema 校验；所有对象均禁止未知字段。

## 固定运行时

| 模板 | Renderer | 用途 |
| --- | --- | --- |
| `feynman_explanation_v1` | `long_text_v1` | 费曼式概念解释 |
| `oral_defense_v1` | `structured_text_v1` | 结论、依据、边界答辩 |
| `scenario_interview_v1` | `structured_text_v1` | 情境分析与面试作答 |
| `argument_debate_v1` | `structured_text_v1` | 立场、论据与反驳 |

当前四个 V1 模板均已接入生成、文本作答和评分链路；安装器仍检查实际运行能力和必需工具。真实模型出题与评分质量另行验收。

所有模板固定使用 `structured_subjective_v1` 和 `rubric_llm_v1`，并且必须同时支持 `question_bank`、`mastery_drill`、`web_practice`、`paper_exam`、`pdf`。每种模板的字段 key 和顺序固定，显示名称、占位文案、长度、提示词和评分维度可以定制；所有字段的 `max_length` 合计不得超过 20000。

## 提示词变量

只允许 `${course_name}`、`${course_description}`、`${knowledge_units}`、`${difficulty}`、`${answer_schema}`、`${rubric}`、`${reference_examples}`。不支持 Jinja、动态 include、环境变量和自定义 system role。

出题阶段从课程上下文、冻结定义和本题要求注入变量。评分和反馈阶段使用课程名、本题难度、冻结作答结构、rubric 和参考案例；此时 `course_description` 为 `""`、`knowledge_units` 为 `[]`，不重新读取可变课程内容。实际评分依据由题干、参考答案和学生回答提供。

可选 `feedback.md` 与 `grade.md` 在同一次评分请求中生效，仅控制 `feedback_text` 的表达，不改变维度分数、证据要求或通过阈值。

评分权重总和允许最多 `0.001` 的舍入误差。运行时在这个范围内按总和归一化计算成绩，冻结的包定义和题目快照保持原值。

## 安全限制

| 项目 | 上限 |
| --- | ---: |
| 压缩包 | 8 MB |
| 解压后总量 | 24 MB |
| 文件数 | 100 |
| 单文件 | 4 MB |
| `SKILL.md` / 单个 prompt | 32 KB |
| 参考案例 | 256 KB |
| 图片最长边 / 总像素 | 4096 px / 1600 万 |
| 压缩比 | 100:1 |

禁止绝对路径、`..`、反斜杠、Windows 保留名称、控制字符、大小写冲突路径、符号链接、特殊文件、加密 ZIP 和动画图片。校验过程不执行磁盘解压，不调用 LLM，也不运行任何包内容。

## 编译与完整性

编译器把清单、提示词、案例、工具绑定和资源元数据收口为版本冻结的 `CompiledQuestionTypeDefinition`。包哈希按排序后的规范化路径和内容计算，不依赖 ZIP 条目顺序、时间戳或操作系统换行符。

```powershell
conda run -n aiteachme python backend/scripts/build_atqskill_examples.py --output <目录>
conda run -n aiteachme python backend/scripts/validate_atqskill.py <文件.atqskill>
```
