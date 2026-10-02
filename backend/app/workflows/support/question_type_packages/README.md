# Question Type Packages

最后更新：2026-09-29

职责：定义、校验、编译并安装用户提供的声明式 `.atqskill` 题型包。

这里的 `SKILL.md` 是产品内部合同，不是 Codex Skill，也不会注册到代理运行时。

```text
.atqskill ZIP
  -> archive safety checks
  -> restricted SKILL.md parsing
  -> JSON Schema and semantic validation
  -> version-frozen CompiledQuestionTypeDefinition
  -> explicit course-scoped installation
```

## 文件

```text
archive.py    # 有界读取、安全路径校验、确定性打包
parser.py     # 受限 YAML Frontmatter 与 JSON 解析
validator.py  # Schema、跨字段、prompt、案例、工具、图片校验
compiler.py   # 无 I/O 的不可变编译结果组装
contracts.py  # 限制、错误合同和编译模型
installer.py  # 暂存、幂等安装、不可变版本与公开目录
schemas/      # 服务端权威 JSON Schema
example_packages/ # 随服务端发布的六个 V2 通用文本示例包
```

## 当前边界

P1 已提供课程级上传、公开预览、确认安装、版本切换、归档、受保护资源和示例下载。上传暂存有效期为 24 小时，安装版本不可变；完整编译结果只保存在服务端。每课程最多 10 个待确认导入、20 个上传题型、每题型 10 个版本，题型图片资源合计最多 100 MB；账号待确认导入最多 20 个。

P2 已接通 `feynman_explanation_v1` 的单次长文本出题与 rubric 判分，可用于题库、闯关、测验、考卷和 PDF。随后补齐了同一 `structured_subjective_v1` / `rubric_llm_v1` 能力对结构化文本字段的通用适配，V1 的答辩、面试和辩论包与 V2 文本表单包都复用这条能力链；安装器仍按运行时、渲染器、评分器和必需工具的实际可用性决定状态。

当前六个默认示例全部使用 V2 `generic_text_form_v2`，支持自由文本字段和字段化参考案例，共用同一个编译定义和生成/评分链路。固定 V1 协议身份集中在 `shared/kernel/question_type_compatibility.py`，历史费曼生成规则集中在 `examine/question_types/legacy.py`。V2 题干编号数通过 `generation_constraints.numbered_task_count` 声明，与题型名称无关。

四个原 V1 源码及发布包保存在 `tests/fixtures/question_type_packages/v1/` 进行字节一致性和升级兼容测试。导入同一 `package_key` 的 `2.0.0` 示例会创建新版本；既有题目继续使用原快照。新下载合同使用 `example_id`，旧下载地址和已弃用的响应 `template_key` 字段仅作客户端兼容。

本 support 模块只负责安全校验、安装和版本目录，不直接执行 LLM，也绝不运行包内代码。实际生成和判分分别由 `examine/question_build` 与 `examine/exam_grade` 使用不可变编译快照完成。

`PackageValidationResult.compiled_definition` 含有完整提示词，只能供服务端安装流程使用。上传预览和课程目录均剔除完整编译结果、prompt 与参考答案，只返回公开元数据、错误、警告和包哈希。
