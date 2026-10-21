"""Deterministic Markdown checks for explicit, LLM-interpreted quantities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re

from markdown_it import MarkdownIt

from app.workflows.digest.docgen.lib.models import ChapterQuantityConstraints
from app.workflows.digest.docgen.lib.unit_tests import unit_test_structure_issues


class ChapterQuantityContractError(RuntimeError):
    """Raised when final publication formatting violates explicit quantities."""


@dataclass(frozen=True)
class ExplicitChapterEndQuestionContract:
    """A quantity contract extracted from an untrusted natural-language handoff."""

    total: int
    minimum_groups: int
    group_counts: tuple[int, ...]
    source: str


_QUESTION_COUNT_VALUE = r"[0-9０-９一二两三四五六七八九十百]+"
_QUESTION_COUNT = rf"(?P<count>{_QUESTION_COUNT_VALUE})"
_QUESTION_LABEL = (
    r"(?:章末|章尾|课后|应用迁移|应用练习|实践练习|迁移练习|填空短测|"
    r"选择题|填空题|判断题|简答题|短测|小测|自测|测验|测试|练习|习题|题目|题)"
)
_QUESTION_GROUP_RE = re.compile(
    rf"{_QUESTION_COUNT}\s*(?:(?:道|个)\s*{_QUESTION_LABEL}|题)(?!组|型|量)",
)
_ADDITIVE_GROUP_RE = re.compile(
    rf"{_QUESTION_COUNT_VALUE}\s*(?:道|题|个)\s*{_QUESTION_LABEL}\s*"
    rf"(?:和|及|与|、|，|,|\+|＋|加)\s*"
    rf"{_QUESTION_COUNT_VALUE}\s*(?:道|题|个)\s*{_QUESTION_LABEL}",
)
_QUESTION_TOTAL_RE = re.compile(
    rf"(?:共|总计|合计)\s*{_QUESTION_COUNT}\s*(?:道|题|个)(?!\s*(?:题组|题型|题量|组|型|量))",
)
_CHAPTER_END_MARKER_RE = re.compile(
    r"章末|章尾|课后(?!\s*(?:练习|题|短测|小测|测验|测试|习题|题目|应用|实践|迁移|填空))|"
    r"单元(?:测试|小测)|章节(?:测试|小测)|课末"
)
_SENTENCE_BOUNDARY_RE = re.compile(r"[。；;!！?？\n]")
_ADDITIVE_RE = re.compile(r"(?:和|及|与|、|，|,|\+|＋|加)")
_CHINESE_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
                   "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "百": 100}


def _parse_question_count(value: str) -> int | None:
    normalized = value.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if normalized.isdigit():
        parsed = int(normalized)
        return parsed if parsed > 0 else None
    if not normalized or any(char not in _CHINESE_DIGITS for char in normalized):
        return None
    # Handle common 十/百 forms as well as Arabic numerals without altering
    # the explicitly requested quantity.
    if len(normalized) == 1:
        parsed = _CHINESE_DIGITS[normalized]
        return parsed if parsed > 0 else None
    if "百" in normalized:
        head, _, tail = normalized.partition("百")
        value = _CHINESE_DIGITS.get(head, 1) * 100
        if tail:
            value += _parse_question_count(tail) or 0
        return value if value > 0 else None
    if "十" in normalized:
        head, _, tail = normalized.partition("十")
        value = (_CHINESE_DIGITS.get(head, 1) * 10) + (_CHINESE_DIGITS.get(tail, 0) if tail else 0)
        return value if value > 0 else None
    value = 0
    for char in normalized:
        value = value * 10 + _CHINESE_DIGITS[char]
    return value if value > 0 else None


def _question_group_counts(fragment: str) -> list[int]:
    return [
        count
        for match in _QUESTION_GROUP_RE.finditer(fragment)
        if (count := _parse_question_count(match.group("count"))) is not None
    ]


def infer_explicit_chapter_end_question_contracts(
    sources: Sequence[str] = (),
) -> list[ExplicitChapterEndQuestionContract]:
    """Extract only unambiguous additive chapter-end question requirements.

    This deliberately consumes the confirmed/user text as a second signal.  It
    never invents a quantity from mode defaults and treats ``共 5 题，其中 2
    道练习`` as one five-question total rather than adding the subset twice.
    """

    if isinstance(sources, str):
        sources = (sources,)
    contracts: list[ExplicitChapterEndQuestionContract] = []
    for raw_source in sources:
        source = str(raw_source or "").strip()
        if not source:
            continue
        markers = list(_CHAPTER_END_MARKER_RE.finditer(source))
        for marker_index, marker in enumerate(markers):
            boundary = _SENTENCE_BOUNDARY_RE.search(source, marker.end())
            end = boundary.start() if boundary else len(source)
            if marker_index + 1 < len(markers):
                end = min(end, markers[marker_index + 1].start())
            fragment = source[marker.start():end]
            total_match = _QUESTION_TOTAL_RE.search(fragment)
            if total_match:
                # Do not count the declared total itself as one of the
                # additive groups (for example, ``共 9 题，4 道练习和 5 道短测``).
                groups = _question_group_counts(
                    fragment[:total_match.start()] + fragment[total_match.end():]
                )
                total = _parse_question_count(total_match.group("count"))
                if total is not None:
                    # A phrase such as “共 5 题，其中 2 道练习” describes a
                    # subset, not a second independent group.  Only preserve
                    # group counts when the extracted groups are additive and
                    # account for the declared total.
                    additive_groups = (
                        groups
                        if len(groups) >= 2
                        and _ADDITIVE_RE.search(fragment)
                        and sum(groups) == total
                        else []
                    )
                    contracts.append(ExplicitChapterEndQuestionContract(
                        total=total,
                        minimum_groups=max(1, len(additive_groups)),
                        group_counts=tuple(additive_groups),
                        source=fragment,
                    ))
                continue
            groups = _question_group_counts(fragment)
            if len(groups) == 1:
                contracts.append(ExplicitChapterEndQuestionContract(
                    total=groups[0], minimum_groups=1,
                    group_counts=(), source=fragment,
                ))
            elif len(groups) >= 2 and _ADDITIVE_RE.search(fragment):
                contracts.append(ExplicitChapterEndQuestionContract(
                    total=sum(groups), minimum_groups=len(groups),
                    group_counts=tuple(groups), source=fragment,
                ))

        # A short-test label is a strong chapter-end signal even when a UI
        # handoff omits the word “章末”; avoid treating a sentence explicitly
        # scoped to正文 as a chapter-end contract.
        if not _CHAPTER_END_MARKER_RE.search(source) and "正文" not in source:
            for match in re.finditer(
                _ADDITIVE_GROUP_RE.pattern,
                source,
            ):
                fragment = match.group(0)
                groups = _question_group_counts(fragment)
                if len(groups) >= 2 and any(label in fragment for label in ("短测", "小测", "测验", "测试")):
                    contracts.append(ExplicitChapterEndQuestionContract(
                        total=sum(groups), minimum_groups=len(groups),
                        group_counts=tuple(groups), source=fragment,
                    ))
    unique: dict[tuple[int, int, tuple[int, ...], str], ExplicitChapterEndQuestionContract] = {}
    for contract in contracts:
        unique[(contract.total, contract.minimum_groups, contract.group_counts, contract.source)] = contract
    return list(unique.values())


def chapter_end_question_contract_issues(
    *,
    quantity_constraints: ChapterQuantityConstraints,
    chapter_end_practice_plan: Sequence[Mapping[str, object]],
    sources: Sequence[str] = (),
) -> list[str]:
    """Cross-check model JSON against explicit natural-language group requests."""

    contracts = infer_explicit_chapter_end_question_contracts(sources)
    if not contracts:
        return []
    plan_counts = [
        int(item["question_count"])
        for item in (chapter_end_practice_plan or ())
        if (
            isinstance(item, Mapping)
            and isinstance(item.get("question_count"), int)
            and not isinstance(item.get("question_count"), bool)
        )
    ]
    issues: list[str] = []
    for contract in contracts:
        actual = quantity_constraints.chapter_end_question_count
        if actual != contract.total:
            issues.append(
                f"原始需求“{contract.source}”明确要求章末共 {contract.total} 题，"
                f"结构化 quantity_constraints 却为 {actual!r}。"
            )
        if len(plan_counts) < contract.minimum_groups:
            issues.append(
                f"原始需求“{contract.source}”包含至少 {contract.minimum_groups} 个互不重叠题组，"
                f"结构化 chapter_end_practice_plan 只有 {len(plan_counts)} 组。"
            )
        elif contract.group_counts and len(contract.group_counts) == len(plan_counts):
            if sorted(plan_counts) != sorted(contract.group_counts):
                issues.append(
                    f"原始需求“{contract.source}”要求题组数量为 {list(contract.group_counts)}，"
                    f"结构化 chapter_end_practice_plan 却为 {plan_counts}。"
                )
    return issues


def explicit_chapter_structure_issues(
    markdown: str,
    quantities: ChapterQuantityConstraints,
    *,
    include_unit_test: bool = False,
) -> list[str]:
    """Count Markdown structure, leaving examples and prose length to semantic review."""

    issues: list[str] = []
    if quantities.body_section_count is not None:
        tokens = MarkdownIt("commonmark").parse(markdown)
        section_count = sum(
            token.type == "heading_open" and token.tag == "h2" and token.level == 0
            and tokens[index + 1].content != "单元测试"
            for index, token in enumerate(tokens)
        )
        if section_count != quantities.body_section_count:
            issues.append(f"正文必须恰好有 {quantities.body_section_count} 个二级小节，当前为 {section_count} 个。")
    if include_unit_test and quantities.chapter_end_question_count is not None:
        issues.extend(unit_test_structure_issues(
            markdown, expected_question_count=quantities.chapter_end_question_count,
        ))
    # Raw Markdown character counts include code and markup; they cannot
    # validate a natural-language word range or count semantic teaching examples.
    return issues
