"""Destructive upgrades are scoped, backed up, atomic, and idempotent."""

import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlmodel import Session, SQLModel, create_engine

from app.models import Course, ExamPaper, ExamPaperItem, QuestionTemplate, User, UserKnowledgeState
from app.models.knowledge_unit import KnowledgeUnit
from app.shared.infra.database import question_type_cleanup as cleanup
from app.shared.infra.database import core
from app.workflows.digest.docgen.lib import learner_profile
from app.workflows.profile.common.lib.course_profile import refresh_course_profile_summary
from app.workflows.profile.common.lib.user_profile import refresh_user_profile_summary


@pytest.fixture
def legacy_database(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")

    @sa.event.listens_for(engine, 'connect')
    def foreign_keys_on(connection, _record):
        connection.execute('PRAGMA foreign_keys=ON')

    SQLModel.metadata.create_all(engine)
    # Exercise the released legacy DDL, not a hand-written approximation of it.
    with engine.connect() as connection:
        connection.exec_driver_sql('PRAGMA foreign_keys=OFF')
        connection.commit()
        with Operations.context(MigrationContext.configure(connection)):
            for filename in ('20260907_0031_question_type_packages.py', '20260912_0032_question_type_runtime.py'):
                path = Path(__file__).parents[1] / 'migrations/versions' / filename
                spec = importlib.util.spec_from_file_location(filename[:-3], path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.upgrade()
        connection.commit()
        connection.exec_driver_sql('PRAGMA foreign_keys=ON')
        connection.commit()

    with Session(engine) as session:
        session.add(User(id='cleanup-user', username='cleanup-user'))
        session.commit()
        session.add(Course(id='cleanup-course', user_id='cleanup-user', name='保留课程'))
        session.commit()
        templates = [QuestionTemplate(
            id=i, course_id='cleanup-course', question_type=kind, difficulty='easy',
            stem=f'题目{i}', stem_hash=f'hash-{i}', answer='A', explanation='解析',
        ) for i, kind in ((1, 'single_choice'), (2, 'custom_test'))]
        papers = [ExamPaper(
            id=i, course_id='cleanup-course', user_id='cleanup-user', exam_mode='web_practice', status=status,
            config_snapshot_json=json.dumps(config),
        ) for i, status, config in (
            (1, 'graded', {}), (2, 'submitted', {}),
            (3, 'failed', {'question_type_runtimes': [{'type_key': 'custom_test'}]}),
            (4, 'ready', {'question_types': ['custom_test']}),
        )]
        session.add_all([*templates, *papers])
        session.commit()
        session.add_all([ExamPaperItem(
            id=i, exam_paper_id=paper, question_template_id=template, item_order=order,
            question_type=kind, difficulty='easy', stem_snapshot='题目', answer_snapshot='A', explanation_snapshot='解析',
            is_correct=True, score=1, score_obtained=1,
        ) for i, paper, template, kind, order in (
            (1, 1, 1, 'single_choice', 1), (2, 2, 2, 'custom_test', 1), (3, 2, 1, 'single_choice', 2),
        )])
        # The latest source can be normal while an older custom paper is still
        # present in the accumulated statistics.
        session.add(UserKnowledgeState(id=1, course_id='cleanup-course', user_id='cleanup-user',
                                       source_exam_paper_id=1, stats_json='{"consumed_exam_paper_ids":[1,2]}'))
        session.commit()
    yield engine
    engine.dispose()


def test_cleanup_preserves_builtins_removes_mixed_history_and_schedules_profile_replay(legacy_database):
    engine = legacy_database
    backup = cleanup.migrate_sqlite_question_types(engine)
    assert backup is not None and backup.is_file()
    with sqlite3.connect(backup) as original:
        assert original.execute('SELECT COUNT(*) FROM exam_paper').fetchone()[0] == 4
        assert original.execute('SELECT COUNT(*) FROM question_template').fetchone()[0] == 2
    with engine.connect() as connection:
        assert connection.exec_driver_sql('SELECT id FROM exam_paper').scalars().all() == [1]
        assert connection.exec_driver_sql('SELECT id FROM question_template').scalars().all() == [1]
        assert connection.exec_driver_sql('SELECT id FROM exam_paper_item').scalars().all() == [1]
        assert connection.exec_driver_sql('SELECT COUNT(*) FROM course').scalar_one() == 1
        assert connection.exec_driver_sql('SELECT COUNT(*) FROM user_knowledge_state').scalar_one() == 0
        assert connection.exec_driver_sql('SELECT exam_paper_id, status FROM exam_profile_sync').all() == [(1, 'pending')]
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar_one() == 1
    assert core._inspect_sqlite_schema_drift(engine) is None
    assert not set(cleanup.REMOVED_TABLES).intersection(sa.inspect(engine).get_table_names())
    assert cleanup.migrate_sqlite_question_types(engine) is None
    with Session(engine) as session:
        paper = ExamPaper(course_id='cleanup-course', user_id='cleanup-user', exam_mode='web_practice')
        template = QuestionTemplate(course_id='cleanup-course', question_type='short_answer', difficulty='easy',
                                    stem='新题', stem_hash='new', answer='A', explanation='解析')
        session.add_all([paper, template])
        session.commit()
        assert paper.id > 4 and template.id > 2


def test_cleanup_rolls_back_data_and_schema_on_failure(legacy_database, monkeypatch):
    with Session(legacy_database) as session:
        refresh_course_profile_summary(session, course_id='cleanup-course')
        refresh_user_profile_summary(session, user_id='cleanup-user')
        course_profile = session.get(Course, 'cleanup-course').profile_json
        user_profile = session.get(User, 'cleanup-user').profile_json

    def fail(*_args, **_kwargs):
        raise RuntimeError('injected schema failure')

    monkeypatch.setattr(Operations, 'batch_alter_table', fail)
    with pytest.raises(RuntimeError, match='injected schema failure'):
        cleanup.migrate_sqlite_question_types(legacy_database)
    with legacy_database.connect() as connection:
        assert connection.exec_driver_sql('SELECT COUNT(*) FROM exam_paper').scalar_one() == 4
        assert connection.exec_driver_sql('SELECT COUNT(*) FROM question_template').scalar_one() == 2
        assert connection.exec_driver_sql('SELECT COUNT(*) FROM user_knowledge_state').scalar_one() == 1
        assert connection.exec_driver_sql('SELECT COUNT(*) FROM exam_profile_sync').scalar_one() == 0
        assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar_one() == 1
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
    with Session(legacy_database) as session:
        assert session.get(Course, 'cleanup-course').profile_json == course_profile
        assert session.get(User, 'cleanup-user').profile_json == user_profile
    assert set(cleanup.REMOVED_TABLES).issubset(sa.inspect(legacy_database).get_table_names())


@pytest.mark.parametrize('has_remaining_graded_paper', [False, True])
@pytest.mark.parametrize('has_mastery_state', [False, True])
def test_cleanup_invalidates_affected_profile_caches(
    legacy_database, monkeypatch, has_remaining_graded_paper, has_mastery_state,
):
    engine = legacy_database
    untouched_profile = '{"unaffected": true}'
    with Session(engine) as session:
        session.add(User(id='other-user', username='other-user', profile_json=untouched_profile))
        session.add(KnowledgeUnit(
            id=1, course_id='cleanup-course', knowledge_unit_type='concept',
            canonical_name='Unit', normalized_name='unit', status='active',
        ))
        session.commit()
        session.add_all([
            Course(id='sibling-course', user_id='cleanup-user', name='同一用户的其他课程',
                   profile_json=untouched_profile),
            Course(id='other-course', user_id='other-user', name='其他用户课程',
                   profile_json=untouched_profile),
        ])
        state = session.get(UserKnowledgeState, 1)
        if has_mastery_state:
            state.knowledge_unit_id = 1
            state.mastery_score = 0.2
            state.total_attempts = 1
            state.review_status = 'pending'
            session.add(state)
        else:
            session.delete(state)
        if not has_remaining_graded_paper:
            paper = session.get(ExamPaper, 1)
            paper.config_snapshot_json = '{"question_types": ["custom_test"]}'
            session.add(paper)
        session.commit()
        refresh_course_profile_summary(session, course_id='cleanup-course')
        refresh_user_profile_summary(session, user_id='cleanup-user')

    # Read through the real DocGen consumer as well as checking persisted rows.
    monkeypatch.setattr(learner_profile, 'managed_session', lambda: Session(engine))
    assert learner_profile.load_docgen_learner_profile_context(course_id='cleanup-course')['has_profile']
    cleanup.migrate_sqlite_question_types(engine)

    with Session(engine) as session:
        assert session.get(Course, 'cleanup-course').profile_json == '{}'
        assert session.get(User, 'cleanup-user').profile_json == '{}'
        assert session.get(Course, 'sibling-course').profile_json == untouched_profile
        assert session.get(Course, 'other-course').profile_json == untouched_profile
        assert session.get(User, 'other-user').profile_json == untouched_profile
    context = learner_profile.load_docgen_learner_profile_context(course_id='cleanup-course')
    assert context['has_profile'] is False
    assert context['profile_text'] == ''
    assert context['course_profile'] == {}
    assert context['user_profile'] == {}
    with engine.connect() as connection:
        replay_count = connection.exec_driver_sql('SELECT COUNT(*) FROM exam_profile_sync').scalar_one()
        assert replay_count == int(has_remaining_graded_paper and has_mastery_state)


def test_fresh_database_has_no_retired_schema_or_cleanup_backup(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}")
    SQLModel.metadata.create_all(engine)
    assert cleanup.migrate_sqlite_question_types(engine) is None
    assert not (tmp_path / 'backups').exists()
    assert not set(cleanup.REMOVED_TABLES).intersection(sa.inspect(engine).get_table_names())
    engine.dispose()
