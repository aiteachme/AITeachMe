"""Load user goal, file context, and shared inputs for planner."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from app.models.subject import Subject
from app.repositories.files_repo import list_raw_files_by_ids
from app.shared.infra.database import managed_session
from app.shared.infra.workflow import emit_progress
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.state import BuildPlannerState
from app.workflows.digest.shared.contracts import (
    resolve_digest_course_type,
    resolve_planner_retrieval_profile,
)
from app.workflows.digest.shared.models import FastTopicHints, SharedInputs, SourcePacket, SubjectProfile
from app.workflows.digest.shared.prepare import prepare_shared_inputs

_SUBJECT_SLUG_RE = re.compile(r"^subj_[a-z0-9]+$", re.IGNORECASE)


def _guess_topic_hints_from_filenames(
    filenames: list[str],
    *,
    subject: str,
    user_goal: str | None,
) -> list[str]:
    seeds: list[str] = []
    if user_goal and user_goal.strip():
        seeds.append(user_goal.strip())
    for filename in filenames:
        stem = Path(filename).stem.strip()
        if not stem:
            continue
        cleaned = stem.replace("_", " ").replace("-", " ").strip()
        if cleaned:
            seeds.append(cleaned)
    if subject and not _SUBJECT_SLUG_RE.fullmatch(subject.strip()):
        seeds.append(subject)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in seeds:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= 8:
            break
    return deduped


def _build_seed_shared_inputs(*, subject: str, file_ids: list[int], user_goal: str | None) -> SharedInputs:
    with managed_session() as session:
        raw_files = list_raw_files_by_ids(session, subject, file_ids)
        subject_row = session.query(Subject).filter(Subject.slug == subject).first()

    filenames = [raw_file.original_filename for raw_file in raw_files if raw_file.original_filename]
    topic_hints = _guess_topic_hints_from_filenames(filenames, subject=subject, user_goal=user_goal)
    discipline_counts = Counter(
        str(raw_file.detected_discipline).strip()
        for raw_file in raw_files
        if raw_file.detected_discipline
    )
    sub_discipline_counts = Counter(
        str(raw_file.detected_sub_discipline).strip()
        for raw_file in raw_files
        if raw_file.detected_sub_discipline
    )
    content_type_counts = Counter(
        str(raw_file.detected_content_type).strip()
        for raw_file in raw_files
        if raw_file.detected_content_type
    )

    source_packets = [
        SourcePacket(
            file_id=int(raw_file.id),
            filename=raw_file.original_filename,
            filetype=raw_file.file_ext,
            markdown_path=raw_file.markdown_path or "",
            asset_dir=raw_file.asset_dir or "",
            normalized_content=f"文件名：{raw_file.original_filename}",
            char_count=0,
            has_formulas=False,
            has_tables=False,
            has_images=bool(raw_file.image_count),
            image_refs=[],
        )
        for raw_file in raw_files
        if raw_file.id is not None
    ]

    return SharedInputs(
        source_packets=source_packets,
        fast_hints=FastTopicHints(chapter_candidates=topic_hints),
        subject_profile=SubjectProfile(
            subject_slug=subject,
            subject_name=(subject_row.name or "").strip() if subject_row is not None else "",
            discipline=(discipline_counts.most_common(1)[0][0] if discipline_counts else ""),
            sub_discipline=(sub_discipline_counts.most_common(1)[0][0] if sub_discipline_counts else ""),
            content_type=(content_type_counts.most_common(1)[0][0] if content_type_counts else ""),
            key_topics=topic_hints,
        ),
    )


def build_load_context_node(*, context: WorkflowContext):
    async def load_context_node(state: BuildPlannerState) -> dict:
        await emit_progress(
            state,
            stage="load_context",
            step="load_context",
            detail="正在读取用户目标和已上传资料...",
        )
        shared_inputs = await prepare_shared_inputs(
            state["subject"],
            state.get("file_ids", []),
            user_prompt=state.get("user_goal"),
        )
        if not shared_inputs.source_packets:
            shared_inputs = _build_seed_shared_inputs(
                subject=state["subject"],
                file_ids=list(state.get("file_ids", [])),
                user_goal=state.get("user_goal"),
            )

        digest_mode = state.get("digest_mode") or shared_inputs.digest_mode_decision.mode.value
        return {
            "shared_inputs": shared_inputs,
            "digest_mode": digest_mode,
            "course_type": resolve_digest_course_type(digest_mode),
            "retrieval_profile": resolve_planner_retrieval_profile(),
            "teaching_action": "plan_course",
            "tone": state.get("tone") or "encouraging",
        }

    return load_context_node


__all__ = ["build_load_context_node"]

