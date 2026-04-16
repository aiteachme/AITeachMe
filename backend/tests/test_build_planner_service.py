from __future__ import annotations

import asyncio
import re
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, select

from app.models import IngestStatus, RawFile, Subject, TaskStatus
from app.models.build_planner import BuildPlannerSession, ConfirmedBuildPlan
from app.schemas.knowledge import BuildPlannerCreateRequest, BuildPlannerMessageRequest
from app.workflows.digest.planner.sessions import (
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


class FailingWorkflowResult:
    def __init__(self, error: Exception):
        self._error = error

    def require_value(self):
        raise self._error


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
                "objective": f"理解 {title} 的核心内容。",
                "required_elements": ["清晰讲解", "典型例子"],
                "search_queries": [f"{subject} {title} 梳理"],
                "writing_instructions": "请按明确的教学步骤展开讲解。",
                "media_hints": {"images": [], "mermaid": [f"{title} 思维导图"], "interactive": []},
            }
        ],
        "research_queries": [f"{subject} {title} 梳理"],
        "media_plan": {"enable_mermaid": True, "enable_images": False, "enable_interactive_html": False},
        "build_constraints": {"include_exercises": True, "include_sources": True},
        "plan_summary": summary,
    }


def test_confirm_build_planner_session_creates_new_confirmed_plan_after_revision(session: Session) -> None:
    subject = _seed_subject(session, subject_slug="subj_planner_revision")
    _seed_ready_raw_file(session, subject_slug=subject.slug, uid="raw_plan_a")

    first_plan = _plan_payload(
        subject=subject.slug,
        goal="先生成第一版方案",
        digest_mode="systematic",
        tone="encouraging",
        title="核心概念",
        summary="第一版系统化构建方案，先梳理核心概念。",
    )
    revised_plan = _plan_payload(
        subject=subject.slug,
        goal="生成更聚焦考试重点的修订方案",
        digest_mode="systematic",
        tone="concise",
        title="考试抓分技巧",
        summary="根据用户反馈修订为更聚焦考试重点的系统化构建方案。",
    )

    with patch(
        "app.workflows.digest.planner.sessions.run_build_planner_workflow",
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
        "app.workflows.digest.planner.sessions.run_build_planner_workflow",
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
    assert "系统化构建方案" in confirmed_plans[0].plan_summary
    assert "系统" in confirmed_plans[1].plan_summary
    assert planner_session is not None
    assert planner_session.confirmed_plan_id == second_confirm.plan_id
    assert planner_session.status == "confirmed"


def test_create_build_planner_session_normalizes_dirty_workflow_payload(session: Session) -> None:
    subject = _seed_subject(session, subject_slug="subj_planner_normalize")
    _seed_ready_raw_file(session, subject_slug=subject.slug, uid="raw_plan_dirty")

    dirty_plan = {
        "subject": subject.slug,
        "user_goal": "考前快速复习",
        "digest_mode": "sprint",
        "tone": "encouraging",
        "chapter_plan": [
            {
                "chapter_index": 99,
                "title": "Chapter 1",
                "objective": "Explain basics in English",
                "required_elements": ["clear explanation"],
                "search_queries": [],
                "writing_instructions": "Explain the basics.",
                "media_hints": {},
            }
        ],
        "research_queries": [],
        "media_plan": {},
        "build_constraints": {},
        "plan_summary": "English summary only",
    }

    with patch(
        "app.workflows.digest.planner.sessions.run_build_planner_workflow",
        new=AsyncMock(return_value=DummyWorkflowResult({"plan": dirty_plan, "plan_summary": dirty_plan["plan_summary"]})),
    ):
        response = asyncio.run(
            create_build_planner_session_service(
                session,
                subject=subject,
                user_id="local",
                payload=BuildPlannerCreateRequest(user_goal="考前快速复习", digest_mode="sprint"),
            )
        )

    planner_session = session.get(BuildPlannerSession, response.session_id)
    titles = [chapter.title for chapter in response.plan.chapter_plan]

    assert response.plan.digest_mode == "sprint"
    assert 3 <= len(response.plan.chapter_plan) <= 6
    assert all("：" in title for title in titles)
    assert all(not re.fullmatch(r"第\s*\d+\s*章", title) for title in titles)
    assert response.plan.build_constraints["target_chapter_count"] == len(response.plan.chapter_plan)
    assert "fixed_chapter_count" not in response.plan.build_constraints
    assert "冲刺型知识文档" in response.plan.plan_summary
    assert planner_session is not None
    assert planner_session.latest_plan_json is not None
    assert "：" in planner_session.latest_plan_json["chapter_plan"][0]["title"]
    assert planner_session.latest_summary == response.plan.plan_summary


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


def test_create_build_planner_session_exposes_runtime_stats(session: Session) -> None:
    subject = _seed_subject(session, subject_slug="subj_planner_runtime")
    _seed_ready_raw_file(session, subject_slug=subject.slug, uid="raw_plan_runtime")

    plan = _plan_payload(
        subject=subject.slug,
        goal="生成更快的规划方案",
        digest_mode="systematic",
        tone="encouraging",
        title="极限与连续",
        summary="围绕极限与连续整理一份系统化知识文档方案。",
    )
    workflow_state = {
        "plan": plan,
        "plan_summary": plan["plan_summary"],
        "plan_sketch_markdown": "# 构建方案\n\n> 模式：systematic\n> 一句话摘要：围绕极限与连续整理一份系统化知识文档方案。\n\n## 研究任务\n1. 梳理极限与连续的核心概念\n",
        "workflow_elapsed_ms": 345,
        "prepare_ms": 32,
        "compose_ms": 180,
        "finalize_ms": 100,
        "planner_generation_mode": "deep_research_v3",
    }

    with patch(
        "app.workflows.digest.planner.sessions.run_build_planner_workflow",
        new=AsyncMock(return_value=DummyWorkflowResult(workflow_state)),
    ):
        response = asyncio.run(
            create_build_planner_session_service(
                session,
                subject=subject,
                user_id="local",
                payload=BuildPlannerCreateRequest(user_goal="生成更快的规划方案"),
            )
        )

    assert response.runtime_stats is not None
    assert response.runtime_stats.elapsed_ms == 345
    assert response.runtime_stats.steps[0].name == "prepare_material_context"
    assert response.runtime_stats.steps[0].elapsed_ms == 32
    assert response.runtime_stats.steps[1].name == "compose_plan_contract"
    assert response.runtime_stats.steps[1].elapsed_ms == 180
    assert response.runtime_stats.steps[2].name == "finalize_plan_contract"
    assert response.runtime_stats.steps[2].elapsed_ms == 100
    assert response.runtime_stats.generation_mode == "deep_research_v3"
    assert [step.name for step in response.runtime_stats.steps] == [
        "prepare_material_context",
        "compose_plan_contract",
        "finalize_plan_contract",
    ]
    assert response.turns[-1].content.startswith("# 构建方案")


def test_create_build_planner_session_marks_session_failed_when_workflow_result_fails(session: Session) -> None:
    subject = _seed_subject(session, subject_slug="subj_planner_create_failed")
    _seed_ready_raw_file(session, subject_slug=subject.slug, uid="raw_plan_create_failed")

    with patch(
        "app.workflows.digest.planner.sessions.run_build_planner_workflow",
        new=AsyncMock(return_value=FailingWorkflowResult(RuntimeError("planner llm failed"))),
    ):
        with pytest.raises(RuntimeError, match="planner llm failed"):
            asyncio.run(
                create_build_planner_session_service(
                    session,
                    subject=subject,
                    user_id="local",
                    payload=BuildPlannerCreateRequest(user_goal="create should fail"),
                )
            )

    planner_sessions = list(
        session.exec(
            select(BuildPlannerSession).where(BuildPlannerSession.subject == subject.slug)
        ).all()
    )

    assert len(planner_sessions) == 1
    assert planner_sessions[0].status == "failed"
    assert planner_sessions[0].latest_plan_json is None


def test_append_build_planner_message_marks_session_failed_when_workflow_result_fails(session: Session) -> None:
    subject = _seed_subject(session, subject_slug="subj_planner_append_failed")
    _seed_ready_raw_file(session, subject_slug=subject.slug, uid="raw_plan_append_failed")

    plan = _plan_payload(
        subject=subject.slug,
        goal="先创建一版方案",
        digest_mode="systematic",
        tone="encouraging",
        title="基础概念",
        summary="先创建一版可编辑方案。",
    )

    with patch(
        "app.workflows.digest.planner.sessions.run_build_planner_workflow",
        new=AsyncMock(return_value=DummyWorkflowResult({"plan": plan, "plan_summary": plan["plan_summary"]})),
    ):
        created = asyncio.run(
            create_build_planner_session_service(
                session,
                subject=subject,
                user_id="local",
                payload=BuildPlannerCreateRequest(user_goal="先创建一版方案"),
            )
        )

    with patch(
        "app.workflows.digest.planner.sessions.run_build_planner_workflow",
        new=AsyncMock(return_value=FailingWorkflowResult(RuntimeError("planner append llm failed"))),
    ):
        with pytest.raises(RuntimeError, match="planner append llm failed"):
            asyncio.run(
                append_build_planner_message_service(
                    session,
                    subject=subject,
                    user_id="local",
                    session_id=created.session_id,
                    payload=BuildPlannerMessageRequest(message="请继续优化"),
                )
            )

    planner_session = session.get(BuildPlannerSession, created.session_id)

    assert planner_session is not None
    assert planner_session.status == "failed"
    assert planner_session.latest_plan_json is not None
