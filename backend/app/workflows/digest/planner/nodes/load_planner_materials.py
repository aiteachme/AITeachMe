"""Load persisted planner session data and parsed source materials."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import structlog

from app.repositories.files_repo import list_raw_files_by_ids
from app.shared.infra.database import managed_session
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.common.material_digest import build_material_digest
from app.workflows.digest.common.models import DigestMaterialContext, FastTopicHints, SourcePacket, CourseProfile
from app.workflows.digest.common.prepare import prepare_material_context as build_digest_material_context
from app.workflows.digest.planner.lib.planner_events import emit_planner_event
from app.workflows.digest.planner.lib.store import prepare_planner_run
from app.workflows.digest.planner.state import BuildPlannerState

_COURSE_ID_RE = re.compile(r"^(?:course|subj)_[a-z0-9]+$", re.IGNORECASE)
logger = structlog.get_logger(__name__)


def _seed_titles_from_goal_and_files(
    filenames: list[str],
    *,
    course_id: str,
    user_prompt: str | None,
) -> list[str]:
    seeds: list[str] = []
    if user_prompt and user_prompt.strip():
        seeds.append(user_prompt.strip())
    for filename in filenames:
        stem = Path(filename).stem.strip()
        if stem:
            seeds.append(stem.replace("_", " ").replace("-", " ").strip())
    if course_id and not _COURSE_ID_RE.fullmatch(course_id.strip()):
        seeds.append(course_id)

    titles: list[str] = []
    seen: set[str] = set()
    for item in seeds:
        text = item.strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        titles.append(text)
    return titles


def _build_seed_material_context(*, course_id: str, file_ids: list[str], user_prompt: str | None) -> DigestMaterialContext:
    with managed_session() as session:
        raw_files = list_raw_files_by_ids(session, course_id, file_ids)

    filenames = [raw_file.original_filename for raw_file in raw_files if raw_file.original_filename]
    seed_titles = _seed_titles_from_goal_and_files(filenames, course_id=course_id, user_prompt=user_prompt)
    discipline_counts = Counter(str(raw_file.detected_discipline).strip() for raw_file in raw_files if raw_file.detected_discipline)
    sub_discipline_counts = Counter(str(raw_file.detected_sub_discipline).strip() for raw_file in raw_files if raw_file.detected_sub_discipline)
    content_type_counts = Counter(str(raw_file.detected_content_type).strip() for raw_file in raw_files if raw_file.detected_content_type)

    source_documents = [
        SourcePacket(
            file_id=raw_file.id,
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
        material_hints=FastTopicHints(chapter_candidates=seed_titles),
        learning_domain_profile=CourseProfile(
            course_id=course_id,
            course_name="",
            discipline=(discipline_counts.most_common(1)[0][0] if discipline_counts else ""),
            sub_discipline=(sub_discipline_counts.most_common(1)[0][0] if sub_discipline_counts else ""),
            content_type=(content_type_counts.most_common(1)[0][0] if content_type_counts else ""),
            key_topics=seed_titles,
        ),
    )


def build_load_planner_materials_node(*, context: WorkflowContext):
    """构建 Planner 资料准备节点。

    负责把 API create/append 输入转成统一的 material_context。它会读取
    或创建 planner session，选择本轮可用资料，并为后续意图识别和大纲
    合成提供轻量资料摘要。
    """

    async def load_planner_materials_node(state: BuildPlannerState) -> dict:
        """读取 Planner 会话状态和资料理解包。"""

        logger.info(
            "planner_load_materials_started",
            planner_session_id=state.get("planner_session_id", ""),
            course_id=state.get("course_id", ""),
            operation=state.get("planner_operation", ""),
            file_id_count=len(state.get("file_ids", []) or []),
            requested_file_id_count=len(state.get("requested_file_ids", []) or []),
        )
        session_update = prepare_planner_run(state)
        working_state = {**state, **session_update}
        logger.info(
            "planner_load_materials_session_prepared",
            planner_session_id=working_state.get("planner_session_id", ""),
            selected_file_id_count=len(working_state.get("selected_file_ids", []) or []),
            workflow_file_id_count=len(working_state.get("file_ids", []) or []),
            message_count=len(working_state.get("message_history", []) or []),
            has_latest_plan=bool(working_state.get("latest_plan")),
        )
        await emit_planner_event(
            working_state,
            event="planner.material.loading",
            detail="正在读取学习目标和资料理解包...",
        )
        material_context = await build_digest_material_context(
            working_state["course_id"],
            working_state.get("file_ids", []),
            user_prompt=working_state.get("user_prompt"),
        )
        logger.info(
            "planner_load_materials_context_loaded",
            planner_session_id=working_state.get("planner_session_id", ""),
            source_document_count=len(material_context.source_documents),
            section_count=len(material_context.material_sections),
            digest_chars=len(material_context.material_digest or ""),
        )
        if not material_context.source_documents:
            # 刚上传后 parsed markdown 可能还没准备好。seed context 让 planner
            # 至少可以基于文件名和用户提示先给出临时方案。
            await emit_planner_event(
                working_state,
                event="planner.material.pending",
                detail="当前资料正文尚未解析完成，本轮将先依据文件名和用户提示生成临时方案。",
            )
            material_context = _build_seed_material_context(
                course_id=working_state["course_id"],
                file_ids=list(working_state.get("file_ids", [])),
                user_prompt=working_state.get("user_prompt"),
            )
            logger.warning(
                "planner_load_materials_seed_context_used",
                planner_session_id=working_state.get("planner_session_id", ""),
                source_document_count=len(material_context.source_documents),
                seed_titles=list(material_context.material_hints.chapter_candidates),
            )

        digest_mode = working_state.get("digest_mode") or material_context.course_mode_decision.mode.value
        if material_context.source_documents:
            await emit_planner_event(
                working_state,
                event="planner.context.started",
                detail="正在拼接资料上下文...",
            )
            digest_result = await build_material_digest(material_context)
            material_context = material_context.model_copy(update={"material_digest": digest_result.digest})
            logger.info(
                "planner_load_materials_digest_ready",
                planner_session_id=working_state.get("planner_session_id", ""),
                total_chars=digest_result.total_chars,
                total_tokens=digest_result.total_tokens,
                source_count=digest_result.source_count,
            )
            await emit_planner_event(
                working_state,
                event="planner.context.ready",
                detail=(
                    f"资料上下文已拼接（{digest_result.source_count} 份资料，"
                    "已完整交给 Planner）。"
                ),
                payload={
                    "total_chars": digest_result.total_chars,
                    "total_tokens": digest_result.total_tokens,
                    "source_count": digest_result.source_count,
                },
            )

        await emit_planner_event(
            working_state,
            event="planner.material.ready",
            detail=(
                f"已读取 {len(material_context.source_documents)} 个资料文件，"
                f"整理 {len(material_context.material_sections)} 个内容片段。"
            ),
            payload={
                "source_count": len(material_context.source_documents),
                "section_count": len(material_context.material_sections),
            },
        )
        result = {
            **session_update,
            "material_context": material_context,
            "digest_mode": digest_mode,
        }
        logger.info(
            "planner_load_materials_completed",
            planner_session_id=working_state.get("planner_session_id", ""),
            digest_mode=digest_mode,
            material_digest_chars=len(material_context.material_digest or ""),
        )
        return result

    return load_planner_materials_node


__all__ = ["build_load_planner_materials_node"]
