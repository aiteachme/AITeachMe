"""Few-shot example packs for Planner."""

from __future__ import annotations


PLAN_SKETCH_EXAMPLES = [
    {
        "label": "sprint_exam_thinking",
        "input": "用户想考前冲刺《高数试题精讲》，本地资料以题目、答案和考点总结为主。",
        "output": """这批资料更像考前题目和考点包，先按极限、导数、积分的题型簇拆开，不照题号流水账。
大纲会围绕题眼、公式适用条件、常见变式和易错步骤组织，每章尽量压成“考点判断 + 例题路径 + 易错速查”。
""",
    },
    {
        "label": "sprint_concept_thinking",
        "input": "用户上传的是零散计算机基础题库，希望快速补基础概念，必要时可用外部资料校准。",
        "output": """这份资料是计算机基础选择题题库，主线集中在硬件/软件术语、CPU、ROM/RAM、单位换算、编码和设备分类。
大纲会按“概念辨析 + 题型识别”收束：系统组成、存储体系、编码表示、输入输出、安全启动，最后做易错速查。
""",
    },
    {
        "label": "systematic_textbook_thinking",
        "input": "用户上传教材和讲义，希望系统学习线性代数。",
        "output": """这组资料更像教材加讲义，线性代数需要按依赖关系走，不能只挑零散考点。
章节会从对象与表示开始，再到矩阵方程组、向量空间、行列式与秩、线性变换、特征值对角化，最后补证明辨析和综合应用。
""",
    },
    {
        "label": "systematic_mixed_notes_thinking",
        "input": "用户上传零散笔记和课件，希望系统整理计算机网络基础，允许外部资料补齐缺口。",
        "output": """这些笔记和课件比较零散，先用 OSI/TCP-IP 分层把边界理顺，再放回寻址、路由、可靠传输、DNS、HTTP 和 TCP 连接管理。
大纲会按分层术语、数据链路、IP 路由、TCP/UDP、DNS/HTTP、拥塞重传和故障排查组织，缺口再用外部资料校准。
""",
    },
]


COMPOSER_EXAMPLES = [
    {
        "label": "sprint_exam_contract",
        "summary": "冲刺型计划里章节少而聚焦，标题要像真实讲义目录，key_points 要落到考点、题型和易错步骤。",
    },
    {
        "label": "sprint_concept_contract",
        "summary": "概念补基础的冲刺计划要先对齐定义，再连接题型和易错点，不要只有刷题口号。",
    },
    {
        "label": "systematic_textbook_contract",
        "summary": "系统型计划要体现知识主线、依赖关系、方法结构和应用，不要只是把目录原样抄出来。",
    },
    {
        "label": "systematic_mixed_contract",
        "summary": "当资料比较零散时，计划要先建立章节主线，不要把文件名、来源名或检索动作写进章节标题。",
    },
]


def render_plan_sketch_examples() -> str:
    blocks: list[str] = []
    for index, item in enumerate(PLAN_SKETCH_EXAMPLES, start=1):
        blocks.append(
            f"示例 {index}\n"
            f"输入场景：{item['input']}\n"
            f"目标输出：\n{item['output']}"
        )
    return "\n\n".join(blocks)


def render_composer_examples() -> str:
    return "\n".join(
        f"- {item['label']}：{item['summary']}"
        for item in COMPOSER_EXAMPLES
    )


__all__ = ["render_composer_examples", "render_plan_sketch_examples"]
