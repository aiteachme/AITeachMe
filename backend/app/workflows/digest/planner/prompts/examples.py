"""Few-shot example packs for Planner."""

from __future__ import annotations


PLAN_SKETCH_EXAMPLES = [
    {
        "label": "sprint_exam_thinking",
        "input": "用户想考前冲刺《高数试题精讲》，本地资料以题目、答案和考点总结为主。",
        "output": """1. 关注重点：极限、导数、积分的高频考点；题眼和公式步骤；变式题迁移；公式适用条件；易错点收束。
2. 预计计划大纲：极限与导数核心考点；常用公式与速判方法；高频题型拆解；积分计算路径；综合变式抓手；考前速查。
""",
    },
    {
        "label": "sprint_concept_thinking",
        "input": "用户上传的是零散计算机基础题库，希望快速补基础概念，必要时可用外部资料校准。",
        "output": """1. 关注重点：硬件软件术语；定义题和概念辨析题；CPU、字长、ROM/RAM；单位换算和编码表示；缩写与设备分类。
2. 预计计划大纲：计算机基础概念；运算基础；存储体系；输入输出设备；数据表示与编码；安全和启动常识；易错速查。
""",
    },
    {
        "label": "systematic_textbook_thinking",
        "input": "用户上传教材和讲义，希望系统学习线性代数。",
        "output": """1. 关注重点：矩阵和方程组依赖；向量空间和线性变换；行列式、秩、解空间关系；特征值和对角化；证明思路与易混边界。
2. 预计计划大纲：对象与表示；矩阵与方程组；向量空间与基；行列式和秩；线性变换；特征值对角化；证明辨析；综合应用。
""",
    },
    {
        "label": "systematic_mixed_notes_thinking",
        "input": "用户上传零散笔记和课件，希望系统整理计算机网络基础，允许外部资料补齐缺口。",
        "output": """1. 关注重点：OSI/TCP-IP 分层主线；寻址、路由和可靠传输；IP、端口、DNS、HTTP；TCP 连接管理；跨层故障场景。
2. 预计计划大纲：网络分层术语；数据链路；IP 寻址路由；TCP/UDP；DNS 和 HTTP；拥塞重传；故障排查；跨层综合。
""",
    },
]


COMPOSER_EXAMPLES = [
    {
        "label": "sprint_exam_contract",
        "summary": "冲刺型计划里章节少而聚焦，标题要像真实讲义目录，研究任务和 search_queries 要能直接驱动后续写作。",
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
        "summary": "当本地资料不完整时，计划里要明确哪些章节依赖外部校准，但标题和任务不能出现来源名。",
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
