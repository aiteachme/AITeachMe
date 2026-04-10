"""Lightweight Chinese planner prompts."""

from __future__ import annotations

from app.workflows.digest.shared.models import SharedInputs


def _mode_contract(digest_mode: str) -> str:
    normalized_mode = (digest_mode or "systematic").strip().lower()
    if normalized_mode == "sprint":
        return (
            "模式护栏：\n"
            "1. 这是冲刺型知识文档，章节数通常为 3 到 6 章，应由考点密度和用户目标决定，不要机械套固定模板。\n"
            "2. 研究任务要偏向抓重点、抓公式、抓题型、抓易错点，也可以按主题自然拆章。\n"
            "3. 不要把任务写成空泛口号，要能直接指导后续检索与写作。"
        )
    return (
        "模式护栏：\n"
        "1. 这是系统型知识文档，章节数通常为 5 到 12 章，应由主题复杂度、资料跨度和用户目标决定。\n"
        "2. 研究任务要覆盖概念、方法、推演、应用、边界条件与总结回收，但不要机械固定成同一套标题。\n"
        "3. 不要只是重复原始文件目录，要体现循序渐进的学习路径。"
    )


def _compact_file_summary(shared_inputs: SharedInputs) -> str:
    source_packets = list(shared_inputs.source_packets[:6])
    if not source_packets:
        return "暂无已解析资料，本次主要依据用户输入规划。"

    lines: list[str] = []
    for packet in source_packets:
        pieces = [packet.filename or f"file_{packet.file_id}"]
        if packet.has_formulas:
            pieces.append("公式多")
        if packet.has_tables:
            pieces.append("表格多")
        if packet.has_images:
            pieces.append("含图片")
        lines.append(" / ".join(pieces))
    return "\n".join(f"- {line}" for line in lines)


def _compact_topic_hints(shared_inputs: SharedInputs) -> str:
    raw_hints = [
        *shared_inputs.subject_profile.key_topics,
        *shared_inputs.fast_hints.chapter_candidates,
    ]
    hints: list[str] = []
    seen: set[str] = set()
    for item in raw_hints:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        hints.append(text)
        if len(hints) >= 8:
            break
    return "、".join(hints) if hints else "暂无明显主题提示"


def _compact_message_history(message_history: list[str]) -> str:
    cleaned = [str(item).strip() for item in message_history if str(item).strip()]
    if not cleaned:
        return "暂无补充修改意见"
    return "\n".join(f"- {item}" for item in cleaned[-4:])


def _compact_latest_plan(latest_plan: dict | None) -> str:
    if not latest_plan:
        return "暂无上一版方案"
    plan_summary = str(latest_plan.get("plan_summary") or "").strip()
    chapter_count = len(list(latest_plan.get("chapter_plan") or []))
    if plan_summary:
        return f"上一版摘要：{plan_summary}\n上一版章节数：{chapter_count}"
    return f"上一版章节数：{chapter_count}"


def build_planner_prompt(
    *,
    subject: str,
    user_goal: str,
    digest_mode: str,
    tone: str,
    shared_inputs: SharedInputs,
    message_history: list[str],
    latest_plan: dict | None,
    concept_briefing: str = "",
    skillpack_guidance: str = "",
    recommended_tool_tags: list[str] | None = None,
) -> str:
    compact_goal = user_goal.strip() or f"围绕 {subject} 生成知识文档"
    skillpack_section = (
        f"策略包约束：\n{skillpack_guidance.strip()}\n\n"
        if skillpack_guidance.strip()
        else ""
    )
    toolset_section = (
        f"推荐工具标签：{', '.join(recommended_tool_tags or [])}\n\n"
        if recommended_tool_tags
        else ""
    )
    return (
        "你是 AITeachMe 的构建方案规划助手。\n"
        "你的任务不是写文档正文，而是像 Deep Research 的前置规划阶段一样，"
        "快速给出一组可直接确认的研究任务。\n"
        "本轮规划必须先参考已经检索到的基础概念锚点，再组织章节任务，不要只靠主观联想裸生成。\n"
        "请严格依据用户目标、资料主题和最近修改意见来规划，避免空泛模板。\n\n"
        f"主题：{subject}\n"
        f"用户目标：{compact_goal}\n"
        f"期望模式：{digest_mode}\n"
        f"表达风格：{tone}\n\n"
        "主题提示：\n"
        f"{_compact_topic_hints(shared_inputs)}\n\n"
        "已上传资料：\n"
        f"{_compact_file_summary(shared_inputs)}\n\n"
        "最近对话与修改意见：\n"
        f"{_compact_message_history(message_history)}\n\n"
        "上一版方案：\n"
        f"{_compact_latest_plan(latest_plan)}\n\n"
        "快速概念锚点：\n"
        f"{concept_briefing.strip() or '暂无额外概念检索结果，可先依据资料主题与用户目标规划。'}\n\n"
        f"{skillpack_section}"
        f"{toolset_section}"
        f"{_mode_contract(digest_mode)}\n\n"
        "输出目标：\n"
        "1. 研究任务必须是中文自然语言。\n"
        "2. 每条任务都要能直接变成后续检索词或章节写作目标。\n"
        "3. 任务重点要贴合当前主题，不要出现 subj_ 这类内部标识。\n"
        "4. 优先覆盖快速概念检索里反复出现的核心概念、结构关系和基础方法，但不要机械照抄标题。\n"
        "5. 整体语气要清晰、直接、可执行。"
    )


__all__ = ["build_planner_prompt"]
