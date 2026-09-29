"""Persistence and catalog contracts for P1 question-type package imports."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import shutil
from datetime import timedelta
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.models  # noqa: F401 - register all tables before create_all
from app.models import (
    Course,
    QuestionTypePackageAsset,
    QuestionTypePackageImport,
    QuestionTypePackageVersion,
    QuestionTypeRegistry,
    User,
)
from app.shared.infra.exceptions import AITeachMeError
from app.utils.time import utcnow
from app.workflows.support.question_type_packages import (
    build_atqskill_archive,
    validate_atqskill,
)
from app.workflows.support.question_type_packages.installer import (
    create_pending_import,
    get_question_type_asset,
    install_pending_import,
    list_question_type_catalog,
    update_question_type_catalog_item,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_ROOT = REPOSITORY_ROOT / "examples" / "question-type-skills"
LEGACY_EXAMPLE_ROOT = Path(__file__).parent / "fixtures" / "question_type_packages" / "v1"
COURSE_ID = "course_questiontypes01"
USER_ID = "question-type-user"


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add(User(id=USER_ID, username=USER_ID))
        db.add(Course(id=COURSE_ID, user_id=USER_ID, name="题型包测试课程"))
        db.commit()
        yield db


def _build_example(tmp_path: Path, *, version: str = "1.0.1", suffix: str = "") -> Path:
    source = tmp_path / f"source{suffix}"
    shutil.copytree(LEGACY_EXAMPLE_ROOT / "feynman_explanation", source)
    skill_path = source / "SKILL.md"
    skill_text = skill_path.read_text(encoding="utf-8")
    skill_text = re.sub(
        r"(?m)^version:[^\S\r\n]*\S+[^\S\r\n]*$",
        f"version: {version}",
        skill_text,
        count=1,
    )
    if suffix:
        skill_text = skill_text.replace(
            "要求学习者用自己的语言解释概念、依据、例子和适用边界。",
            f"要求学习者用自己的语言解释概念、依据、例子和适用边界。{suffix}",
        )
    skill_path.write_text(skill_text, encoding="utf-8")
    return build_atqskill_archive(source, tmp_path / f"feynman-{version}{suffix}.atqskill")


def _preview_and_install(
    session: Session,
    package: Path,
    *,
    set_current: bool = True,
):
    result = validate_atqskill(package)
    record, preview = create_pending_import(
        session,
        course_id=COURSE_ID,
        user_id=USER_ID,
        original_filename=package.name,
        archive_bytes=package.read_bytes(),
        result=result,
    )
    assert record is not None
    installed = install_pending_import(
        session,
        course_id=COURSE_ID,
        user_id=USER_ID,
        import_id=record.id,
        set_current=set_current,
    )
    return record, preview, installed


def test_published_package_installs_as_active_catalog_item(
    session: Session,
    tmp_path: Path,
) -> None:
    package = _build_example(tmp_path)

    record, preview, installed = _preview_and_install(session, package)

    assert preview.valid is True
    assert preview.import_id == record.id
    assert preview.conflict == "none"
    assert preview.runtime_ready is True
    assert installed.status == "active"
    assert installed.runtime_ready is True
    assert record.status == "installed"
    assert record.archive_base64 == ""
    assert record.compiled_definition_json == "{}"

    registry = session.get(QuestionTypeRegistry, installed.registry_id)
    version = session.get(QuestionTypePackageVersion, installed.version_id)
    assert registry is not None
    assert registry.is_active is True
    assert registry.source == "upload"
    assert version is not None
    assert version.profile_eligible is False
    assert '"prompts"' in version.compiled_definition_json

    catalog = list_question_type_catalog(session, course_id=COURSE_ID)
    custom = next(item for item in catalog if item.type_key == "custom_feynman_explanation")
    assert custom.current_version == "1.0.1"
    assert custom.runtime_ready is True
    assert custom.answer_fields[0].key == "explanation"
    assert "prompts" not in custom.model_dump(mode="json")
    assert "reference_cases" not in custom.model_dump(mode="json")


def test_mixed_selection_freezes_explicit_versions_and_rejects_disabled_packages(session: Session, tmp_path: Path) -> None:
    from app.schemas.exams import QuestionTypeSelection
    from app.workflows.examine.question_types.selection import resolve_question_type_selection
    from app.workflows.examine.question_types.runtime import QuestionTypeRuntimeError, resolve_question_type_version
    installed = []
    for name in ["experiment_design", "case_analysis"]:
        package = build_atqskill_archive(EXAMPLE_ROOT / name, tmp_path / f"{name}.atqskill")
        installed.append(_preview_and_install(session, package)[2])
    selected = [QuestionTypeSelection(question_type="single_choice", count=2), *[
        QuestionTypeSelection(registry_id=item.registry_id, version_id=item.version_id, count=1) for item in installed
    ]]
    kwargs = dict(course_id=COURSE_ID, mode="paper_exam", question_count=4, selections=selected, legacy_types=[], legacy_registry_ids=[])
    types, runtimes, counts = resolve_question_type_selection(session, **kwargs)
    assert types == ["single_choice", "custom_experiment_design", "custom_case_analysis"]
    assert list(counts.values()) == [2, 1, 1]
    assert all(not runtime.profile_eligible for runtime in runtimes)
    assert [runtime.version_id for runtime in runtimes] == [item.version_id for item in installed]
    frozen = runtimes[0].definition.model_dump_json()
    registry = session.get(QuestionTypeRegistry, installed[0].registry_id)
    registry.status = "inactive"
    registry.is_active = False
    session.flush()
    with pytest.raises(QuestionTypeRuntimeError, match="停用"):
        resolve_question_type_selection(session, **kwargs)
    # Already-started exams replay the pinned version independently of activation.
    historical = resolve_question_type_version(session, course_id=COURSE_ID, version_id=installed[0].version_id, mode="paper_exam")
    assert historical.definition.model_dump_json() == frozen
    assert resolve_question_type_selection(session, course_id=COURSE_ID, mode="web_practice", question_count=10, selections=[], legacy_types=[], legacy_registry_ids=[]) == ([], [], {})


def test_repeat_install_is_idempotent_and_same_version_change_conflicts(
    session: Session,
    tmp_path: Path,
) -> None:
    package = _build_example(tmp_path)
    _first_record, _preview, first = _preview_and_install(session, package)

    duplicate_result = validate_atqskill(package)
    duplicate_record, duplicate_preview = create_pending_import(
        session,
        course_id=COURSE_ID,
        user_id=USER_ID,
        original_filename=package.name,
        archive_bytes=package.read_bytes(),
        result=duplicate_result,
    )
    assert duplicate_record is not None
    assert duplicate_preview.conflict == "already_installed"
    duplicate = install_pending_import(
        session,
        course_id=COURSE_ID,
        user_id=USER_ID,
        import_id=duplicate_record.id,
    )
    assert duplicate.already_installed is True
    assert duplicate.version_id == first.version_id

    changed = _build_example(tmp_path, suffix="-changed")
    changed_result = validate_atqskill(changed)
    changed_record, changed_preview = create_pending_import(
        session,
        course_id=COURSE_ID,
        user_id=USER_ID,
        original_filename=changed.name,
        archive_bytes=changed.read_bytes(),
        result=changed_result,
    )
    assert changed_record is not None
    assert changed_preview.conflict == "version_conflict"
    with pytest.raises(AITeachMeError) as error:
        install_pending_import(
            session,
            course_id=COURSE_ID,
            user_id=USER_ID,
            import_id=changed_record.id,
        )
    assert error.value.error_code == "QUESTION_TYPE_VERSION_CONFLICT"


def test_upgraded_disabled_package_keeps_old_nonblank_pass_decision(
    session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same 65% answer passes the old 60% rule and fails the new 70% rule."""
    from app.api.exams import _custom_runtime_persistence_payload
    from app.models import ExamPaper, ExamPaperItem, QuestionTemplate
    from app.workflows.examine.exam_grade.lib import grader
    from app.workflows.examine.question_types.runtime import resolve_question_type_version

    _record, _preview, old_install = _preview_and_install(session, _build_example(tmp_path))
    answer = "相关性不等于因果；随机分组可以减少分组前的混杂，但小样本仍可能不平衡，需要对照和独立重复。"
    reference = "随机分组能减少分组前混杂；对照与独立重复帮助评估处理效果，小样本不保证两组完全平衡。"

    def persist_paper(installed):
        runtime = resolve_question_type_version(
            session, course_id=COURSE_ID, version_id=installed.version_id, mode="web_practice",
        )
        frozen = _custom_runtime_persistence_payload(runtime.workflow_payload(), answer=reference)
        template = QuestionTemplate(
            course_id=COURSE_ID, question_type=runtime.type_key,
            question_type_registry_id=installed.registry_id, question_type_version_id=installed.version_id,
            difficulty="medium", stem="解释随机分组与因果推断。", stem_hash=f"version-{installed.version_id}",
            answer=reference, explanation="说明随机分组的作用及其限制。",
        )
        paper = ExamPaper(course_id=COURSE_ID, user_id=USER_ID, exam_mode="web_practice", status="ready")
        session.add_all([template, paper])
        session.flush()
        item = ExamPaperItem(
            exam_paper_id=paper.id, question_template_id=template.id, item_order=1,
            question_type_registry_id=installed.registry_id, question_type_version_id=installed.version_id,
            question_type=runtime.type_key, difficulty="medium", score=5,
            stem_snapshot=template.stem, answer_snapshot=reference, explanation_snapshot=template.explanation,
            answer_schema_snapshot_json=json.dumps(frozen["answer_schema"]),
            reference_answer_snapshot_json=json.dumps(frozen["reference_answer"]),
            grading_spec_snapshot_json=json.dumps(frozen["grading_spec"]),
            runtime_snapshot_json=json.dumps(frozen["runtime_snapshot"]),
            answer_content=answer, answer_payload_json=json.dumps({"explanation": answer}),
            profile_eligible=False,
        )
        session.add(item)
        session.commit()
        return item.id

    old_item_id = persist_paper(old_install)
    old_snapshot = session.get(ExamPaperItem, old_item_id).grading_spec_snapshot_json
    source = tmp_path / "upgraded-source"
    shutil.copytree(LEGACY_EXAMPLE_ROOT / "feynman_explanation", source)
    skill = source / "SKILL.md"
    skill.write_text(skill.read_text("utf-8").replace("version: 1.0.1", "version: 1.1.0").replace("pass_score: 0.6", "pass_score: 0.7"), encoding="utf-8")
    _record, _preview, new_install = _preview_and_install(
        session, build_atqskill_archive(source, tmp_path / "upgrade.atqskill"),
    )
    new_item_id = persist_paper(new_install)
    update_question_type_catalog_item(
        session, course_id=COURSE_ID, registry_id=old_install.registry_id,
        status="inactive", current_version_id=None,
    )
    session.expire_all()
    old_item = session.get(ExamPaperItem, old_item_id)
    new_item = session.get(ExamPaperItem, new_item_id)
    registry = session.get(QuestionTypeRegistry, old_install.registry_id)
    assert not registry.is_active
    assert session.get(QuestionTypePackageVersion, new_install.version_id).is_current
    assert not session.get(QuestionTypePackageVersion, old_install.version_id).is_current

    async def same_partial_answer_grade(*_args, **_kwargs):
        return grader.CustomRubricGradePayload(
            criteria=[{
                "key": key, "score_ratio": 0.65,
                "evidence": [{"field_key": "explanation", "quote": "相关性不等于因果"}],
            } for key in ("accuracy", "reasoning", "example", "boundary")],
            feedback_text="部分理解，需要补充具体例子及更完整的解释。",
        )

    monkeypatch.setattr(grader, "acompletion_with_fallback", same_partial_answer_grade)
    old_grade, new_grade = asyncio.run(grader.grade_exam_items_with_workflow(
        course_name="实验方法", items=[old_item, new_item],
    ))
    assert old_grade.score_obtained == new_grade.score_obtained == pytest.approx(3.25)
    assert old_grade.is_correct is True and new_grade.is_correct is False
    assert old_grade.grading_detail["pass_score"] == 0.6
    assert new_grade.grading_detail["pass_score"] == 0.7
    assert old_item.grading_spec_snapshot_json == old_snapshot


def test_new_published_version_can_switch_current_and_remain_active(
    session: Session,
    tmp_path: Path,
) -> None:
    _record, _preview, first = _preview_and_install(session, _build_example(tmp_path))
    _record2, preview2, second = _preview_and_install(
        session,
        _build_example(tmp_path, version="1.1.0", suffix="-v2"),
        set_current=False,
    )
    assert preview2.conflict == "new_version"

    catalog = list_question_type_catalog(session, course_id=COURSE_ID)
    custom = next(item for item in catalog if item.id == first.registry_id)
    assert custom.current_version_id == first.version_id
    assert len(custom.versions) == 2

    updated = update_question_type_catalog_item(
        session,
        course_id=COURSE_ID,
        registry_id=first.registry_id,
        status=None,
        current_version_id=second.version_id,
    )
    assert updated.current_version_id == second.version_id
    assert sum(1 for item in updated.versions if item.is_current) == 1

    activated = update_question_type_catalog_item(
        session,
        course_id=COURSE_ID,
        registry_id=first.registry_id,
        status="active",
        current_version_id=None,
    )
    assert activated.status == "active"
    assert activated.runtime_ready is True


@pytest.mark.parametrize("status", ["inactive", "archived"])
def test_switching_current_version_preserves_disabled_status(
    session: Session,
    tmp_path: Path,
    status: str,
) -> None:
    record, _preview, first = _preview_and_install(session, _build_example(tmp_path))
    _record2, _preview2, second = _preview_and_install(
        session,
        _build_example(tmp_path, version="1.1.0", suffix="-v2"),
        set_current=False,
    )
    disabled = update_question_type_catalog_item(
        session,
        course_id=COURSE_ID,
        registry_id=first.registry_id,
        status=status,
        current_version_id=None,
    )
    assert disabled.status == status
    assert disabled.is_active is False

    updated = update_question_type_catalog_item(
        session,
        course_id=COURSE_ID,
        registry_id=first.registry_id,
        status=None,
        current_version_id=second.version_id,
    )

    assert updated.current_version_id == second.version_id
    assert updated.status == status
    assert updated.is_active is False

    replayed = install_pending_import(
        session,
        course_id=COURSE_ID,
        user_id=USER_ID,
        import_id=record.id,
    )
    assert replayed.already_installed is True
    assert replayed.status == status

    registry = session.get(QuestionTypeRegistry, first.registry_id)
    assert registry is not None
    assert registry.status == status
    assert registry.is_active is False


def test_expired_import_cannot_be_installed(session: Session, tmp_path: Path) -> None:
    package = _build_example(tmp_path)
    result = validate_atqskill(package)
    record, _preview = create_pending_import(
        session,
        course_id=COURSE_ID,
        user_id=USER_ID,
        original_filename=package.name,
        archive_bytes=package.read_bytes(),
        result=result,
    )
    assert record is not None
    record.expires_at = utcnow() - timedelta(seconds=1)
    session.add(record)
    session.flush()

    with pytest.raises(AITeachMeError) as error:
        install_pending_import(
            session,
            course_id=COURSE_ID,
            user_id=USER_ID,
            import_id=record.id,
        )
    assert error.value.error_code == "QUESTION_TYPE_IMPORT_EXPIRED"
    assert session.get(QuestionTypePackageImport, record.id) is None


def test_invalid_package_is_not_persisted(session: Session, tmp_path: Path) -> None:
    package = tmp_path / "invalid.atqskill"
    package.write_bytes(b"not-a-zip")
    result = validate_atqskill(package)

    record, preview = create_pending_import(
        session,
        course_id=COURSE_ID,
        user_id=USER_ID,
        original_filename=package.name,
        archive_bytes=b"",
        result=result,
    )

    assert record is None
    assert preview.valid is False
    assert preview.import_id is None
    assert session.exec(select(QuestionTypePackageImport)).all() == []


def test_existing_course_scoped_builtin_type_remains_runtime_ready(session: Session) -> None:
    session.add(
        QuestionTypeRegistry(
            type_key="single_choice",
            display_name="课程单选题",
            scope="course",
            course_id=COURSE_ID,
            description="沿用系统单选题运行能力。",
            answer_format="选择一个答案",
            grading_method="objective",
            source="manual",
            status="active",
            is_system=False,
            is_active=True,
        )
    )
    session.flush()

    catalog = list_question_type_catalog(session, course_id=COURSE_ID)
    legacy = next(item for item in catalog if item.display_name == "课程单选题")

    assert legacy.runtime_ready is True
    assert legacy.runtime_message == ""


def test_installed_asset_is_private_and_revalidated_on_read(
    session: Session,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source-with-asset"
    shutil.copytree(EXAMPLE_ROOT / "feynman_explanation", source)
    asset_path = source / "assets" / "example.png"
    asset_path.parent.mkdir()
    Image.new("RGB", (12, 8), color=(40, 80, 160)).save(asset_path, format="PNG")
    skill_path = source / "SKILL.md"
    skill_text = skill_path.read_text(encoding="utf-8")
    skill_text = skill_text.replace(
        "tools:\n  bindings: tools/bindings.json\n---",
        "tools:\n  bindings: tools/bindings.json\n"
        "assets:\n  - path: assets/example.png\n    role: example\n---",
    )
    skill_path.write_text(skill_text, encoding="utf-8")
    package = build_atqskill_archive(source, tmp_path / "with-asset.atqskill")

    _record, _preview, installed = _preview_and_install(session, package)
    asset = session.exec(
        select(QuestionTypePackageAsset).where(
            QuestionTypePackageAsset.package_version_id == installed.version_id
        )
    ).one()
    _stored, content = get_question_type_asset(
        session,
        course_id=COURSE_ID,
        asset_id=asset.id or 0,
    )
    assert content.startswith(b"\x89PNG\r\n\x1a\n")

    asset.content_base64 = base64.b64encode(content + b"tampered").decode("ascii")
    session.add(asset)
    session.flush()
    with pytest.raises(AITeachMeError) as error:
        get_question_type_asset(
            session,
            course_id=COURSE_ID,
            asset_id=asset.id or 0,
        )
    assert error.value.error_code == "QUESTION_TYPE_ASSET_CORRUPTED"


@pytest.mark.parametrize("name", ["feynman_explanation", "oral_defense", "scenario_interview", "argument_debate"])
def test_v1_to_generic_upgrade_keeps_registry_and_grades_frozen_history(session, tmp_path, monkeypatch, name):
    from app.api.exams import _custom_runtime_persistence_payload
    from app.models import ExamPaper, ExamPaperItem, QuestionTemplate
    from app.workflows.examine.exam_grade.lib import grader
    from app.workflows.examine.question_types.answers import normalize_custom_answer
    from app.workflows.examine.question_types.runtime import resolve_question_type_version

    legacy_package = build_atqskill_archive(LEGACY_EXAMPLE_ROOT / name, tmp_path / "old.atqskill")
    _, _, old = _preview_and_install(session, legacy_package)
    old_version = session.get(QuestionTypePackageVersion, old.version_id)
    frozen_definition = old_version.compiled_definition_json
    frozen_hash = old_version.package_hash
    runtime = resolve_question_type_version(session, course_id=COURSE_ID, version_id=old.version_id, mode="web_practice")
    case = runtime.definition.reference_cases[0]
    content = next(answer.content for answer in case.answers if answer.label == "strong")
    answer = normalize_custom_answer(
        {"fields": [field.model_dump() for field in runtime.definition.answer_fields]},
        answer=content if isinstance(content, str) else None,
        answer_payload=content if isinstance(content, dict) else None,
    )
    frozen = _custom_runtime_persistence_payload(runtime.workflow_payload(), answer=answer.display_text, answer_payload=answer.payload)
    paper = ExamPaper(course_id=COURSE_ID, user_id=USER_ID, exam_mode="web_practice", status="ready")
    template = QuestionTemplate(course_id=COURSE_ID, question_type=runtime.type_key, difficulty="medium",
        stem=case.question["stem"], stem_hash=f"legacy-{name}", answer=answer.display_text,
        explanation=case.question["explanation"])
    session.add_all([paper, template])
    session.flush()
    item = ExamPaperItem(
        exam_paper_id=paper.id, question_template_id=template.id, item_order=1, question_type=runtime.type_key,
        question_type_registry_id=old.registry_id, question_type_version_id=old.version_id,
        difficulty="medium", score=5, stem_snapshot=case.question["stem"],
        answer_snapshot=answer.display_text, explanation_snapshot=case.question["explanation"],
        answer_content=answer.display_text, answer_payload_json=json.dumps(answer.payload),
        answer_schema_snapshot_json=json.dumps(frozen["answer_schema"]),
        reference_answer_snapshot_json=json.dumps(frozen["reference_answer"]),
        grading_spec_snapshot_json=json.dumps(frozen["grading_spec"]),
        runtime_snapshot_json=json.dumps(frozen["runtime_snapshot"]), profile_eligible=False,
    )
    session.add(item)
    session.commit()
    old_item_id = item.id
    before = (item.answer_schema_snapshot_json, item.reference_answer_snapshot_json, item.grading_spec_snapshot_json, item.runtime_snapshot_json)
    new_package = build_atqskill_archive(EXAMPLE_ROOT / name, tmp_path / "new.atqskill")
    _, preview, new = _preview_and_install(session, new_package)
    assert preview.conflict == "new_version"
    assert new.registry_id == old.registry_id and new.version_id != old.version_id
    update_question_type_catalog_item(session, course_id=COURSE_ID, registry_id=new.registry_id, status="inactive", current_version_id=None)
    session.commit()
    session.expire_all()
    assert session.get(QuestionTypePackageVersion, old.version_id).compiled_definition_json == frozen_definition
    assert session.get(QuestionTypePackageVersion, old.version_id).package_hash == frozen_hash
    for mode in ("web_practice", "paper_exam", "mastery_drill"):
        old_runtime = resolve_question_type_version(session, course_id=COURSE_ID, version_id=old.version_id, mode=mode)
        new_runtime = resolve_question_type_version(session, course_id=COURSE_ID, version_id=new.version_id, mode=mode)
        assert old_runtime.definition.schema_version.endswith("/v1")
        assert new_runtime.definition.template_key == "generic_text_form_v2"
        assert old_runtime.definition.answer_fields == new_runtime.definition.answer_fields
        assert old_runtime.definition.rubric == new_runtime.definition.rubric

    async def full_credit(*_args, **_kwargs):
        key = next(iter(answer.payload))
        return grader.CustomRubricGradePayload(
            criteria=[dict(key=row.key, score_ratio=1, evidence=[dict(field_key=key, quote=answer.payload[key])]) for row in runtime.definition.rubric],
            feedback_text="回答满足题目要求。",
        )
    monkeypatch.setattr(grader, "acompletion_with_fallback", full_credit)
    restored = session.get(ExamPaperItem, old_item_id)
    grade = asyncio.run(grader._grade_custom_rubric_item("课程", restored))
    assert grade.score_obtained == 5 and grade.is_correct
    assert before == (restored.answer_schema_snapshot_json, restored.reference_answer_snapshot_json, restored.grading_spec_snapshot_json, restored.runtime_snapshot_json)
