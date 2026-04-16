"""Prepare Digest material context for Planner V3."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from app.models.subject import Subject
from app.repositories.files_repo import list_raw_files_by_ids
from app.shared.infra.database import managed_session
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.lib.planner_events import emit_planner_event
from app.workflows.digest.planner.state import BuildPlannerState
from app.workflows.digest.common.contracts import resolve_planner_retrieval_profile
from app.workflows.digest.common.models import DigestMaterialContext, FastTopicHints, SourcePacket, SubjectProfile
from app.workflows.digest.common.prepare import prepare_material_context

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
        if stem:
            seeds.append(stem.replace("_", " ").replace("-", " ").strip())
    if subject and not _SUBJECT_SLUG_RE.fullmatch(subject.strip()):
        seeds.append(subject)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in seeds:
        text = item.strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        deduped.append(text)
        if len(deduped) >= 8:
            break
    return deduped


def _build_seed_material_context(*, subject: str, file_ids: list[int], user_goal: str | None) -> DigestMaterialContext:
    with managed_session() as session:
        raw_files = list_raw_files_by_ids(session, subject, file_ids)
        subject_row = session.query(Subject).filter(Subject.slug == subject).first()

    filenames = [raw_file.original_filename for raw_file in raw_files if raw_file.original_filename]
    topic_hints = _guess_topic_hints_from_filenames(filenames, subject=subject, user_goal=user_goal)
    discipline_counts = Counter(str(raw_file.detected_discipline).strip() for raw_file in raw_files if raw_file.detected_discipline)
    sub_discipline_counts = Counter(str(raw_file.detected_sub_discipline).strip() for raw_file in raw_files if raw_file.detected_sub_discipline)
    content_type_counts = Counter(str(raw_file.detected_content_type).strip() for raw_file in raw_files if raw_file.detected_content_type)

    source_documents = [
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

    return DigestMaterialContext(
        source_documents=source_documents,
        material_hints=FastTopicHints(chapter_candidates=topic_hints),
        learning_domain_profile=SubjectProfile(
            subject_slug=subject,
            subject_name=(subject_row.name or "").strip() if subject_row is not None else "",
            discipline=(discipline_counts.most_common(1)[0][0] if discipline_counts else ""),
            sub_discipline=(sub_discipline_counts.most_common(1)[0][0] if sub_discipline_counts else ""),
            content_type=(content_type_counts.most_common(1)[0][0] if content_type_counts else ""),
            key_topics=topic_hints,
        ),
    )


def build_prepare_material_context_node(*, context: WorkflowContext):
    async def prepare_material_context_node(state: BuildPlannerState) -> dict:
        await emit_planner_event(
            state,
            event="planner.material.loading",
            detail="正在读取学习目标和资料理解包...",
        )
        material_context = await prepare_material_context(
            state["subject"],
            state.get("file_ids", []),
            user_prompt=state.get("user_goal"),
        )
        if not material_context.source_documents:
            await emit_planner_event(
                state,
                event="planner.material.pending",
                detail="当前资料正文尚未解析完成，本轮将先依据文件名和用户目标生成临时方案。",
            )
            material_context = _build_seed_material_context(
                subject=state["subject"],
                file_ids=list(state.get("file_ids", [])),
                user_goal=state.get("user_goal"),
            )

        digest_mode = state.get("digest_mode") or material_context.course_mode_decision.mode.value
        await emit_planner_event(
            state,
            event="planner.material.ready",
            detail=(
                f"已读取 {len(material_context.source_documents)} 个资料文件，"
                f"整理 {len(material_context.material_sections)} 个内容片段。"
            ),
            payload={
                "source_count": len(material_context.source_documents),
                "section_count": len(material_context.material_sections),
                "topic_hints": list(material_context.material_hints.chapter_candidates[:8]),
            },
        )
        return {
            "material_context": material_context,
            "digest_mode": digest_mode,
            "retrieval_profile": resolve_planner_retrieval_profile(),
            "tone": state.get("tone") or "encouraging",
        }

    return prepare_material_context_node

__all__ = ["build_prepare_material_context_node"]
