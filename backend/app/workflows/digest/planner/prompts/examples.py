"""Few-shot example packs for Planner prompts."""

from __future__ import annotations


PLAN_SKETCH_EXAMPLES = [
    {
        "label": "primary_math_resource",
        "input": "用户说“三年级数学”，资料包含教材目录、练习题、易错题和课堂讲义。",
        "output": """这批资料更像小学数学阶段性资源包，不适合按文件顺序整理，而要先把计算、图形、分数时间和应用题分成几条稳定主线。
我会先识别哪些内容是课堂必学概念，哪些是题型训练和易错点，再把每一块压成学生能直接复习的章节抓手。
初步大纲会控制在少数几章里，每章都尽量对应一类学习动作：会算、会换算、会读题、会建模。""",
    },
    {
        "label": "sprint_exam_bank",
        "input": "用户想考前冲刺高数，资料是历年题、答案解析和公式速记。",
        "output": """这批资料重点不是系统铺开教材，而是从题目里反推高频考点和得分路径。
我会先把题目按极限、导数、积分、级数和综合应用归簇，再看每一簇常用公式、题眼变化和最容易错的计算步骤。
初步大纲会以“题型识别—公式使用—易错修正”为核心，不把每套试卷机械拆成章节。""",
    },
    {
        "label": "systematic_textbook",
        "input": "用户上传线性代数教材和课堂笔记，希望系统学习。",
        "output": """这组资料明显有前后依赖，不能只按考点碎片化处理。
我会先建立对象主线：矩阵、方程组、向量空间、线性变换和特征值，再把证明、计算和应用放到对应章节里。
初步大纲会更像系统课程目录，每章先讲概念边界，再讲方法成立条件，最后落到例题和迁移。""",
    },
]


COMPOSER_EXAMPLES = [
    {
        "label": "小学数学资源",
        "plan_text": "本计划以三年级数学核心考点为主线，分四章推进：先稳住口算与竖式计算，再梳理图形和单位换算，随后处理分数与时间初步，最后集中训练应用题读题和建模。每章都保留典型题型与易错点，方便后续继续按课堂或家庭复习目标调整。",
        "chapters": [
            {
                "title": "口算与竖式计算",
                "key_points": ["三位数加减法竖式计算（含进位与退位）", "乘法口诀快速应用（1~9×1~9）", "常见口算错误归因与纠正"],
            },
            {
                "title": "图形与单位换算",
                "key_points": ["长方形、正方形周长公式及应用", "元角分、厘米米之间的单位换算", "图形特征辨识与测量单位选择"],
            },
            {
                "title": "分数与时间初步",
                "key_points": ["分数的初步认识（如 1/2、1/4 的含义）", "钟面读写与时间间隔计算", "生活情境中的时间表达与推算"],
            },
            {
                "title": "应用题解题路径",
                "key_points": ["审题关键词识别（如一共、多少、还剩）", "列表建模与数量关系图构建", "数形结合解决实际问题"],
            },
        ],
    },
    {
        "label": "考前冲刺题库",
        "plan_text": "本计划按题型簇而不是试卷顺序组织内容，先提炼高频题眼，再把公式适用条件、解题步骤和易错环节放到同一章里。初步大纲会聚焦最容易提分的题型，后续可以继续按考试范围删减或加深。",
        "chapters": [
            {
                "title": "极限与连续题眼",
                "key_points": ["等价无穷小与洛必达适用条件", "分段函数连续性判断", "常见极限变式的第一步选择"],
            },
            {
                "title": "导数与单调性应用",
                "key_points": ["导数定义与几何意义", "单调区间和极值判断", "切线方程与参数题常见坑"],
            },
            {
                "title": "积分计算与面积模型",
                "key_points": ["换元积分和分部积分选择", "定积分几何意义", "面积/体积应用题建模"],
            },
        ],
    },
    {
        "label": "系统教材讲义",
        "plan_text": "本计划按概念依赖关系组织课程，先建立基础对象和符号，再推进到方法、定理和应用。初步大纲不会照搬教材目录，而会把相邻知识合并成更适合学习的模块，后续可以按课时或考试重点继续调整。",
        "chapters": [
            {
                "title": "矩阵对象与基本运算",
                "key_points": ["矩阵的定义、行列结构与记号", "加法、数乘、乘法的成立条件", "初等变换和等价关系"],
            },
            {
                "title": "方程组与秩",
                "key_points": ["线性方程组的矩阵表示", "秩与解的存在唯一性", "消元法的步骤和边界条件"],
            },
            {
                "title": "向量空间与线性相关",
                "key_points": ["向量组、张成空间和基", "线性相关/无关判断", "维数与坐标表示"],
            },
            {
                "title": "特征值与对角化",
                "key_points": ["特征值和特征向量定义", "相似矩阵与对角化条件", "典型计算题和应用解释"],
            },
        ],
    },
]


def render_plan_sketch_examples() -> str:
    blocks: list[str] = []
    for index, item in enumerate(PLAN_SKETCH_EXAMPLES, start=1):
        blocks.append(
            f"示例 {index}：{item['label']}\n"
            f"输入场景：{item['input']}\n"
            f"目标输出：\n{item['output']}"
        )
    return "\n\n".join(blocks)


def render_composer_examples() -> str:
    blocks: list[str] = []
    for index, item in enumerate(COMPOSER_EXAMPLES, start=1):
        chapters = "\n".join(
            f"  - {chapter['title']}：{'；'.join(chapter['key_points'])}"
            for chapter in item["chapters"]
        )
        blocks.append(
            f"示例 {index}：{item['label']}\n"
            f"plan_text：{item['plan_text']}\n"
            f"chapters：\n{chapters}"
        )
    return "\n\n".join(blocks)


__all__ = ["render_composer_examples", "render_plan_sketch_examples"]
