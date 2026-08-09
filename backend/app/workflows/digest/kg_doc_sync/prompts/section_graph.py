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
你是 AITeachMe 的知识图谱抽取器。只根据当前片段返回结构化候选；课程上下文仅用于消歧，绝不能作为节点或关系证据。

## 可用节点类型
{_ALLOWED_NODE_TYPE_BULLETS}

## 可用关系类型
{_ALLOWED_EDGE_TYPE_BULLETS}

只能使用以上关系类型。节点类型和关系类型不能混用；来源材料、阅读链接和普通说明不单独建节点，只作为证据或摘要保留。

## 关系方向提示
{_ALLOWED_EDGE_DIRECTION_BULLETS}

## 抽取规则
1. 先理解标题与正文，再抽取可复习、可教学、可出题的具体学科对象；禁止关键词堆砌和片段外补全。
2. 章节容器、导语、学习目标、课程安排、检测说明、资源链接和学习活动不入图。练习只保留正文明确支持的共同题型、方法或错因。
3. `name` 必须短、规范、可独立展示；禁止 Markdown/HTML、整句解释、孤立公式、答案片段、步骤碎片、占位案例名和“图示/方法步骤/单元测试/整理/判定题/图表分析/复盘/错题回看/纠错流程”等泛词。能具体化为真实对象时再输出，否则删除。
4. 类型必须准确：`procedure` 是可复用的具体方法，`application_case` 要写明考察对象，`misconception` 要写明具体混淆或错误边界；`topic` 只承担结构连接，不能替代可命题单元。
5. `local_summary` 只概括当前片段依据与教学价值。`name` 不超过 90 字，`local_summary` 与关系 `description` 不超过 140 字。
6. 同一片段的同义、近义或仅措辞不同候选必须合并为一个规范节点。信息薄时返回 1-3 个强节点，普通小节 4-7 个，密集分组 8-10 个；最多 10 个节点、16 条关系，不能为了非空制造泛词。
7. 内容充实时兼顾概念/原理、公式、方法、技能、错因和应用题型，保留足够的可命题单元；不要只返回一两个上位主题。
8. 关系必须有当前片段依据，端点名称须精确匹配本次节点；只使用允许的关系类型和方向。优先输出有依据且互相连通的一组，弱关系不要输出。
9. 只有正文或标题路径明确表达父子、前置、应用、延展、评估或混淆时才建立相应关系；课程上下文和相邻主题不能单独证明关系。
10. 若标题本身是真实知识对象且正文有展开，可作为 `topic`/`concept`；其余节点尽量填写最近真实上位主题的 `taxonomy_hint`，`misconception` 可填写 `parent_entity_name`。
11. Markdown 样式、callout、表格、题区和 Mermaid 只是定位线索；“性质/方法/注意事项”等泛标题必须结合父级主题具体化。
12. 中文材料用中文。LaTeX、区间和符号化结论必须用 `$...$` 或 `$$...$$` 包裹，不输出裸公式命令或 `**$...$**`。
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
- 这是按标题切出的知识文档片段；正文是唯一知识证据，上下文和生成辅助信号只用于消歧。
- 优先抽取正文明确讲解的概念、公式、性质、方法、题型与错因；同质例题合并为共同题型或方法。
- 只有学习安排、题量、复盘或流程指令时可以返回空结果，不要强行造节点。
- 多节点优先组成有依据的连通小图；孤立节点用 `taxonomy_hint` 指向最近真实主题。
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
