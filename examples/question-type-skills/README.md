# 题型 Skill 示例包

这里保存六个统一采用 `aiteachme.question-skill/v2` 的 `.atqskill` 示例包源码。所有包使用 `generic_text_form_v2`，题型差异由字段、提示词、参考案例和评分规则表达：

- `feynman_explanation`：费曼解释题
- `oral_defense`：结构化答辩题
- `scenario_interview`：情境面试题
- `argument_debate`：结构化辩论题
- `experiment_design`：实验设计题（四字段）
- `case_analysis`：案例分析题（短文本建议、长文本论证）

费曼题是一个长文本字段；其他示例是多个字段。全部支持修改字段 key、数量、顺序、显示名称和长度，并共用现有生成与评分链路。费曼题通过 `generation_constraints.numbered_task_count: 4` 声明四项编号任务，任何新题型都可使用相同约束。

六个当前包的题型版本均为 `2.0.0`。包格式 `schema`、题型 `version` 和执行能力的版本号相互独立；`structured_subjective_v1`、`structured_text_v1`、`rubric_llm_v1` 继续代表已发布的执行能力。

已有 V1 题型可以导入相同 `package_key` 的新版本升级，旧试卷仍使用冻结旧版本。原四个 V1 源码和发布包保存在 `backend/tests/fixtures/question_type_packages/v1/` 作为兼容测试资料，不出现在默认示例列表。下载接口用 `example_id` 区分示例，旧的带 `_v1` / `_v2` 下载地址兼容解析到最新示例。

创建独立题型时，复制任一示例并使用新的 `package_key`；更新已有题型时保留 `package_key` 并增加 `version`。不要用同一个题型版本覆盖不同内容。

示例目录不是运行时插件，包内也没有可执行代码。使用 `aiteachme` Conda 环境构建：

```powershell
conda run -n aiteachme python backend/scripts/build_atqskill_examples.py --output <目标目录>
```

生成的 `.atqskill` 是确定性 ZIP；相同源码应生成相同文件和规范化 SHA-256。发行使用的示例资源位于 `backend/app/workflows/support/question_type_packages/example_packages/`，由此构建脚本生成；个人试验包不要混入源码示例目录。
