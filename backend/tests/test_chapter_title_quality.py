from app.workflows.digest.common.pedagogy import clean_generated_chapter_title
from app.workflows.digest.planner.lib.plans import normalize_planner_draft
from app.workflows.digest.docgen.prompts.title_lock import build_title_lock_messages


def test_clean_generated_chapter_title_strips_slogan_prefix() -> None:
    assert clean_generated_chapter_title("01. 算得准：四则运算与数感基础") == "四则运算与数感基础"
    assert clean_generated_chapter_title("学得会：函数概念与图像关系") == "函数概念与图像关系"
    assert clean_generated_chapter_title("看得懂：实验现象与误差分析") == "实验现象与误差分析"
    assert clean_generated_chapter_title("写得出：循环结构与调试路径") == "循环结构与调试路径"


def test_clean_generated_chapter_title_keeps_real_topic_prefix() -> None:
    assert clean_generated_chapter_title("所得税：税法基础") == "所得税：税法基础"
    assert clean_generated_chapter_title("概率分布：离散与连续变量") == "概率分布：离散与连续变量"


def test_normalize_planner_draft_removes_slogan_title_prefixes() -> None:
    draft = normalize_planner_draft(
        {
            "plan_summary": "围绕三年级数学生成一份可确认的学习计划。",
            "plan_steps": ["确认范围", "归并资料", "划分章节", "形成大纲"],
            "chapter_plan": [
                {
                    "title": "算得准：四则运算与数感基础",
                    "key_points": ["整数四则运算", "估算与数感"],
                },
                {
                    "title": "量得清：单位换算与测量工具",
                    "key_points": ["长度质量时间单位", "测量工具使用"],
                },
                {
                    "title": "形得明：图形特征与面积公式",
                    "key_points": ["平面图形特征", "周长与面积"],
                },
                {
                    "title": "用得对：数量关系与应用题解法",
                    "key_points": ["数量关系", "应用题解法"],
                },
            ],
        },
        course_id="三年级数学",
        user_prompt="三年级数学系统学一下",
        requested_digest_mode="sprint",
    )

    titles = [chapter.title for chapter in draft.chapter_plan[:4]]

    assert titles == [
        "四则运算与数感基础",
        "单位换算与测量工具",
        "图形特征与面积公式",
        "数量关系与应用题解法",
    ]


def test_title_lock_prompt_blocks_slogan_prefixes() -> None:
    messages = build_title_lock_messages(
        course_name="三年级数学",
        digest_mode="sprint",
        user_prompt="三年级数学系统学一下",
        plan_summary="按运算、测量、图形和应用题组织。",
        chapter={
            "chapter_index": 1,
            "title": "算得准：四则运算与数感基础",
            "objective": "讲清整数四则运算和估算。",
            "required_elements": ["四则运算", "数感"],
        },
    )
    prompt_text = "\n".join(message["content"] for message in messages)

    assert "动词+得+形容词" in prompt_text
    assert "只保留冒号后的知识对象" in prompt_text
