"""Typed question replacements that preserve every untouched question verbatim."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.workflows.digest.docgen.lib.models import DocGenBaseModel
from app.workflows.digest.docgen.lib.unit_tests import (
    ChapterUnitTestItem,
    _UNIT_TEST_CALLOUT_START_RE,
    _UNIT_TEST_QUESTION_HEADER_RE,
    _prepare_unit_test_items,
    _protect_fenced_code_blocks,
    _render_unit_test_item_markdown,
    _restore_fenced_code_blocks,
)


class UnitTestQuestionPatch(DocGenBaseModel):
    question_number: int = Field(ge=1)
    item: ChapterUnitTestItem


class UnitTestQuestionPatches(DocGenBaseModel):
    status: Literal["patch", "no_change"] = "patch"
    patches: list[UnitTestQuestionPatch] = Field(default_factory=list)
    covered_action_ids: list[str] = Field(default_factory=list)
    unresolved_action_ids: list[str] = Field(default_factory=list)
    note: str = ""


def unit_test_question_blocks(module: str) -> tuple[str, dict[int, str]]:
    """Read already validated QUESTION/ANSWER pairs, ignoring fenced examples."""
    visible, fenced = _protect_fenced_code_blocks(module)
    starts: list[int] = []
    cursor = 0
    for line in visible.splitlines(keepends=True):
        marker = _UNIT_TEST_CALLOUT_START_RE.match(line)
        if marker is not None and marker.group("kind").upper() == "QUESTION":
            starts.append(cursor)
        cursor += len(line)
    if not starts:
        return module, {}
    blocks: dict[int, str] = {}
    for start, end in zip(starts, [*starts[1:], len(visible)]):
        block = visible[start:end]
        header = _UNIT_TEST_QUESTION_HEADER_RE.search(block)
        if header is None:
            raise ValueError("Question replacement requires a valid numbered question header.")
        number = int(header.group("number"))
        if number in blocks:
            raise ValueError("Question numbers must be unique before selective repair.")
        blocks[number] = _restore_fenced_code_blocks(block, fenced)
    return _restore_fenced_code_blocks(visible[:starts[0]], fenced), blocks


def apply_unit_test_question_patches(
    module: str, patches: list[UnitTestQuestionPatch], *, chapter_title: str,
) -> tuple[str, str, str, str]:
    """Return the merged module and exact changed/unchanged review contexts."""
    prefix, blocks = unit_test_question_blocks(module)
    if not patches:
        raise ValueError("Question repair must return at least one targeted replacement.")
    replacements: dict[int, str] = {}
    for patch in patches:
        number = patch.question_number
        if number not in blocks or number in replacements:
            raise ValueError(f"Invalid or duplicate replacement question number Q{number:02d}.")
        item = _prepare_unit_test_items(
            [patch.item], title=chapter_title, min_items=1, max_items=1, fallback_targets=[],
        )[0]
        replacements[number] = _render_unit_test_item_markdown(item, index=number) + "\n\n"
    merged = prefix + "".join(replacements.get(number, block) for number, block in blocks.items())
    original = "\n\n".join(block for number, block in blocks.items() if number in replacements)
    changed = "\n\n".join(replacements[number] for number in blocks if number in replacements)
    unchanged = "\n\n".join(block for number, block in blocks.items() if number not in replacements)
    return merged, original, changed, unchanged
