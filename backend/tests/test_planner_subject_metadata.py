import sqlalchemy as sa
from sqlmodel import Session, create_engine, select

from app.models.subject import Subject
from app.workflows.digest.common.models import DigestMaterialContext, SubjectProfile
from app.workflows.digest.planner.lib.store import (
    _build_subject_description_from_plan,
    _build_subject_user_intent_from_state,
    _maybe_update_subject_from_planner,
)


def _create_subject_table(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                CREATE TABLE subject (
                    id INTEGER PRIMARY KEY,
                    user_id VARCHAR NOT NULL,
                    slug VARCHAR NOT NULL,
                    name VARCHAR NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    user_intent TEXT NOT NULL DEFAULT '',
                    normalized_name VARCHAR,
                    preferred_digest_mode VARCHAR,
                    preferred_digest_note VARCHAR,
                    detected_discipline VARCHAR,
                    detected_sub_discipline VARCHAR,
                    profile_json VARCHAR NOT NULL DEFAULT '{}',
                    settings_json TEXT NOT NULL DEFAULT '{}',
                    learning_intent_text TEXT NOT NULL DEFAULT '',
                    subject_intro_text TEXT NOT NULL DEFAULT '',
                    document_summary_json JSON NOT NULL DEFAULT '{}',
                    llm_context_text TEXT NOT NULL DEFAULT '',
                    status VARCHAR NOT NULL DEFAULT 'active',
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    build_lock_holder VARCHAR,
                    build_lock_at DATETIME
                )
                """
            )
        )


def test_planner_builds_subject_description_from_profile_and_plan_summary():
    description = _build_subject_description_from_plan(
        {"plan_summary": "Review derivatives through common exam patterns."},
        material_context=DigestMaterialContext(
            learning_domain_profile=SubjectProfile(
                discipline="Math",
                sub_discipline="Calculus",
                key_topics=["Limit", "Derivative"],
            )
        ),
    )

    assert "Math > Calculus" in description
    assert "Limit" in description
    assert "Review derivatives" in description


def test_planner_uses_plan_intent_as_subject_user_intent():
    intent = _build_subject_user_intent_from_state(
        {
            "user_prompt": "fallback prompt",
            "plan_intent": {"plan_intent": "Prepare for a calculus exam with weak-point review."},
        }
    )

    assert intent == "Prepare for a calculus exam with weak-point review."


def test_planner_updates_subject_metadata_without_renaming_named_subject():
    engine = create_engine("sqlite://")
    _create_subject_table(engine)

    with Session(engine) as session:
        session.add(Subject(user_id="user-1", slug="subj_demo", name="Calculus"))
        session.commit()

        _maybe_update_subject_from_planner(
            session,
            subject="subj_demo",
            user_id="user-1",
            generated_name="Generated Title",
            description="  Calculus review plan.  ",
            user_intent="  Prepare for finals.  ",
        )

        subject = session.exec(select(Subject).where(Subject.slug == "subj_demo")).one()

    assert subject.name == "Calculus"
    assert subject.description == "Calculus review plan."
    assert subject.user_intent == "Prepare for finals."


def test_planner_auto_names_placeholder_subject_while_updating_metadata():
    engine = create_engine("sqlite://")
    _create_subject_table(engine)

    with Session(engine) as session:
        session.add(Subject(user_id="user-1", slug="subj_demo", name="untitled subject"))
        session.commit()

        _maybe_update_subject_from_planner(
            session,
            subject="subj_demo",
            user_id="user-1",
            generated_name="Calculus Sprint",
            description="Calculus sprint plan.",
            user_intent="Prepare with focused drills.",
        )

        subject = session.exec(select(Subject).where(Subject.slug == "subj_demo")).one()

    assert subject.name == "Calculus Sprint"
    assert subject.description == "Calculus sprint plan."
    assert subject.user_intent == "Prepare with focused drills."
