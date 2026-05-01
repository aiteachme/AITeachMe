"""Chapter-level review for enhanced DocGen drafts."""

from __future__ import annotations

from collections.abc import Sequence
import re

from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.tools.builtin.markdown_processing import count_words, find_markdown_rendering_issues
from app.workflows.digest.docgen.lib.model_policy import DocGenModelStep, docgen_completion_kwargs_with_metadata
from app.workflows.digest.docgen.lib.models import (
    ChapterGenerationTask,
    ChapterReviewReport,
    ClaimEvidenceMap,
    ClaimLedger,
    ConflictReport,
    EnhancedChapterDraft,
    LLMChapterReviewResult,
    ReviewAction,
    ReviewedChapterDraft,
    clean_string_list,
)
from app.workflows.digest.docgen.lib.quality import evidence_support_score
from app.workflows.digest.docgen.prompts.chapter_review import build_chapter_review_messages

_LEARNING_ACTIVITY_RE = re.compile(
    r"(?:例题|案例|示例|练习|自测|实践任务|实践案例|操作案例|操作示例|变式|错误诊断|任务场景|复盘任务)"
)


def _coverage(markdown: str, targets: list[str]) -> tuple[float, list[str]]:
    if not targets:
        return 1.0, []
    normalized = "".join(str(markdown or "").split()).casefold()
    missing: list[str] = []
    hits = 0
    for target in targets:
        needle = "".join(str(target or "").split()).casefold()
        if needle and needle in normalized:
            hits += 1
        else:
            missing.append(target)
    return round(hits / max(1, len(targets)), 4), missing


def _safe_int(value: object, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _learning_activity_count(markdown: str) -> int:
    return len(_LEARNING_ACTIVITY_RE.findall(str(markdown or "")))


def _planned_example_count(task: ChapterGenerationTask) -> int:
    total = 0
    for item in task.example_coverage_plan or []:
        if isinstance(item, dict):
            total += max(1, _safe_int(item.get("min_examples"), default=1))
    return total


def _missing_example_targets(markdown: str, task: ChapterGenerationTask, *, limit: int = 8) -> list[str]:
    normalized = "".join(str(markdown or "").split()).casefold()
    missing: list[str] = []
    for item in task.example_coverage_plan or []:
        if not isinstance(item, dict):
            continue
        target = str(item.get("target") or "").strip()
        needle = "".join(target.split()).casefold()
        if needle and needle not in normalized:
            missing.append(target)
        if len(missing) >= limit:
            break
    return missing


def _chapter_anchor(draft: EnhancedChapterDraft) -> str:
    return draft.title or f"chapter:{draft.chapter_index}"


def _dedupe_actions(actions: Sequence[ReviewAction]) -> list[ReviewAction]:
    deduped: list[ReviewAction] = []
    seen: set[tuple[str, int | None, str, str]] = set()
    for action in actions:
        key = (
            action.action_type,
            action.chapter_index,
            action.target_anchor.casefold(),
            action.reason.casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return deduped


def _rule_review_chapter(
    *,
    draft: EnhancedChapterDraft,
    task: ChapterGenerationTask | None,
    claim_ledger: ClaimLedger | None,
    claim_evidence_map: ClaimEvidenceMap | None,
    conflict_report: ConflictReport | None,
    digest_mode: str = "",
) -> tuple[ReviewedChapterDraft, ChapterReviewReport, list[ReviewAction]]:
    """执行无需 LLM 的章节复核兜底。

    规则复核只检查合同覆盖、证据支撑、长度和冲突信号。它既是 LLM
    review 失败时的 fallback，也是 LLM 结果的 guardrail。
    """

    task = task or ChapterGenerationTask(chapter_index=draft.chapter_index, confirmed_title=draft.title)
    targets = clean_string_list([*task.required_elements, *task.claim_targets], limit=18)
    coverage_score, missing = _coverage(draft.markdown, targets)
    support_score = evidence_support_score(claim_evidence_map or ClaimEvidenceMap(chapter_index=draft.chapter_index))
    quality_score = draft.quality_signals.quality_score or 0.0
    word_count = count_words(draft.markdown)
    warnings: list[str] = []
    actions: list[ReviewAction] = []
    rendering_issues = find_markdown_rendering_issues(draft.markdown)
    if rendering_issues:
        warnings.extend(rendering_issues)
        actions.append(
            ReviewAction(
                action_id=f"review_ch{draft.chapter_index:02d}_surface_rendering",
                action_type="surface_patch",
                chapter_index=draft.chapter_index,
                severity="warning",
                reason="Markdown 渲染结构异常：" + "；".join(rendering_issues),
                target_anchor=_chapter_anchor(draft),
                instruction="只修复 Markdown 结构，包括 blockquote、代码块和 display math 的分隔，不改正文知识内容。",
                constraints=[
                    "不得新增或删除知识点。",
                    "不得改变章节标题和章节顺序。",
                    "只允许调整 Markdown 标记、空行和 fenced block 边界。",
                ],
                expected_effect="章节 Markdown 可以稳定渲染，代码块和公式不被引用块污染。",
            )
        )
    if missing:
        warnings.append("章节未完全覆盖执行合同中的关键点。")
        actions.append(
            ReviewAction(
                action_id=f"review_ch{draft.chapter_index:02d}_section_patch",
                action_type="section_patch",
                chapter_index=draft.chapter_index,
                severity="warning",
                reason="缺少章节合同项：" + "、".join(missing[:5]),
                target_anchor=_chapter_anchor(draft),
                instruction="补齐章节中缺失的合同项：" + "、".join(missing[:8]),
                constraints=[
                    "不得新增、删除或重排 confirmed plan 章节。",
                    "只允许修改本章相关小节。",
                    "不得引入没有证据支撑的新断言。",
                ],
                expected_effect="章节正文能覆盖执行合同中的关键点，且不改变章节边界。",
            )
        )
    activity_count = _learning_activity_count(draft.markdown)
    planned_examples = _planned_example_count(task)
    density_policy = dict(task.practice_seed_policy.get("example_density_policy") or {})
    if str(digest_mode or task.practice_seed_policy.get("digest_mode") or "").strip().lower() == "sprint":
        expected_activity_count = max(
            3,
            min(
                8,
                planned_examples
                or _safe_int(density_policy.get("worked_examples_per_chapter"), default=4)
                + _safe_int(density_policy.get("practice_tasks_per_chapter"), default=4),
            ),
        )
        if activity_count < expected_activity_count:
            warnings.append("速成课例题、案例、训练或实践任务密度不足。")
            actions.append(
                ReviewAction(
                    action_id=f"review_ch{draft.chapter_index:02d}_sprint_examples",
                    action_type="section_patch",
                    chapter_index=draft.chapter_index,
                    severity="warning",
                    reason=f"速成课学习活动密度不足：当前约 {activity_count} 处，目标至少 {expected_activity_count} 处。",
                    target_anchor=_chapter_anchor(draft),
                    instruction=(
                        "补充高价值例题、操作案例、变式训练、自测或错误诊断；每个重要方法要有识别信号、"
                        "步骤过程、答案/结果和易错复盘。"
                    ),
                    constraints=[
                        "不把非考试主题硬改成试卷题。",
                        "优先补本章已有知识点、方法或场景的例子，不新增无来源的新主题。",
                        "理论说明必须服务会做题、会操作、会判断、会避坑。",
                    ],
                    expected_effect="速成章形成题型/场景/任务驱动的例题和训练密度。",
                )
            )
    else:
        missing_example_targets = _missing_example_targets(draft.markdown, task, limit=6)
        expected_activity_count = min(6, max(2, len(task.example_coverage_plan or [])))
        if task.example_coverage_plan and (missing_example_targets or activity_count < expected_activity_count):
            warnings.append("系统课核心知识点缺少足够例题、案例或练习覆盖。")
            detail = "、".join(missing_example_targets[:5]) if missing_example_targets else "部分核心知识点"
            actions.append(
                ReviewAction(
                    action_id=f"review_ch{draft.chapter_index:02d}_systematic_examples",
                    action_type="section_patch",
                    chapter_index=draft.chapter_index,
                    severity="warning",
                    reason="系统课例题覆盖不足：" + detail,
                    target_anchor=_chapter_anchor(draft),
                    instruction=(
                        "为缺少覆盖的核心知识点补充例题、案例、操作示例或练习任务；重要、易错或核心方法优先"
                        "提供两个不同角度的例子或任务。"
                    ),
                    constraints=[
                        "不得只追加题目答案，必须说明思路、过程、易错点和知识点回扣。",
                        "不得改变 confirmed plan 的章节边界。",
                        "新增例题或案例必须围绕本章已有知识点。",
                    ],
                    expected_effect="系统章做到知识细讲并由例题/案例支撑核心知识点。",
                )
            )
    if support_score < task.evidence_support_threshold and list((claim_ledger or ClaimLedger()).items or []):
        warnings.append("部分主张证据支撑偏弱。")
        actions.append(
            ReviewAction(
                action_id=f"review_ch{draft.chapter_index:02d}_evidence",
                action_type="evidence_patch",
                chapter_index=draft.chapter_index,
                severity="warning",
                reason="主张证据支撑低于阈值。",
                target_anchor=_chapter_anchor(draft),
                instruction="针对证据支撑不足的主张补充可追踪来源，并只局部改写相关小节。",
                constraints=[
                    "必须优先使用本地资料或已打开网页正文。",
                    "不得只依据搜索标题补新断言。",
                    "补充来源和 claim/evidence 映射必须写入 manifest。",
                ],
                expected_effect="低支撑主张获得新的 evidence binding，章节正文只做必要局部调整。",
            )
        )
    if word_count < task.min_word_count:
        warnings.append("章节长度低于最低字数要求。")
        actions.append(
            ReviewAction(
                action_id=f"review_ch{draft.chapter_index:02d}_surface_length",
                action_type="record_only",
                chapter_index=draft.chapter_index,
                severity="info",
                reason="章节偏短；当前阶段仅记录，后续可由有限回流决定是否扩写。",
                target_anchor=_chapter_anchor(draft),
                instruction="记录章节长度偏短，不在 MVP repair 中自动扩写。",
                constraints=[
                    "不因长度原因自动新增事实内容。",
                    "不改变当前发布正文。",
                ],
                expected_effect="manifest 中保留长度风险，发布流程不中断。",
            )
        )
    unresolved_conflicts = int((conflict_report or ConflictReport()).unresolved_count or 0)
    if unresolved_conflicts > 0:
        warnings.append("仍存在未解决的低证据或冲突提示。")
    passed = not any(
        action.action_type in {"section_patch", "evidence_patch", "regenerate_chapter", "re_dispatch", "rebuild_backbone"}
        and action.severity in {"warning", "error"}
        for action in actions
    )
    report = ChapterReviewReport(
        report_id=f"ch{draft.chapter_index:02d}_review",
        chapter_index=draft.chapter_index,
        passed=passed,
        coverage_score=coverage_score,
        evidence_support_score=support_score,
        quality_score=quality_score,
        missing_elements=missing,
        warnings=warnings,
        fallback_used=False,
    )
    reviewed = ReviewedChapterDraft.model_validate(
        {
            **draft.model_dump(mode="json"),
            "review_report_ref": report.report_id,
            "warnings": [*draft.warnings, *warnings],
            "patched": False,
        }
    )
    return reviewed, report, actions


def _llm_actions_to_review_actions(
    *,
    draft: EnhancedChapterDraft,
    suggestions: Sequence,
) -> list[ReviewAction]:
    actions: list[ReviewAction] = []
    for index, suggestion in enumerate(suggestions, start=1):
        action_type = suggestion.action_type
        if action_type == "regenerate_chapter" and suggestion.reason and "证据" in suggestion.reason:
            action_type = "evidence_patch"
        actions.append(
            ReviewAction(
                action_id=f"llm_review_ch{draft.chapter_index:02d}_{index:02d}_{action_type}",
                action_type=action_type,
                chapter_index=draft.chapter_index,
                severity=suggestion.severity,
                reason=suggestion.reason,
                target_anchor=suggestion.target_anchor or _chapter_anchor(draft),
                instruction=suggestion.instruction,
                constraints=suggestion.constraints,
                expected_effect=suggestion.expected_effect,
            )
        )
    return actions


async def review_chapter(
    *,
    draft: EnhancedChapterDraft,
    task: ChapterGenerationTask | None,
    claim_ledger: ClaimLedger | None,
    claim_evidence_map: ClaimEvidenceMap | None,
    conflict_report: ConflictReport | None,
    digest_mode: str = "",
) -> tuple[ReviewedChapterDraft, ChapterReviewReport, list[ReviewAction]]:
    """Run LLM content review with deterministic guardrail fallback."""

    rule_reviewed, rule_report, rule_actions = _rule_review_chapter(
        draft=draft,
        task=task,
        claim_ledger=claim_ledger,
        claim_evidence_map=claim_evidence_map,
        conflict_report=conflict_report,
        digest_mode=digest_mode,
    )
    task = task or ChapterGenerationTask(chapter_index=draft.chapter_index, confirmed_title=draft.title)
    try:
        llm_result = await acompletion_with_fallback(
            build_chapter_review_messages(
                chapter_title=draft.title,
                digest_mode=digest_mode,
                chapter_task=task.model_dump(mode="json"),
                markdown=draft.markdown,
                claim_ledger=(claim_ledger or ClaimLedger(chapter_index=draft.chapter_index)).model_dump(mode="json"),
                claim_evidence_map=(claim_evidence_map or ClaimEvidenceMap(chapter_index=draft.chapter_index)).model_dump(mode="json"),
                conflict_report=(conflict_report or ConflictReport(chapter_index=draft.chapter_index)).model_dump(mode="json"),
                rule_review=rule_report.model_dump(mode="json"),
            ),
            **docgen_completion_kwargs_with_metadata(
                DocGenModelStep.CHAPTER_REVIEW,
                digest_mode=digest_mode,
                chapter_index=draft.chapter_index,
                review_mode="docgen_content_review",
            ),
            response_model=LLMChapterReviewResult,
        )
        assert isinstance(llm_result, LLMChapterReviewResult)
    except Exception as exc:
        fallback_report = rule_report.model_copy(
            update={
                "warnings": [
                    *rule_report.warnings,
                    f"LLM 内容复核失败，已使用规则复核兜底：{str(exc)[:120]}",
                ],
                "fallback_used": True,
                "review_mode": "rule_fallback_after_llm_error",
            }
        )
        fallback_reviewed = ReviewedChapterDraft.model_validate(
            {
                **rule_reviewed.model_dump(mode="json"),
                "warnings": clean_string_list([*draft.warnings, *fallback_report.warnings], limit=32),
                "review_report_ref": fallback_report.report_id,
            }
        )
        return fallback_reviewed, fallback_report, rule_actions

    llm_actions = _llm_actions_to_review_actions(
        draft=draft,
        suggestions=llm_result.actions,
    )
    merged_actions = _dedupe_actions([*rule_actions, *llm_actions])
    missing = clean_string_list([*rule_report.missing_elements, *llm_result.missing_elements], limit=18)
    warnings = clean_string_list([*rule_report.warnings, *llm_result.warnings], limit=24)
    blocking_types = {"section_patch", "evidence_patch", "regenerate_chapter", "re_dispatch", "rebuild_backbone"}
    passed = llm_result.passed and not any(
        action.action_type in blocking_types and action.severity in {"warning", "error"}
        for action in merged_actions
    )
    report = ChapterReviewReport(
        report_id=rule_report.report_id,
        chapter_index=draft.chapter_index,
        passed=passed,
        coverage_score=min(rule_report.coverage_score or 1.0, llm_result.coverage_score),
        evidence_support_score=min(rule_report.evidence_support_score or 1.0, llm_result.evidence_support_score),
        quality_score=min(rule_report.quality_score or 1.0, llm_result.quality_score),
        missing_elements=missing,
        warnings=warnings,
        fallback_used=False,
        review_mode="llm_structured_with_rule_guardrails",
        llm_action_count=len(llm_actions),
        rule_action_count=len(rule_actions),
    )
    reviewed = ReviewedChapterDraft.model_validate(
        {
            **draft.model_dump(mode="json"),
            "review_report_ref": report.report_id,
            "warnings": [*draft.warnings, *warnings],
            "patched": False,
        }
    )
    return reviewed, report, merged_actions


__all__ = ["review_chapter"]
