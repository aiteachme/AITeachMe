"""Prompt builders for DocGen content review."""

from __future__ import annotations

from app.workflows.digest.common.prompt_tracing import trace_prompt_build

REVIEW_MARKDOWN_BUDGET = 9000
REVIEW_LEDGER_BUDGET = 5000


def _clip(value: object, *, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n...[已截断]"


def build_chapter_review_messages(
    *,
    chapter_title: str,
    digest_mode: str,
    chapter_task: dict,
    markdown: str,
    claim_ledger: dict,
    claim_evidence_map: dict,
    conflict_report: dict,
    rule_review: dict,
) -> list[dict[str, str]]:
    """Build messages for read-only chapter review."""

    system_prompt = """
你是 AITeachMe 的内容质检员，只负责复核，不负责改写。
你必须严格检查章节是否符合用户已确认的章节合同、是否有证据支撑、是否越界、是否适合学习。
你不能新增事实，不能替正文打补丁，不能要求推翻 confirmed plan。
如果问题可以局部修，输出 section_patch 或 evidence_patch；只有整章严重不可用时才输出 regenerate_chapter。
证据不足时优先 evidence_patch，不要轻易要求整章重写。
""".strip()
    user_prompt = f"""
请复核下面这一章，并输出结构化结果。

章节标题：{chapter_title}
文档模式：{digest_mode}

章节执行合同：
{_clip(chapter_task, limit=REVIEW_LEDGER_BUDGET)}

规则复核基线：
{_clip(rule_review, limit=REVIEW_LEDGER_BUDGET)}

ClaimLedger：
{_clip(claim_ledger, limit=REVIEW_LEDGER_BUDGET)}

ClaimEvidenceMap：
{_clip(claim_evidence_map, limit=REVIEW_LEDGER_BUDGET)}

ConflictReport：
{_clip(conflict_report, limit=REVIEW_LEDGER_BUDGET)}

章节 Markdown：
{_clip(markdown, limit=REVIEW_MARKDOWN_BUDGET)}

复核要求：
1. 判断是否覆盖执行合同中的关键点。
2. 判断主张是否有足够证据支撑。
3. 判断是否越过章节边界或推翻 confirmed plan。
4. 判断是否适合学生学习，不要只看格式。
5. action 必须可执行，写清 target_anchor、instruction、constraints、expected_effect。
6. 只做复核判断，不输出修补后的正文。
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return trace_prompt_build(
        "chapter_review",
        inputs={
            "chapter_title": chapter_title,
            "digest_mode": digest_mode,
            "markdown_chars": len(markdown),
            "chapter_task_keys": sorted(chapter_task.keys()),
        },
        output=messages,
    )


__all__ = ["build_chapter_review_messages"]
