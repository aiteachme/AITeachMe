from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from sqlmodel import Session, select

from app.models import IngestStatus, RawFile, Subject, TaskStatus
from app.models.build_planner import BuildPlannerSession, ConfirmedBuildPlan
from app.schemas.knowledge import BuildPlannerCreateRequest, BuildPlannerMessageRequest
from app.services.knowledge.build_planner_service import (
    append_build_planner_message_service,
    confirm_build_planner_session_service,
    create_build_planner_session_service,
    mark_confirmed_build_plan_status,
)


class DummyWorkflowResult:
    def __init__(self, value):
        self._value = value

    def require_value(self):
        return self._value


def _seed_subject(session: Session, *, subject_slug: str) -> Subject:
    subject = Subject(user_id="local", slug=subject_slug, name="Test Subject")
    session.add(subject)
    session.commit()
    session.refresh(subject)
    return subject


def _seed_ready_raw_file(session: Session, *, subject_slug: str, uid: str) -> RawFile:
    raw_file = RawFile(
        uid=uid,
        subject=subject_slug,
        filename=f"{uid}.md",
        filetype="md",
        file_path=f"/tmp/{uid}.md",
        status=TaskStatus.COMPLETED.value,
        ingest_status=IngestStatus.READY_FOR_DIGEST.value,
        markdown_content=f"# {uid}\n\nSample content for {uid}",
    )
    session.add(raw_file)
    session.commit()
    session.refresh(raw_file)
    return raw_file


def _plan_payload(*, subject: str, goal: str, digest_mode: str, tone: str, title: str, summary: str) -> dict:
    return {
        "subject": subject,
        "user_goal": goal,
        "digest_mode": digest_mode,
        "tone": tone,
        "chapter_plan": [
            {
                "chapter_index": 1,
                "title": title,
                "objective": f"Understand {title}",
                "required_elements": ["clear explanation", "examples"],
                "search_queries": [f"{subject} {title} overview"],
                "writing_instructions": "Explain with explicit teaching steps.",
                "media_hints": {"images": [], "mermaid": [f"{title} concept map"], "interactive": []},
            }
        ],
        "research_queries": [f"{subject} {title} overview"],
        "media_plan": {"enable_mermaid": True, "enable_images": False, "enable_interactive_html": False},
        "build_constraints": {"include_exercises": True, "include_sources": True},
        "plan_summary": summary,
    }


def test_confirm_build_planner_session_creates_new_confirmed_plan_after_revision(session: Session) -> None:
    subject = _seed_subject(session, subject_slug="subj_planner_revision")
    _seed_ready_raw_file(session, subject_slug=subject.slug, uid="raw_plan_a")

    first_plan = _plan_payload(
        subject=subject.slug,
        goal="Build a first draft",
        digest_mode="systematic",
        tone="encouraging",
        title="Core concepts",
        summary="First confirmed plan.",
    )
    revised_plan = _plan_payload(
        subject=subject.slug,
        goal="Build a refined draft",
        digest_mode="sprint",
        tone="concise",
        title="Exam shortcuts",
        summary="Revised plan after user feedback.",
    )

    with patch(
        "app.services.knowledge.build_planner_service.run_build_planner_workflow",
        new=AsyncMock(return_value=DummyWorkflowResult({"plan": first_plan, "plan_summary": first_plan["plan_summary"]})),
    ):
        create_response = asyncio.run(
            create_build_planner_session_service(
                session,
                subject=subject,
                user_id="local",
                payload=BuildPlannerCreateRequest(user_goal="Build a first draft"),
            )
        )

    first_confirm = confirm_build_planner_session_service(
        session,
        subject=subject,
        user_id="local",
        session_id=create_response.session_id,
    )

    with patch(
        "app.services.knowledge.build_planner_service.run_build_planner_workflow",
        new=AsyncMock(return_value=DummyWorkflowResult({"plan": revised_plan, "plan_summary": revised_plan["plan_summary"]})),
    ):
        revised_response = asyncio.run(
            append_build_planner_message_service(
                session,
                subject=subject,
                user_id="local",
                session_id=create_response.session_id,
                payload=BuildPlannerMessageRequest(message="Please focus more on exam-oriented shortcuts."),
            )
        )

    second_confirm = confirm_build_planner_session_service(
        session,
        subject=subject,
        user_id="local",
        session_id=create_response.session_id,
    )

    confirmed_plans = list(
        session.exec(
            select(ConfirmedBuildPlan)
            .where(ConfirmedBuildPlan.subject == subject.slug)
            .order_by(ConfirmedBuildPlan.created_at.asc())
        ).all()
    )
    planner_session = session.get(BuildPlannerSession, create_response.session_id)

    assert first_confirm.plan_id != second_confirm.plan_id
    assert revised_response.status == "draft"
    assert revised_response.plan.confirmed_plan_id is None
    assert [plan.id for plan in confirmed_plans] == [first_confirm.plan_id, second_confirm.plan_id]
    assert confirmed_plans[0].plan_summary == "First confirmed plan."
    assert confirmed_plans[1].plan_summary == "Revised plan after user feedback."
    assert planner_session is not None
    assert planner_session.confirmed_plan_id == second_confirm.plan_id
    assert planner_session.status == "confirmed"


def test_mark_confirmed_build_plan_status_keeps_newer_session_binding(session: Session) -> None:
    subject = _seed_subject(session, subject_slug="subj_plan_status")
    planner_session = BuildPlannerSession(
        id="planner-status-session",
        subject=subject.slug,
        user_id="local",
        title="Planner Session",
        status="draft",
        user_goal="Current draft goal",
        digest_mode="systematic",
        tone="encouraging",
        selected_file_ids_json=[],
        latest_plan_json={},
    )
    session.add(planner_session)
    session.commit()
    session.refresh(planner_session)

    older_plan = ConfirmedBuildPlan(
        id="plan-old",
        subject=subject.slug,
        planner_session_id=planner_session.id,
        user_id="local",
        status="building",
        user_goal="Old plan",
        digest_mode="systematic",
        tone="encouraging",
    )
    newer_plan = ConfirmedBuildPlan(
        id="plan-new",
        subject=subject.slug,
        planner_session_id=planner_session.id,
        user_id="local",
        status="confirmed",
        user_goal="New plan",
        digest_mode="sprint",
        tone="concise",
    )
    session.add(older_plan)
    session.add(newer_plan)
    session.commit()

    planner_session.confirmed_plan_id = newer_plan.id
    planner_session.status = "draft"
    session.add(planner_session)
    session.commit()

    mark_confirmed_build_plan_status(
        session,
        subject=subject.slug,
        user_id="local",
        plan_id=older_plan.id,
        status="completed",
    )

    session.refresh(planner_session)
    session.refresh(older_plan)

    assert older_plan.status == "completed"
    assert planner_session.confirmed_plan_id == newer_plan.id
    assert planner_session.status == "draft"
