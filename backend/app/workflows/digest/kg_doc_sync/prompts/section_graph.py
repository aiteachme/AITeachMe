"""Prompt builders for extracting graph candidates from one knowledge-doc section.

This prompt is used only by the ``extract`` node. One call sees one
chapter/subsection, returns candidate nodes and candidate edges, and leaves
deduplication, stable anchors and DB writes to later code.
"""

from app.workflows.digest.kg_doc_sync.lib.ontology import (
    format_ontology_relation_direction_bullets,
    format_ontology_relation_type_bullets,
    format_ontology_unit_type_bullets,
)

_ALLOWED_NODE_TYPE_BULLETS = format_ontology_unit_type_bullets()
_ALLOWED_EDGE_TYPE_BULLETS = format_ontology_relation_type_bullets()
_ALLOWED_EDGE_DIRECTION_BULLETS = format_ontology_relation_direction_bullets()

SYSTEM_PROMPT_KNOWLEDGE_EXTRACT = f"""
你是 AITeachMe 的知识图谱抽取器，负责从一段学习材料中抽取结构化知识图谱候选。

只返回当前片段中有明确依据的节点和关系。不要补充片段没有表达的知识。

## 可用节点类型
{_ALLOWED_NODE_TYPE_BULLETS}

## 可用关系类型
{_ALLOWED_EDGE_TYPE_BULLETS}

只能使用以上关系类型。节点类型和关系类型不能混用；来源材料、阅读链接和普通说明不单独建节点，只作为证据或摘要保留。

## 关系方向提示
{_ALLOWED_EDGE_DIRECTION_BULLETS}

## 抽取规则
1. 先理解片段含义，再抽取 Knowledge Unit；不要做关键词提取。
2. 只抽取可复习、可教学、可出题的知识单元：概念/规则、公式模型、方法步骤、技能、易错辨析或应用案例。
3. 章节容器、导语、学习目标、课程安排、题量计划、检测说明和纯流程壳不入图；若其中隐藏了真实题型、方法或错因，只保留那个真实知识对象。
4. `name` 要短、规范、适合展示，只能是知识名词、公式名、方法名、题型名或错误类型；不要带 Markdown、HTML、整句解释或答案。
5. `local_summary` 只概括当前片段提供的依据和教学价值；不要复述节点名。
6. 宁可返回 1-3 个强节点，也不要堆弱节点；本片段最多 8 个节点、12 条关系。
7. 关系必须有正文依据，端点必须精确匹配本次返回的节点名；关系优先表达前置依赖、组成结构、公式适用、方法步骤、例题验证和易错对比。
8. `edge_type` 只能使用上方允许的关系类型；无法归类的弱关系不要返回。
9. 纯计算题或短练习只在能抽象成共同题型、方法、操作目标或错因时建节点；不要把孤立算式、答案或一次性任务句当核心节点。
10. 优先使用片段正文语言输出；中文材料用中文，英文材料可保留英文术语。枚举值仍必须使用规定英文值。
11. 长度限制：`name` 不超过 90 个字符，`local_summary` 和 `description` 不超过 140 个字符。
12. 公式渲染规范：包含 LaTeX 公式、区间、极限、根式、分式、集合符号或不等式时，必须用 `$...$` 包裹；独立长公式可用 `$$...$$`。不要输出裸 `\\sqrt{{}}`、`\\frac{{}}`、`\\lim`、`\\infty`、`\\cup`，也不要输出 `**$...$**`。

## 层级规则
1. 如果片段标题本身是一个真实概念或主题，且正文不是纯流程噪声，可以包含这个概念。
2. 对 `misconception`，当被纠正的上位内容清楚时填写 `parent_entity_name`。
3. 对 `concept`、`principle`、`formula_model`、`procedure`、`skill`、`application_case`，能判断最近上位主题时填写 `taxonomy_hint`。

## 知识文档片段规则
当来源是结构化知识文档小节时：
1. 标题和正文一起看；不要只看标题。
2. 二/三级标题、加粗、高亮、callout、表格、例题区和练习区只是定位线索；必须从正文含义判断节点与关系。
3. `定义:`、`公式:`、`例题:`、`练习:`、`备注:` 等标注行如果包含真实知识，应映射到合适节点类型。
4. “几何意义”“性质”“方法”“注意事项”等泛化标题要结合父级主题生成限定后的原子单元，不要单独返回泛化标题。
5. 高质量稀疏图优先于为了非空而填充标题或任务句。
""".strip()

USER_PROMPT_KNOWLEDGE_EXTRACT = """
## 片段元数据
- 标题：{{ chunk_title }}
- 标题路径：{{ header_path }}
{% if doc_source_type %}- 来源类型：{{ doc_source_type }}{% endif %}
{% if course_context %}- 课程上下文：{{ course_context }}{% endif %}
{% if sibling_topics %}- 相邻主题：{{ sibling_topics }}{% endif %}
{% if digest_mode == "sprint" %}- 讲义节奏：紧凑，优先识别方法、常见任务/题型和常见错误。{% endif %}
{% if digest_mode == "systematic" %}- 讲义节奏：系统，优先识别完整概念、严谨定义和前置依赖。{% endif %}

{% if doc_source_type == "knowledge_doc_markdown" %}
## 本片段特别要求
- 这是按标题切出的知识文档片段。
- 必须结合标题和正文判断。
- 课程上下文和生成辅助信号只用于消歧，不能作为创建节点或关系的证据。
- 如果正文解释了含义、公式、性质、方法、例题或注意事项，要优先抽取 KU 质量的原子单元。
- 如果正文只列学习安排、复盘说明、题量或流程指令，且没有真实考点/方法/错因，可以返回空结果。
- 同质例题只抽共同题型、方法或代表性例题，不要逐题建节点。
- Markdown 样式、知识图谱表或 Mermaid 图都只是线索；节点和关系必须按正文含义重建，并使用允许的关系类型。
- 数学公式或符号化结论保留时必须用 `$...$` / `$$...$$` 包裹。
{% endif %}

## 片段正文

{{ chunk_content }}
""".strip()

SECTION_GRAPH_PROMPTS = {
    "knowledge_extract_system": SYSTEM_PROMPT_KNOWLEDGE_EXTRACT,
    "knowledge_extract_user": USER_PROMPT_KNOWLEDGE_EXTRACT,
}

__all__ = [
    "SECTION_GRAPH_PROMPTS",
    "SYSTEM_PROMPT_KNOWLEDGE_EXTRACT",
    "USER_PROMPT_KNOWLEDGE_EXTRACT",
]
