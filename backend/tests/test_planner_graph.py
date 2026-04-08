from __future__ import annotations

from app.workflows.digest.planner.graph import (
    _build_raw_plan_from_preview,
    _extract_preview_tasks,
    _extract_preview_title,
)
from app.workflows.digest.planner.models import build_fallback_plan
from app.workflows.digest.shared.models import FastTopicHints, SharedInputs, SourcePacket, SubjectProfile


def _build_shared_inputs() -> SharedInputs:
    return SharedInputs(
        source_packets=[
            SourcePacket(
                file_id=1,
                filename="linear_algebra.md",
                filetype="markdown",
                markdown_path="linear_algebra.md",
                asset_dir="assets",
                normalized_content="\u5411\u91cf\u7a7a\u95f4\u3001\u77e9\u9635\u3001\u7279\u5f81\u503c\u4e0e\u7ebf\u6027\u53d8\u6362",
                char_count=200,
                has_formulas=True,
                has_tables=False,
                has_images=False,
            )
        ],
        fast_hints=FastTopicHints(
            chapter_candidates=[
                "\u5411\u91cf\u7a7a\u95f4",
                "\u77e9\u9635\u8fd0\u7b97",
                "\u7279\u5f81\u503c",
                "\u7ebf\u6027\u53d8\u6362",
            ]
        ),
        subject_profile=SubjectProfile(
            subject_name="\u7ebf\u6027\u4ee3\u6570",
            discipline="\u6570\u5b66",
            sub_discipline="\u4ee3\u6570",
            key_topics=[
                "\u5411\u91cf\u7a7a\u95f4",
                "\u77e9\u9635\u8fd0\u7b97",
                "\u7279\u5f81\u503c",
                "\u7ebf\u6027\u53d8\u6362",
            ],
            has_heavy_formulas=True,
        ),
    )


def test_extract_preview_title_and_tasks_from_plaintext_stream() -> None:
    raw_text = (
        "\u7ebf\u6027\u4ee3\u6570\u5b66\u4e60\u4e0e\u5e94\u7528\u6307\u5357\n"
        "\u7814\u7a76\u4efb\u52a1\n"
        "(1) \u68b3\u7406\u5411\u91cf\u7a7a\u95f4\u3001\u57fa\u4e0e\u7ef4\u6570\u7684\u6838\u5fc3\u5b9a\u4e49\n"
        "(2) \u8c03\u7814\u77e9\u9635\u8fd0\u7b97\u4e0e\u7ebf\u6027\u65b9\u7a0b\u7ec4\u7684\u89e3\u9898\u8def\u5f84\n"
        "\u5206\u6790\u7ed3\u679c\n"
        "\u751f\u6210\u62a5\u544a\n"
    )

    assert _extract_preview_title(raw_text) == "\u7ebf\u6027\u4ee3\u6570\u5b66\u4e60\u4e0e\u5e94\u7528\u6307\u5357"
    assert _extract_preview_tasks(raw_text) == [
        "\u68b3\u7406\u5411\u91cf\u7a7a\u95f4\u3001\u57fa\u4e0e\u7ef4\u6570\u7684\u6838\u5fc3\u5b9a\u4e49",
        "\u8c03\u7814\u77e9\u9635\u8fd0\u7b97\u4e0e\u7ebf\u6027\u65b9\u7a0b\u7ec4\u7684\u89e3\u9898\u8def\u5f84",
    ]


def test_build_raw_plan_from_preview_uses_plaintext_tasks() -> None:
    shared_inputs = _build_shared_inputs()
    fallback_plan = build_fallback_plan(
        subject="subj_linear",
        user_goal="\u7cfb\u7edf\u5b66\u4e60\u7ebf\u6027\u4ee3\u6570",
        digest_mode="systematic",
        tone="encouraging",
        shared_inputs=shared_inputs,
    )
    preview_text = (
        "\u7ebf\u6027\u4ee3\u6570\u5b66\u4e60\u4e0e\u5e94\u7528\u6307\u5357\n"
        "\u7814\u7a76\u4efb\u52a1\n"
        "(1) \u68b3\u7406\u5411\u91cf\u7a7a\u95f4\u3001\u5b50\u7a7a\u95f4\u4e0e\u57fa\u5e95\u7684\u6838\u5fc3\u5173\u7cfb\n"
        "(2) \u5206\u6790\u77e9\u9635\u8fd0\u7b97\u3001\u79e9\u4e0e\u53ef\u9006\u6027\u7684\u9898\u578b\u8fde\u63a5\n"
        "(3) \u8c03\u7814\u7279\u5f81\u503c\u3001\u7279\u5f81\u5411\u91cf\u4e0e\u5bf9\u89d2\u5316\u7684\u5b66\u4e60\u8def\u5f84\n"
        "\u5206\u6790\u7ed3\u679c\n"
        "\u751f\u6210\u62a5\u544a\n"
    )

    raw_plan, preview_tasks = _build_raw_plan_from_preview(
        preview_text=preview_text,
        display_subject="\u7ebf\u6027\u4ee3\u6570",
        user_goal="\u7cfb\u7edf\u5b66\u4e60\u7ebf\u6027\u4ee3\u6570",
        digest_mode="systematic",
        tone="encouraging",
        fallback_plan=fallback_plan,
    )

    assert preview_tasks[0].startswith("\u68b3\u7406\u5411\u91cf\u7a7a\u95f4")
    assert raw_plan["research_queries"][1].startswith("\u5206\u6790\u77e9\u9635\u8fd0\u7b97")
    assert raw_plan["chapter_plan"][0]["objective"].startswith("\u68b3\u7406\u5411\u91cf\u7a7a\u95f4")
    assert "subj_" not in raw_plan["plan_summary"]
