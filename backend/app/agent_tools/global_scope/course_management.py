"""Global course-management agent tool entrypoints."""

from __future__ import annotations

from app.agent_tools.result import AgentToolResult, ClientAction
from app.repositories.files_repo import link_raw_files_to_course
from app.shared.infra.database import managed_session
from app.shared.infra.tools.decorator import tool
from app.workflows.ingest.intake import get_user_files_or_raise
from app.workflows.support.courses import (
    create_course_record,
    infer_course_icon_key,
    schedule_course_icon_refinement,
)


@tool(
    "create_course_from_home_intake",
    "Create a new learning course from the homepage intake conversation after the user has confirmed.",
    usage=(
        "Use only after the user explicitly confirms creating a course or subject. "
        "Collect the course name, learning goal, optional planner prompt, and optional attached files first. "
        "Do not say the course has been created until this tool succeeds."
    ),
    tags=["global", "course", "write", "home_intake"],
    source="agent_tools.global_scope",
    risk_level="medium",
    scopes=["course:create", "files:link"],
    requires_approval=True,
    hidden_args=["user_id", "attached_file_ids", "background_task_registry"],
)
async def create_course_from_home_intake_tool(
    name: str,
    description: str = "",
    user_intent: str = "",
    planner_prompt: str = "",
    user_id: str | None = None,
    attached_file_ids: tuple[str, ...] | list[str] | None = None,
    background_task_registry: object | None = None,
) -> dict[str, object]:
    """Create a course and link selected user-library files."""

    owner_user_id = user_id or "local"
    course_name = (name or "").strip() or _fallback_course_name(user_intent, planner_prompt)
    file_ids = list(dict.fromkeys(str(item).strip() for item in (attached_file_ids or []) if str(item).strip()))

    with managed_session() as session:
        item = create_course_record(
            session,
            owner_user_id=owner_user_id,
            name=course_name,
            description=description,
            user_intent=user_intent or planner_prompt,
            icon_key=infer_course_icon_key(course_name),
        )
        if file_ids:
            raw_files = get_user_files_or_raise(
                session,
                owner_user_id=owner_user_id,
                file_ids=file_ids,
            )
            link_raw_files_to_course(
                session,
                owner_user_id=owner_user_id,
                course_id=item.course_id,
                raw_files=raw_files,
            )

    schedule_course_icon_refinement(
        background_task_registry,
        course_id=item.course_id,
        owner_user_id=owner_user_id,
        course_name=item.name,
    )
    result = AgentToolResult(
        ok=True,
        message=f"Created course {item.name}.",
        data={
            "course_id": item.course_id,
            "course_name": item.name,
            "linked_file_ids": file_ids,
            "planner_prompt": planner_prompt or user_intent,
        },
        client_actions=[
            ClientAction(
                type="open_build_planner",
                payload={
                    "course_id": item.course_id,
                    "initial_prompt": planner_prompt or user_intent,
                    "auto_start": bool(planner_prompt or user_intent),
                },
            )
        ],
        audit={"tool": "create_course_from_home_intake"},
    )
    return result.to_dict()


def _fallback_course_name(user_intent: str, planner_prompt: str) -> str:
    source = (user_intent or planner_prompt or "").strip()
    if not source:
        return "新学科"
    return source[:20]
