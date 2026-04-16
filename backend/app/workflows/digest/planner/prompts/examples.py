"""Few-shot example packs for Planner V3.2."""

from __future__ import annotations


PLAN_SKETCH_EXAMPLES = [
    {
        "label": "sprint_exam_thinking",
        "input": "用户想考前冲刺《高数试题精讲》，本地资料以题目、答案和考点总结为主。",
        "output": """# 思考过程

> 我会先把题目和答案拆成“考点、题型、易错点”三条线，再压缩成冲刺大纲。

## 思考重点
1. 先确认高频考点是否集中在极限、导数和积分这几块
2. 再把反复出现的题型拆成题眼、公式和步骤
3. 最后单独收束易错点，避免只堆答案

## 计划大纲
1. 极限与导数的核心考点
2. 常用公式与速判方法
3. 高频题型的识别与拆解
4. 易错点与考前速查

## 规划假设
- 资料里的题目覆盖面足够，外部检索只用来校准概念边界。

## 待确认点
- 是否需要专门留一章做临考前速查清单？
""",
    },
    {
        "label": "sprint_concept_thinking",
        "input": "用户上传的是零散计算机基础题库，希望快速补基础概念，必要时可用外部资料校准。",
        "output": """# 思考过程

> 我会把题库里的高频术语先归类，再用外部资料校准容易混淆的基础定义。

## 思考重点
1. 先找出题库里重复出现的硬件、软件、存储和输入输出术语
2. 再区分“定义题”和“概念辨析题”分别需要怎么讲
3. 最后把缩写、单位和设备分类整理成速查抓手

## 计划大纲
1. 计算机基础概念速通
2. 系统组成与存储体系
3. 输入输出设备与常见术语
4. 高频易错点与速查清单

## 规划假设
- 题库能提供考查方向，外部检索负责校准标准定义。

## 待确认点
- 是否要更偏“题库刷题导向”，而不是概念讲解导向？
""",
    },
    {
        "label": "systematic_textbook_thinking",
        "input": "用户上传教材和讲义，希望系统学习线性代数。",
        "output": """# 思考过程

> 我会先搭出概念依赖，再把方法和例题放到对应章节里，避免目录只是照抄教材。

## 思考重点
1. 先确认矩阵、方程组、向量空间和线性变换的依赖顺序
2. 再把计算方法和证明思路分别放入最合适的章节
3. 最后处理特征值、对角化这类跨章节综合点

## 计划大纲
1. 线性代数的对象与表示
2. 矩阵与线性方程组
3. 向量空间与基
4. 线性变换与矩阵表示
5. 特征值、特征向量与对角化
6. 方法辨析与综合应用

## 规划假设
- 教材和讲义提供主线，外部检索只用于校准术语和补足缺口。

## 待确认点
- 是否需要单独增加一章专门整理证明思路和易混概念？
""",
    },
    {
        "label": "systematic_mixed_notes_thinking",
        "input": "用户上传零散笔记和课件，希望系统整理计算机网络基础，允许外部资料补齐缺口。",
        "output": """# 思考过程

> 我会先用分层模型搭主线，再用外部资料补足协议机制和交互流程。

## 思考重点
1. 先判断笔记覆盖的是 OSI/TCP-IP 主线还是零散协议点
2. 再补齐寻址、路由、可靠传输和应用层流程之间的关系
3. 最后把常见问题放到对应层级里解释

## 计划大纲
1. 网络分层与核心术语
2. 数据链路与介质访问
3. IP、寻址与路由机制
4. TCP/UDP 与可靠传输
5. 应用层协议与典型流程
6. 网络故障分析与综合场景

## 规划假设
- 本地课件提供结构主线，外部检索负责补足协议细节和标准表述。

## 待确认点
- 是否希望最后加入一章面向考试/面试的高频问答整理？
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
