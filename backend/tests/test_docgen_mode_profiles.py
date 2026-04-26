from app.workflows.digest.docgen.lib.chapter_enhancement import _append_practice_section
from app.workflows.digest.docgen.mode_profiles import get_docgen_mode_profile
from app.workflows.digest.docgen.prompts.generation import build_docgen_writer_messages


def test_docgen_mode_profile_uses_flexible_course_hints():
    for mode in ("sprint", "systematic"):
        profile = get_docgen_mode_profile(mode)
        joined = "\n".join([*profile.chapter_format, *profile.course_flow_hints])

        assert "本章自检" not in joined
        assert profile.course_flow_hints
        assert profile.practice_focuses


def test_writer_prompt_marks_course_flow_as_non_required():
    messages = build_docgen_writer_messages(
        title="行列式",
        objective="理解行列式计算",
        digest_mode="sprint",
        required_elements=["行列式性质"],
        writing_instructions="",
        source_count=1,
        dense_context="行列式性质与计算例题。",
        chapter_index=1,
        chapter_count=3,
    )

    prompt = messages[-1]["content"]
    assert "课程化节奏" in prompt
    assert "不是固定目录" in prompt
    assert "不要为了凑齐参考模块而硬塞小节" in prompt


def test_append_practice_section_uses_mode_specific_headings():
    questions = [{"question": "写出题眼和最短解法。"}]

    sprint = _append_practice_section("# 行列式\n\n正文", questions, digest_mode="sprint")
    systematic = _append_practice_section("# 行列式\n\n正文", questions, digest_mode="systematic")

    assert "## 题型例练" in sprint
    assert "## 例题与迁移" in systematic
