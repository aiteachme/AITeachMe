"""Prompts for DocGen static HTML figure generation."""

from __future__ import annotations

from typing import Any

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.docgen.lib.mode_profiles import get_docgen_mode_profile


def build_static_html_figure_selection_messages(
    *,
    chapter_title: str,
    digest_mode: str,
    candidates: list[dict[str, Any]],
    max_assets: int,
) -> list[dict[str, str]]:
    mode_label = get_docgen_mode_profile(digest_mode).prompt_label
    candidate_lines: list[str] = []
    for item in candidates:
        candidate_lines.append(
            "\n".join(
                [
                    f"候选 {item.get('index')}: {item.get('title')}",
                    f"片段：{item.get('context')}",
                ]
            )
        )
    system_prompt = """
你是 AITeachMe 的教学图示触发判断器。
本阶段只判断“哪些章节片段值得生成示意图”，不要输出 FigureSpec，不要画图。
可以一个都不选；宁可不生成，也不要为了凑数量选择没有教学增量的片段。
判断标准由语义决定：图必须帮助学生看见正文不容易直观把握的空间、数量、状态、结构、几何、坐标、路径、装置或易混关系。
示意图必须有“示例作用”：能落到一个具体物体、变量、数据、几何对象、状态转移、实验装置或错误情境上。
选择前先问自己：图里具体会出现哪些对象？它们之间有什么位置、方向、流向、层级、状态变化或数量关系？如果只能回答一组术语或几句定义，就不要选择。
不要按学科关键词、标题词或固定模板选择；只看片段里是否真的有可视化能显著降低理解成本的关系。
如果最合适的是可调参数仿真、动态图、长流程操作或真实图片，不要塞进静态图，也不要放入 selected。
如果学习目标是观察“连续变化、拖动参数、实时反馈、可调实验、多步操作过程”，静态图通常只有单一截面，不要选择。
不要选择：术语定义、分类枚举、纯文字对比、可直接用正文讲清的公式推导、没有具体对象的学习目标。
人文社科也可以选择，但必须有具体关系可画，例如角色网络、权力/信息流向、叙事时间线、论证结构或案例状态变化。
输出只包含 JSON 对象，格式为 {"selected":[{"index":1,"visual_kind":"static_svg","figure_goal":"图要讲清什么","example_seed":"具体例子对象","figure_type":"problem_diagram","reason":"为什么值得画"}]}。
selected 最多保留 max_assets 个；不值得画时输出 {"selected":[]}。
""".strip()
    candidates_text = "\n\n".join(candidate_lines) if candidate_lines else "无"
    prompt = f"""
请从下面候选片段中选择最多 {max_assets} 个真正值得生成静态教学示意图的位置。

章节标题：{chapter_title}
文档模式：{mode_label}

候选片段：
{candidates_text}

输出要求：
1. 只做触发判断，不生成图元。
2. figure_goal 写成一句具体图示目标，方便下一步 FigureSpec 生成。
3. example_seed 写清图里要出现的具体例子，例如“物体从 x1 到 x2 的位移”“a,b,sum 三个变量格”“三角形 ABC 的角关系”。
4. 只有能用一张静态 SVG 讲清的片段才放入 selected，visual_kind 使用 static_svg。
5. 只是术语解释、定义记忆或纯正文说明时，selected 返回空数组。
6. 如果没有任何片段需要示意图，selected 返回空数组。
7. 只输出 JSON 对象。
""".strip()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "docgen_static_html_figure_selection",
        inputs={
            "chapter_title": chapter_title,
            "digest_mode": digest_mode,
            "candidate_count": len(candidates),
            "max_assets": max_assets,
        },
        output=messages,
    )


def build_static_html_figure_messages(
    *,
    figure_title: str,
    figure_goal: str,
    figure_type: str,
    digest_mode: str,
    section_context: str,
    example_seed: str = "",
) -> list[dict[str, str]]:
    mode_label = get_docgen_mode_profile(digest_mode).prompt_label
    system_prompt = """
你是通用教学演示图规划器。先判断章节片段是否真的需要图，再输出 JSON FigureSpec；后端会把它渲染成单张 SVG。
输出内容只包含 JSON 对象，不要输出原始 HTML/SVG。
图必须来自章节片段，source_refs 摘录原文短语；图内只放必要短标签。
图要像课堂板书里的“例子图”，不是正文摘要的装饰图。
只有当图能展示文字难以直观看出的空间、数量、状态、结构、几何或坐标关系时，才生成 elements。
用图元表达几何、坐标、结构、路径、区域、网络、程序状态或关键误区等可视关系。
不要按关键词套模板，不要填 layout.template；layout 通常留空。
内部按两步完成：先基于片段判断“是否值得画”，再把最有教学增量的具体例子排成清晰 SVG 图元。
图必须承担明确学习任务，并能让学生看到仅靠正文不容易把握的关系。
如果你判断这段不需要示意图，返回 elements: []。
不要复刻正文截图、不要把整段代码或长句排进图里。
不要把“公式三步展开”“概念词排列”“一条箭头配几个标签”当作图；这些适合正文或高亮，不适合 sidecar 图。

可用图元：
- axis/curve/point/line/vector/shape/label/callout/step/formula/relation/table_row
- 坐标字段 x/y/x2/y2 均为 0-100
- 关系图、步骤图、状态图优先给 shape 设置短 id，再用 line/vector 的 from_id/to_id 连接；这类图可以少填坐标
- shape_type: ellipse/circle/rectangle/triangle/polygon/angle/arc/region
- polygon/triangle/region 用 points: [[x,y],...]
- ellipse 用 rx/ry；angle/arc 用 start_angle/end_angle
图型选择：
- 有实际图示价值时，优先使用 problem_diagram，并使用 axis/curve/point/line/vector/shape 等视觉图元。
- 由你判断是否需要图、需要哪类图；不要为了凑数量改用 process_steps、formula_derivation 或 concept_map。
- mistake_card 只在你判断能画出明确纠错路径或易混结构时使用。
布局要求：
- 元素 4-8 个为宜，最多 9 个；标签最多 7 个。
- 标签必须很短：中文不超过 8 个字，英文/代码不超过 12 个字符。
- 尽量把文字放在 shape/vector/point 自身的 label 中，少用独立 label/callout。
- 标签必须使用片段中的真实对象/量/角色名称；不要给中文标签追加 A/B/C/D 编号，不要使用“节点1/对象A”等无来源占位符。
- 坐标要分散覆盖画布中部，不要挤在中心，也不要贴边。
- 标签之间至少错开 10 个坐标单位，避免相互覆盖。
- 如果要比较两条关系（如轨迹 vs 位移、计划 vs 执行、表层 vs 深层），不要画在同一条线上；用曲线/区域/上下分层让差异一眼可见。

参考示例，不要照抄内容，只学习表达方式：
- 状态变化：用几个 rectangle 表示状态格，用 vector 表示更新方向，用短标签标出变量/值。
- 步骤路径：用 3-4 个 shape 表示动作节点，用 vector 串联，箭头标签只写关键动作。
- 坐标趋势：用两条 axis、一条 curve、一个 point 或 tangent line 表示关系，不写长解释。
- 关系不清：如果只能列概念词，没有空间/方向/数量/状态关系，返回 elements: []。
""".strip()

    prompt = f"""
请为下面章节片段规划一张教学辅助图，只输出 JSON FigureSpec。

图示标题：{figure_title}
图示判断目标：{figure_goal or "请自行判断这段是否值得生成演示图；不值得就返回空 elements。"}
具体例子种子：{example_seed or "如片段没有具体例子，请自行从片段事实中抽取；抽不出来就返回空 elements。"}
候选策略：{figure_type}
文档模式：{mode_label}

章节片段：
{section_context}

生成要求：
1. 先由模型判断是否值得画；不值得时返回 elements: []，不要勉强生成。
2. 值得画时只画一个关键例子图；elements 必须表达非纯文本的视觉关系，例如变量格位置、指针指向、坐标趋势、几何角度、区域关系、数量结构。
3. 画流程/关系/状态时，优先使用短 id 与 from_id/to_id；不要用随机方框模拟截图。
4. 标签要短，布局要留白；不要依赖后端模板或关键词规则。
5. 如果你判断图没有教学增量，就返回空 elements。
6. 不要使用 layout.template，不要要求外部图片、Canvas、脚本或 Manim；只输出后端 SVG 图元能渲染的静态图。
7. 输出为一个 JSON 对象。
""".strip()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "docgen_static_html_figure",
        inputs={
            "figure_title": figure_title,
            "digest_mode": digest_mode,
            "context_chars": len(section_context),
        },
        output=messages,
    )


__all__ = ["build_static_html_figure_messages", "build_static_html_figure_selection_messages"]
