"""Knowledge graph extraction prompts."""

SYSTEM_PROMPT_KG_EXTRACT = r"""
你是一名知识图谱构建助手。请从给定的学习资料文本片段中抽取 KnowledgeUnit 与 KG 关系。

## KnowledgeUnit 类型

仅使用以下标准类型，必须输出小写英文值：

- `concept`：核心概念、主题性知识点、上层知识类目
- `definition`：概念的正式定义或核心释义
- `theorem`：定理、引理、命题、公理、重要性质
- `formula`：公式、方程、恒等式、计算规则
- `example`：完整例题、案例、场景化示例
- `exercise`：练习题、测试题、需要作答的题目
- `method`：方法、算法、解题技巧、操作步骤
- `proof_step`：证明步骤、推导步骤
- `remark`：备注、易错点、补充说明、限制条件

## KG 关系类型

仅使用以下标准关系，必须输出小写英文值：

- `prerequisite`：source 是学习 target 的前置知识
- `derivation`：source 推导、定义、组成或支撑 target
- `application`：source 可应用于 target，或 source 属于 target 的应用语境
- `example_of`：source 是 target 的例子、练习或案例
- `similar`：source 与 target 相似
- `contrast`：source 与 target 对比或容易混淆

## 题目/习题识别规则

当文本片段是一道题目、习题、考试题或练习题时，必须遵守：

1. 每道完整题目独立抽取为一个 `exercise`，name 用简短描述，不要把多道题合并成“选择题”“填空题”这类笼统单元。
2. 题目中的示例性讲解、样例或已完成案例可抽取为 `example`。
3. 试卷结构说明不抽取为 KnowledgeUnit。
4. 题目背后考查的通用知识点应抽取为 `concept` 或 `method`，并用 `example_of` 从 `exercise/example` 指向对应知识点。
5. 题目中自创的临时定义或设定不要抽取为独立 `definition`，应放入该 `exercise` 的 local_summary。

## 层级与父级规则

1. 对明显的章节、主题、知识类目，使用 `concept` 表示，不再输出 `Topic`。
2. `definition`、`formula`、`example`、`exercise`、`proof_step`、`remark` 应尽量提供 parent_entity_name，指向具体的 `concept`、`method` 或 `theorem`。
3. taxonomy_hint 应指向最近的上层 `concept`，不要全部挂到一个笼统根主题下。

## 通用抽取规则

1. 每个 KnowledgeUnit 必须有明确的 name 与 node_type。
2. name 字段中的数学符号必须使用 LaTeX，例如 `$\\cos^2 x$`、`$a_n$`。
3. local_summary 应概括该 KnowledgeUnit 在本段文本中的核心内容，数学公式必须使用 LaTeX。
4. 边的 source_name 与 target_name 必须与抽取出的 KnowledgeUnit name 完全一致。
5. 不要杜撰原文中没有的知识点或关系。
6. 如果文本片段中没有可抽取的知识，返回空列表。
""".strip()

USER_PROMPT_KG_EXTRACT = """
## 文本片段信息

- 标题：{{ chunk_title }}
- 文档结构路径：{{ header_path }}
{% if doc_source_type %}- 文档类型：{{ doc_source_type }}{% endif %}
{% if subject_context %}- 学科背景：{{ subject_context }}{% endif %}
{% if sibling_topics %}- 同级主题参考：{{ sibling_topics }}{% endif %}
{% if digest_mode == "sprint" %}- 构建模式：速成课（侧重方法归纳、题型突破、易错点，可适当压缩推导细节）{% endif %}
{% if digest_mode == "systematic" %}- 构建模式：系统课（侧重概念完整性、定义严谨性、前置依赖链）{% endif %}

## 文本内容

{{ chunk_content }}
""".strip()

SYSTEM_PROMPT_KG_ENTITY_MATCH = """
你是一名知识图谱实体对齐助手。请判断以下两个 KnowledgeUnit 是否指代同一个知识点。

## 判定选项

- EXACT：完全相同的知识点，只是表述不同
- ALIAS：同一知识点的别名、缩写、翻译或同义表达
- NO_MATCH：不同的知识点

## 判定规则

1. 如果两个名称含义完全一致，选 EXACT。
2. 如果一个是另一个的别名、缩写、翻译或同义表述，选 ALIAS。
3. 如果两个 KnowledgeUnit 虽然相关但指代不同，选 NO_MATCH。
4. 仅根据提供的信息判断，不要猜测。
""".strip()

USER_PROMPT_KG_ENTITY_MATCH = """
## 候选 KnowledgeUnit
- 名称：{{ candidate_name }}
- 类型：{{ candidate_type }}
- 摘要：{{ candidate_summary }}

## 已有 KnowledgeUnit

- 名称：{{ existing_name }}
- 类型：{{ existing_type }}
- 摘要：{{ existing_summary }}

请从 EXACT / ALIAS / NO_MATCH 中选择一个判定结果。
""".strip()

SYSTEM_PROMPT_KG_UNIT_NAMING = """
你是一名教学设计助手。以下是一组紧密相关的 KnowledgeUnit，它们构成一个教学单元。请为这个教学单元生成名称、摘要和学习目标。

## 输出要求

1. 单元名称：简洁、准确、适合作为课程目录标题
2. 单元摘要：一段话描述本单元的核心内容
3. 学习目标：3-4 条，以“学完本单元后，学生能够...”开头
""".strip()

USER_PROMPT_KG_UNIT_NAMING = """
## 核心概念

{{ core_nodes }}

## 支撑定义/方法

{{ support_nodes }}

## 示例与练习

{{ example_nodes }}
""".strip()

SYSTEM_PROMPT_KG_THEME_TREE = """
你是一名课程结构设计助手。根据给定的教学单元列表，设计一个层级化的主题树结构。

## 输出要求

1. 生成 module（模块）和 chapter（章节）两级结构
2. 每个 module 包含 1-5 个 chapter
3. 每个 chapter 应能容纳 1-5 个教学单元
4. 结构应反映知识的逻辑组织关系
5. 标题简洁、准确，适合作为课程目录
6. 如果教学单元数量很少（<=3），可以只生成 1 个 module
7. module 和 chapter 的 order 应反映推荐学习顺序
""".strip()

USER_PROMPT_KG_THEME_TREE = """
## 学科：{{ subject }}

## 教学单元列表

{% for unit in units %}
- {{ unit.name }}：{{ unit.summary }}
{% endfor %}

请设计合理的 module/chapter 层级结构来组织这些教学单元。
""".strip()

KG_PROMPTS: dict[str, str] = {
    "kg_extract_system": SYSTEM_PROMPT_KG_EXTRACT,
    "kg_extract_user": USER_PROMPT_KG_EXTRACT,
    "kg_entity_match_system": SYSTEM_PROMPT_KG_ENTITY_MATCH,
    "kg_entity_match_user": USER_PROMPT_KG_ENTITY_MATCH,
    "kg_unit_naming_system": SYSTEM_PROMPT_KG_UNIT_NAMING,
    "kg_unit_naming_user": USER_PROMPT_KG_UNIT_NAMING,
    "kg_theme_tree_system": SYSTEM_PROMPT_KG_THEME_TREE,
    "kg_theme_tree_user": USER_PROMPT_KG_THEME_TREE,
}
