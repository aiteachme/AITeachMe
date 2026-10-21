"""Prompt builder for source-image teaching evidence."""

from __future__ import annotations

from app.schemas.llm import ChatMessage
from app.workflows.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.docgen_multimodal.lib.models import MaterialImageOccurrence

VISUAL_EVIDENCE_PROMPT_VERSION = "visual-evidence-v4"
VISUAL_EVIDENCE_DETAIL = "high"


def build_visual_evidence_messages(
    occurrences: list[MaterialImageOccurrence],
) -> list[ChatMessage]:
    """Build one ordered multimodal request for a bounded image batch."""

    system_prompt = """
你是 AITeachMe 的教学资料图片理解器。你的任务不是描述所有图片，而是先判断图片是否对教学内容有意义，再只为有意义的图片提取可复用证据。

“有意义”表示图片本身承载了可以帮助理解、讲解、练习或复习资料正文的知识，例如：流程图、结构图、架构图、统计图、曲线图、几何图、公式图、知识表格、用于教学操作的关键界面截图、与正文知识直接相关的照片或示意图。

“无意义”表示图片不承载教学知识，例如：教材或文档封面、Logo、页眉页脚装饰、分隔线、背景、头像、水印、广告、社交按钮、与正文无关的 UI、解析器产生的重复页面缩略图或纯装饰素材。

必须遵守：
1. 每张图片只能对应输入中已经给出的 image_id，不得编造或改写 ID。
2. 对无意义图片，只返回 image_id 和 is_meaningful=false；不要输出摘要、事实、文字、公式、概念、置信度或其它证据字段。
3. 对有意义图片，is_meaningful=true，并提取图片直接表达的知识。附近正文只用于理解语境，不能把正文内容冒充为图片事实。
4. 看不清的文字、数值、公式、箭头或标注必须写入 uncertainty_notes，禁止猜测。
5. summary 要说明图片对教学的核心价值，不要写“这是一张图片”之类空话。
6. extracted_text 只保留对教学有用的可见文字，不做无关 OCR 全量转录。
7. teaching_value 和 confidence 使用 0.0 到 1.0。
8. detail_loss_risk 表示把图片仅转成文字摘要后丢失关键细节的风险，只能是 low、medium、high。
9. visual_type 只能使用 schema 允许的枚举值。
10. 有意义不等于需要复读。Writer 会先获得本次图片理解的简短概述和有限条关键事实，不能假定完整转录都会原样进入 Writer；只有这种精简证据仍不足以可靠讲解关键知识时，才考虑再次提供原图。reread_recommended 默认 false，不确定也设为 false；不得为凑数量保留复读图片。
11. 对每张有意义图片填写 reread_assessment，分别检查：knowledge_scope 是 common（通用知识）、source_specific（资料独有知识）还是 uncertain；text_coverage 是 covered（所属 Section 原始正文已表达具体知识）、missing（确实缺少）还是 uncertain；original_required 表示精简文字证据是否仍不足、确实需要 Writer 看原图。只有 source_specific、missing、original_required=true 同时成立，才能建议复读。独有性和覆盖判断都针对具体知识，不能只判断整张图的主题；正文提到模型名称、宏观流程、图号、图片链接或笼统图注，不等于覆盖图中特有的连接、方向、条件及数据。本次新提取的图片事实也不属于原始正文。缺少正文只能说明无法核对，不能自动证明图片有独有知识。
12. 判断独有性要回答“缺失的具体知识是什么，为什么不能靠通用知识还原”。常见结构的配色、排版、标签位置、符号命名、标准定义和分类不算独有知识。即使正文没有描述，标准 Transformer、普通滑动窗口（包括 step=1）、运行时环境分类思维导图、常规复合求积节点图、只标 R_A/R_B 的同轴电容器图，也应归为 common，不复读。不能仅以“图中特有”“对应关系没写”“摘要可能丢细节”“图很复杂”作为理由。
13. 可以考虑复读的是资料专有且重要的实验数值关系、新公式的非通用约束、自定义架构连接/扫描方向、具体题目不可替代的几何条件等。必须先把能读出的知识写入本次证据；少量数值、单个参数、简单箭头关系若已能被精简文字证据准确完整表达，则 original_required=false。密集数据的联合对照、专有结构中多条扫描路径与门控/残差/跨尺度分支的协同关系，若原文没有逐项解释、简短证据也不能完整保留，才设 true。只列出模块名称不等于还原具体拓扑；熟悉通用 Mamba/Transformer 原理不等于知道该资料的新增架构。普通教学配图和非关键的局部视觉细节不满足条件。
14. missing_knowledge 写出正文缺少的具体数值、公式、约束或连接；没有则写空字符串。original_required=true 时 original_required_reason 指出本次文字证据仍无法可靠保留的关键关系，不能只重复“正文没写”。reread_recommended=true 时 reread_reason 简要合并这两点；否则 reread_reason=""。判断依据必须来自可读原图和提供的正文，不得虚构数据或将看不清当作复读理由。不要另生成一份复读证据。
15. 只返回符合结构化 schema 的结果。
""".strip()

    content: list[dict] = [
        {
            "type": "text",
            "text": (
                f"请按输入顺序判断下面 {len(occurrences)} 张资料图片。"
                "每张图前的文字给出稳定 ID、来源 Section 和附近正文，紧随其后的就是该 ID 对应的原图。"
            ),
        }
    ]
    included_sections: set[tuple[str, str]] = set()
    for occurrence in occurrences:
        section_key = (occurrence.file_id, occurrence.section_ref)
        section_context = (
            "所属 Section 完整正文（用于核对图中知识是否已由正文表达）：\n"
            + (occurrence.section_text or occurrence.nearby_text or "（无可用正文）")
            if section_key not in included_sections
            else "所属 Section 完整正文：与本请求此前相同文件及 Section 的正文一致。"
        )
        included_sections.add(section_key)
        content.extend(
            [
                {
                    "type": "text",
                    "text": "\n".join(
                        [
                            f"[IMAGE_BEGIN image_id={occurrence.image_id}]",
                            f"来源文件：{occurrence.source_filename}",
                            f"Section：{occurrence.section_ref}",
                            f"Section 标题：{occurrence.section_title or '未命名'}",
                            f"页码：{occurrence.page_number or '未知'}",
                            f"图片文件：{occurrence.asset_filename}",
                            f"Markdown alt：{occurrence.alt_text or '无'}",
                            section_context,
                            "图片附近正文：",
                            occurrence.nearby_text or "（无可用附近正文）",
                        ]
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": occurrence.data_url,
                        "detail": VISUAL_EVIDENCE_DETAIL,
                    },
                },
                {
                    "type": "text",
                    "text": f"[IMAGE_END image_id={occurrence.image_id}]",
                },
            ]
        )

    messages: list[ChatMessage] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content},
    ]
    return trace_prompt_build(
        "docgen_multimodal_visual_evidence",
        inputs={
            "prompt_version": VISUAL_EVIDENCE_PROMPT_VERSION,
            "detail": VISUAL_EVIDENCE_DETAIL,
            "image_ids": [item.image_id for item in occurrences],
            "image_count": len(occurrences),
            "section_refs": list(dict.fromkeys(item.section_ref for item in occurrences)),
        },
        output=messages,
    )


__all__ = [
    "VISUAL_EVIDENCE_DETAIL",
    "VISUAL_EVIDENCE_PROMPT_VERSION",
    "build_visual_evidence_messages",
]
