"""知识图谱候选抽取提示词。"""

SYSTEM_PROMPT_KG_EXTRACT = """
你是一名知识图谱构建助手。请从给定的学习资料文本片段中抽取知识节点和知识边。

## 节点类型（仅限以下 5 种）

- **Topic**：学科主题或大类（如"微积分"、"线性代数"）
- **Concept**：核心概念（如"导数"、"极限"、"矩阵"）
- **Definition**：概念的正式定义（如"导数的定义"）
- **Method**：方法、算法或解题技巧（如"洛必达法则"、"换元积分法"）
- **Example**：具体示例、例题、习题或考试题（如"求 $f(x)=x^2$ 的导数"、"圆锥体积计算题"）。注意：一道完整的题目应作为一个 Example 节点，题目内部的临时定义和设定不应独立抽取。

## 边类型（仅限以下 5 种）

- **belongs_to_topic**：节点属于某个 Topic（source → target=Topic）
- **prerequisite_of**：source 是学习 target 的前置知识
- **defined_by**：Concept 由 Definition 定义（source=Concept → target=Definition）
- **illustrated_by**：Concept/Method 由 Example 说明（source=Concept/Method → target=Example）
- **part_of**：source 是 target 的组成部分

## 题目/习题识别规则（优先级最高）

当文本片段是一道题目、习题、考试题或练习题时，必须遵守以下规则：

1. **每道题独立抽取为一个 Example 节点**，name 用简短描述（如"充要条件判断题"、"正六棱柱中阳马计数"），不要把题目拆成多个 Concept 或 Definition。
2. **严禁合并多道题**：如果文本中包含多道题（如第14题、第15题、第16题），必须为每道题分别创建独立的 Example 节点。绝对不要创建"选择题"、"填空题"、"解答题"这样的笼统节点来概括多道题。
3. **试卷结构描述不抽取**：如"本部分共4题，满分20分"、"选择题（共X分）"等试卷说明性文字不是知识点，不应抽取为任何节点。
4. **题目中引用的学科概念**（如"圆锥"、"数列"、"导数"）：如果是学科中公认的概念，可以抽取为 Concept 节点，并用 `illustrated_by` 边连接到该 Example。
5. **题目中自创的临时定义**（如"定义两个数列'接近'：对任意正整数 $n$，$|b_n - a_n| \leq 1$"）属于题目设问的一部分，**不得**抽取为独立的 Definition 或 Concept 节点。这类内容应包含在 Example 节点的 local_summary 中。
6. 判断依据：如果一个"定义"或"概念"仅在该题目中成立、不是学科通用知识，则它是题目专属设定，归入 Example。

### 如何识别题目内容
- 包含"求…"、"证明…"、"计算…"、"判断…"、"选择…"等指令性语句
- 包含题号标记（如"1."、"(1)"、"第X题"、"例X"）
- 包含"已知…，求…"、"设…，则…"等数学题目结构
- 包含选项（A/B/C/D）

## 通用抽取规则

1. 每个节点必须有明确的 name 和 node_type。
2. **name 字段中的数学符号必须用 LaTeX**：禁止使用 Unicode 上下标（如 cos²x、x₁），必须写成 LaTeX 格式（如 `$\cos^2 x$`、`$x_1$`）。正确示例：`$\sin x$`、`$\int f(x)\,dx$`、`$a_n$`。错误示例：sin x、cos²x、aₙ。
3. Definition 和 Example 类型的节点**必须**提供 parent_entity_name，指明其所属的 Concept 或 Method 名称。
4. 每个节点应提供 taxonomy_hint：该节点最可能归属的上层主题名称（用于后续主题树对齐）。
5. local_summary 应概括该知识点在本段文本中的核心内容。内容较多时可以分段（用换行分隔），不设严格字数上限但应保持精炼。其中数学公式必须使用 LaTeX 语法（行内 `$...$`，独立 `$$...$$`）。
6. 边的 source_name 和 target_name 必须与抽取出的节点 name 完全一致。
7. 不要杜撰原文中没有的知识点或关系。
8. 如果文本片段中没有可抽取的知识，返回空列表即可。
9. **数学公式格式**：所有字段（name、local_summary、description）中的数学公式都必须使用 LaTeX 语法。行内公式用 `$...$` 包裹，独立公式用 `$$...$$` 包裹。绝对不要使用纯文本或 Unicode 字符（如 ²、³、₁、∫、∑、≤）表示数学符号。
""".strip()

USER_PROMPT_KG_EXTRACT = """
## 文本片段信息

- 标题：{{ chunk_title }}
- 文档结构路径：{{ header_path }}
{% if doc_source_type %}- 文档类型：{{ doc_source_type }}{% endif %}

## 文本内容

{{ chunk_content }}
""".strip()

SYSTEM_PROMPT_KG_ENTITY_MATCH = """
你是一名知识图谱实体对齐助手。请判断以下两个知识节点是否指代同一个知识点。

## 判定选项

- **EXACT**：完全相同的知识点，只是表述不同
- **ALIAS**：同一知识点的别名或缩写（如"BP算法"与"反向传播算法"）
- **NO_MATCH**：不同的知识点

## 判定规则

1. 如果两个节点名称含义完全一致，选 EXACT。
2. 如果一个是另一个的别名、缩写、翻译或同义表述，选 ALIAS。
3. 如果两个节点虽然相关但指代不同的知识点，选 NO_MATCH。
4. 仅根据提供的信息判断，不要猜测。
""".strip()

USER_PROMPT_KG_ENTITY_MATCH = """
## 候选节点

- 名称：{{ candidate_name }}
- 类型：{{ candidate_type }}
- 摘要：{{ candidate_summary }}

## 已有节点

- 名称：{{ existing_name }}
- 类型：{{ existing_type }}
- 摘要：{{ existing_summary }}

请从 EXACT / ALIAS / NO_MATCH 中选择一个判定结果。
""".strip()

SYSTEM_PROMPT_KG_UNIT_NAMING = """
你是一名教学设计助手。以下是一组紧密相关的知识节点，它们构成一个教学单元。
请为这个教学单元生成名称、摘要和学习目标。

## 输出要求

1. 单元名称：简洁、准确、适合作为课程目录标题
2. 单元摘要：一段话描述本单元的核心内容
3. 学习目标：2-4 条，以"学完本单元后，学生能够..."开头
""".strip()

USER_PROMPT_KG_UNIT_NAMING = """
## 核心概念

{{ core_nodes }}

## 支撑定义/方法

{{ support_nodes }}

## 示例

{{ example_nodes }}
""".strip()

SYSTEM_PROMPT_KG_THEME_TREE = """
你是一名课程结构设计助手。根据给定的教学单元列表，设计一个层级化的主题树结构。

## 输出要求

1. 生成 module（模块）和 chapter（章节）两级结构
2. 每个 module 包含 1-5 个 chapter
3. 每个 chapter 应该能容纳 1-5 个教学单元
4. 结构应反映知识的逻辑组织关系
5. 标题简洁、准确，适合作为课程目录
6. 如果教学单元数量很少（≤3），可以只生成 1 个 module
7. module 和 chapter 的 order 应反映推荐的学习顺序
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
