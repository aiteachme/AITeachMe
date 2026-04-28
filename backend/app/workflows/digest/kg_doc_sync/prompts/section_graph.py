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

只能使用以上关系类型。`remark` 是节点类型，不是关系类型；注意事项、提醒、易错点与方法或概念之间的关系通常用 `application`，如果是在区分易混点则用 `contrast`。

## 关系方向提示
{_ALLOWED_EDGE_DIRECTION_BULLETS}

## 抽取规则
1. 优先抽取可复用的学术知识单元，不抽取临时措辞。
2. 名称要短、规范、适合展示；数学符号需要时使用 LaTeX。
3. `local_summary` 只能概括当前片段实际说了什么。
4. 关系端点必须精确匹配本次返回的节点名称。
5. 不要编造当前片段没有依据的节点或关系。
6. 使用 Knowledge Unit 粒度：一个定义、一个公式、一个推导步骤、一个例题、一个方法步骤，通常就是合适的单元。
7. 不要为整章、整节、阅读导语、容器标题建节点，除非标题本身就是一个原子概念。
8. 宁可返回 1-3 个强节点，也不要返回一堆弱节点；本片段最多返回 8 个节点、10 条关系，不要把同一小节拆成大量近义主题壳。
9. 严格拒绝教学包装语，例如学习目标、章节大纲、复习口号、任务指令、题干句；只抽取明确可复用的概念、定义、公式、性质、方法、例题或证明步骤。
10. `edge_type` 严禁使用节点类型或自造词，例如 `remark`、`support`、`related`、`contains`；遇到无法归类的弱关系可以不返回。
11. 本次只负责候选抽取；不要考虑数据库去重、跨章节合并或旧节点废弃，这些由后续 persist 节点处理。
12. 为前端可视化服务：节点名称尽量短而规范，过长标题要压缩成核心术语或简短公式。
13. `local_summary` 要说明这个节点在当前片段里的教学价值，例如定义了什么、解决什么、依赖什么或容易错在哪里，不要只复述节点名。
14. 关系优先表达“前置依赖、组成结构、公式适用、方法步骤、例题验证、易错对比”，不要为了连线而创造泛泛关系。
15. `name` 不超过 90 个字符；`local_summary` 和 `description` 不超过 140 个字符。输出越短越稳定。

## 层级规则
1. 如果片段标题本身是一个真实概念或主题，且正文不是纯流程噪声，可以包含这个概念。
2. 对 `definition`、`formula`、`theorem`、`example`、`exercise`、`proof_step`、`remark`，当上位概念或方法清楚时填写 `parent_entity_name`。
3. 对 `concept` 和 `method`，能判断最近上位概念时填写 `taxonomy_hint`。

## 知识文档片段规则
当来源是结构化知识文档小节时：
1. 标题和正文要一起看，不能只看标题。
2. 严格遵守 KU 粒度：章节/小节容器通常不是 KU；原子定义、公式、性质、证明步骤、例题、方法步骤通常是 KU。
3. 如果正文包含解释、性质、公式、方法、例题或注意事项，要显式抽出对应节点。
4. 如果出现 `定义:`、`公式:`、`例题:`、`Remark:` 等标注行，要转成相应类型节点，不要轻易返回空结果。
5. 如果标题是“几何意义”“性质”“方法”“注意事项”等泛化词，要结合父级主题生成限定后的原子单元，不要单独返回泛化标题。
6. 当片段只有学习目标、大纲、复盘清单、口号、题干或流程指令时，可以返回空结果。
7. 高质量稀疏图优先于用标题、任务句填充出来的非空图。
""".strip()

USER_PROMPT_KNOWLEDGE_EXTRACT = """
## 片段元数据
- 标题：{{ chunk_title }}
- 标题路径：{{ header_path }}
{% if doc_source_type %}- 来源类型：{{ doc_source_type }}{% endif %}
{% if subject_context %}- 学科上下文：{{ subject_context }}{% endif %}
{% if sibling_topics %}- 相邻主题：{{ sibling_topics }}{% endif %}
{% if digest_mode == "sprint" %}- 讲义模式：sprint，优先识别方法、题型和常见错误。{% endif %}
{% if digest_mode == "systematic" %}- 讲义模式：systematic，优先识别完整概念、严谨定义和前置依赖。{% endif %}

{% if doc_source_type == "knowledge_doc_markdown" %}
## 本片段特别要求
- 这是按标题切出的知识文档片段。
- 必须结合标题和正文判断。
- 学科上下文和 DocGen 辅助信号只用于消歧、确定范围和提醒重点，不能作为创建节点或关系的证据。
- 如果正文是解释性内容，而不是纯题目或流程指令，不要轻易返回空结果。
- 如果片段描述含义、公式、性质、方法、例题或注意事项，要显式抽取。
- 优先返回 KU 质量的原子单元，不要返回宽泛的小节包装。
- 如果正文有表格、提示块或加粗重点，优先检查其中是否包含可复用定义、条件、结论、易错点或方法步骤。
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
