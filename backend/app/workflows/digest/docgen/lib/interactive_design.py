"""Interaction design briefs and quality checks for generated HTML sidecars."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from html import unescape


_CASE_REQUEST_MARKERS = ("例子", "案例", "题目", "应用", "场景", "演示")
_QUANTITATIVE_VISUAL_MARKERS = (
    "函数",
    "图像",
    "曲线",
    "极限",
    "导数",
    "积分",
    "无穷小",
    "近似",
    "误差",
    "比值",
    "变化率",
)
_GEOMETRY_VISUAL_MARKERS = ("几何", "三角形", "四边形", "圆", "角", "边", "面积", "周长", "坐标")
_UNIT_SCALE_MARKERS = ("单位", "换算", "数量级", "比例", "尺度", "百分比", "千克", "米", "秒")
_PROCESS_VISUAL_MARKERS = ("步骤", "流程", "推导", "算法", "方法", "路径", "计算", "求解")
_CONTRAST_VISUAL_MARKERS = ("区别", "比较", "分类", "辨析", "关系", "条件", "判定", "边界")


@dataclass(frozen=True)
class InteractionDesignBrief:
    learning_goal: str
    learner_action: str
    observable_change: str
    preferred_direction: str
    avoid: str

    def as_prompt_text(self) -> str:
        return "\n".join(
            [
                f"- 学习目标：{self.learning_goal}",
                f"- 学生操作：{self.learner_action}",
                f"- 观察变化：{self.observable_change}",
                f"- 展示方向：{self.preferred_direction}",
                f"- 避免事项：{self.avoid}",
            ]
        )

    def as_metadata(self) -> dict[str, str]:
        return {
            "learning_goal": self.learning_goal,
            "learner_action": self.learner_action,
            "observable_change": self.observable_change,
            "preferred_direction": self.preferred_direction,
            "avoid": self.avoid,
        }


@dataclass(frozen=True)
class InteractiveHtmlQualityReport:
    passed: bool
    issues: tuple[str, ...]


def _normalize_blob(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).casefold()


def _contains_any_marker(text: str, markers: Sequence[str]) -> bool:
    normalized = _normalize_blob(text)
    return any(_normalize_blob(marker) in normalized for marker in markers)


def _brief_focus_for_signal(signal: str, *, user_prompt: str = "", interaction_mode: str = "") -> tuple[str, str, str]:
    combined = "\n".join([user_prompt, signal])
    if user_prompt and _contains_any_marker(user_prompt, _CASE_REQUEST_MARKERS):
        return (
            "案例推演",
            "切换或调节具体例子中的关键条件",
            "观察同一知识点在不同情境下的结果差异和易错边界",
        )
    if _contains_any_marker(combined, _QUANTITATIVE_VISUAL_MARKERS):
        return (
            "局部变化观察",
            "拖动变量、范围或对比对象",
            "观察曲线、比值、误差或放大视图如何随状态改变",
        )
    if _contains_any_marker(combined, _GEOMETRY_VISUAL_MARKERS):
        return (
            "几何条件验证",
            "拖动图形元素或切换条件",
            "观察长度、角度、面积或判定结论何时保持、何时失效",
        )
    if _contains_any_marker(combined, _UNIT_SCALE_MARKERS):
        return (
            "单位尺度映射",
            "调节数值、单位或数量级",
            "观察换算结果、现实含义和常见误判如何变化",
        )
    if _contains_any_marker(combined, _PROCESS_VISUAL_MARKERS) or interaction_mode == "process_stepper":
        return (
            "步骤误区诊断",
            "推进步骤、切换做法或修正中间状态",
            "观察每一步如何影响后续结果以及错误从哪里出现",
        )
    if _contains_any_marker(combined, _CONTRAST_VISUAL_MARKERS) or interaction_mode == "concept_mapper":
        return (
            "分类边界切换",
            "改变案例特征、关系节点或判断条件",
            "观察类别、关系或结论为什么发生变化",
        )
    return (
        "核心概念操作化",
        "调节一个能代表概念状态的变量或选项",
        "观察概念表征、结果反馈或关键差异如何变化",
    )


def build_chapter_interaction_design_brief(
    *,
    title: str,
    objective: str,
    context: str,
    interaction_mode: str,
    concept_targets: Sequence[str],
    formula_targets: Sequence[str],
    claim_targets: Sequence[str],
) -> InteractionDesignBrief:
    signal = "\n".join(
        [
            title,
            objective,
            context,
            *list(concept_targets),
            *list(formula_targets),
            *list(claim_targets),
        ]
    )
    focus, action, observation = _brief_focus_for_signal(signal, interaction_mode=interaction_mode)
    goal_seed = objective.strip() or title.strip() or "帮助学生把抽象知识转化为可观察经验"
    return InteractionDesignBrief(
        learning_goal=f"围绕“{title or goal_seed}”，让学生通过一个微场景理解：{goal_seed[:90]}",
        learner_action=action,
        observable_change=observation,
        preferred_direction=f"{focus}；展示形式由内容决定，优先选择能让变化一眼可见的表达。",
        avoid="不要生成泛泛讲义、静态公式卡片、灰色占位块，或控件变化但核心图形/状态不变化的页面。",
    )


def build_selection_interaction_design_brief(
    *,
    anchor_title: str,
    selected_text: str,
    user_prompt: str,
    section_excerpt: str,
) -> InteractionDesignBrief:
    signal = "\n".join([anchor_title, selected_text, section_excerpt])
    focus, action, observation = _brief_focus_for_signal(signal, user_prompt=user_prompt)
    goal = (user_prompt or selected_text or anchor_title or "划选知识点").strip()
    goal = re.sub(r"\s+", " ", goal)[:90]
    return InteractionDesignBrief(
        learning_goal=f"把划选内容转化为可操作的理解场景：{goal}",
        learner_action=action,
        observable_change=observation,
        preferred_direction=f"{focus}；如果用户补充要求更具体，以用户诉求优先。",
        avoid="不要把划选文本扩写成长讲义；不要只做静态说明、通用白卡片或无意义滑块。",
    )


def _script_text(html: str) -> str:
    return "\n".join(
        match.group(1)
        for match in re.finditer(r"<script\b[^>]*>(.*?)</script>", str(html or ""), re.IGNORECASE | re.DOTALL)
    )


def _visible_html_text(html: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", "", str(html or ""), flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _context_terms(*parts: str, limit: int = 16) -> list[str]:
    text = "\n".join(str(part or "") for part in parts)
    candidates = re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z][A-Za-z0-9_+\-/]{2,}", text)
    stop_words = {
        "这个",
        "一个",
        "学生",
        "理解",
        "观察",
        "变化",
        "交互",
        "演示",
        "核心",
        "章节",
        "内容",
        "可以",
        "通过",
        "进行",
        "interactive",
    }
    terms: list[str] = []
    for candidate in candidates:
        normalized = candidate.strip()
        if not normalized or normalized.casefold() in stop_words or normalized in stop_words:
            continue
        if len(normalized) > 8 and re.fullmatch(r"[\u4e00-\u9fff]+", normalized):
            normalized = normalized[:8]
        if normalized not in terms:
            terms.append(normalized)
        if len(terms) >= limit:
            break
    return terms


def _has_meaningful_context_overlap(visible_text: str, *, title: str, context: str, design_brief: str) -> bool:
    terms = _context_terms(title, context, design_brief)
    if not terms:
        return True
    normalized_visible = _normalize_blob(visible_text)
    hits = sum(1 for term in terms[:12] if _normalize_blob(term) in normalized_visible)
    return hits >= 1


def _design_expects_rich_visual(design_brief: str, context: str) -> bool:
    signal = "\n".join([design_brief, context])
    return _contains_any_marker(
        signal,
        (
            "曲线",
            "坐标",
            "误差",
            "比值",
            "放大视图",
            "几何",
            "拖动图形",
            "面积",
            "角度",
            "尺度",
            "数量级",
        ),
    )


def assess_interactive_html_quality(
    html: str,
    *,
    title: str,
    context: str,
    design_brief: str,
) -> InteractiveHtmlQualityReport:
    """Assess whether a generated page is a useful micro-experiment, not just valid HTML."""

    raw = str(html or "")
    lower = raw.casefold()
    script = _script_text(raw)
    visible_text = _visible_html_text(raw)
    issues: list[str] = []

    control_count = len(re.findall(r"<(?:input|select|textarea|button)\b", raw, re.IGNORECASE))
    has_event_hook = bool(
        re.search(
            r"\b(addEventListener|requestAnimationFrame|oninput|onchange|onclick)\b|"
            r"\son(?:input|change|click|pointerdown|mousedown)\s*=",
            raw,
            re.IGNORECASE,
        )
    )
    has_script_state_update = bool(
        re.search(
            r"\b(textContent|innerText|innerHTML|classList|setAttribute|style\.|value\s*=|"
            r"clearRect|fillRect|stroke|arc|lineTo|draw[A-Z_]?)\b",
            script,
            re.IGNORECASE,
        )
    )
    has_svg_or_canvas = bool(re.search(r"<(?:svg|canvas)\b", raw, re.IGNORECASE))
    dom_visual_element_count = len(
        re.findall(r"<(?:div|span|section|article|li|p|table|tr|td)\b", raw, re.IGNORECASE)
    )
    has_dom_visual = dom_visual_element_count >= 8 and has_script_state_update
    has_feedback_copy = any(
        marker in visible_text
        for marker in ("观察", "提示", "现在", "变化", "结果", "比较", "误差", "为什么", "注意", "反馈")
    )
    has_reset = bool(re.search(r"重置|恢复|reset", visible_text + "\n" + raw, re.IGNORECASE))

    if (control_count == 0 or (control_count <= 1 and has_reset)) and not has_event_hook:
        issues.append("缺少学生能主动操作的控件或交互事件。")
    if not has_event_hook:
        issues.append("缺少事件驱动逻辑，页面更像静态说明而不是微实验。")
    if not (has_svg_or_canvas or has_dom_visual):
        issues.append("缺少随状态变化的可视表达；不能只依赖静态说明或占位块。")
    if not has_script_state_update:
        issues.append("交互没有明显更新文本、图形、样式或绘制状态。")
    if not has_feedback_copy:
        issues.append("缺少随操作理解的观察提示或结果反馈。")
    if not has_reset:
        issues.append("缺少能恢复初始状态的重置逻辑。")
    if _design_expects_rich_visual(design_brief, context) and not (has_svg_or_canvas or has_dom_visual):
        issues.append("设计 brief 指向连续变化或图形观察，但页面没有 SVG/Canvas 或真实 DOM 等清晰图形载体。")
    if not _has_meaningful_context_overlap(visible_text, title=title, context=context, design_brief=design_brief):
        issues.append("页面可见文本与当前知识点关联过弱，可能生成了泛化演示。")
    if (
        not has_svg_or_canvas
        and re.search(r"(background(?:-color)?\s*:\s*(?:gray|grey|#(?:aaa|bbb|ccc|ddd|eee)\b)|灰色|占位)", lower)
        and not any(marker in visible_text for marker in ("坐标", "曲线", "节点", "误差", "比例", "关系", "步骤", "结果"))
    ):
        issues.append("疑似使用灰色占位块替代真实可视化。")

    return InteractiveHtmlQualityReport(
        passed=not issues,
        issues=tuple(dict.fromkeys(issues)),
    )
