from app.workflows.digest.docgen.lib.document_backbone import (
    apply_backbone_to_chapter_plan,
    build_document_backbone,
    fallback_document_backbone,
)
from app.workflows.digest.docgen.lib.models import (
    BackboneResearchAgenda,
    ChapterGenerationPlan,
    ChapterGenerationTask,
    ChapterGenerationTaskSeed,
    FileMaterialSummary,
    HighConfidenceEvidenceUnit,
)


def test_document_backbone_builds_claims_and_backfills_chapter_tasks():
    task_seed = ChapterGenerationTaskSeed(
        chapter_index=1,
        confirmed_title="导数基础",
        enhanced_title="导数基础",
        chapter_goal="理解导数定义和几何意义",
        required_elements=["导数定义", "几何意义"],
        retrieval_queries=["导数定义"],
    )
    evidence = HighConfidenceEvidenceUnit(
        evidence_id="ev1",
        source_ref="local://file/1/section/sec1",
        source_type="local",
        evidence_type="definition",
        text="导数描述函数在某一点附近的瞬时变化率。",
        chapter_affinity={1: 0.9},
        confidence=0.9,
    )
    backbone, warnings = build_document_backbone(
        task_seeds=[task_seed],
        agenda=BackboneResearchAgenda(
            topics=["导数基础"],
            glossary_candidates=["导数定义"],
            evidence_unit_ids=["ev1"],
        ),
        evidence_units=[evidence],
        file_summaries=[
            FileMaterialSummary(
                file_id=1,
                filename="calculus.md",
                concepts=["导数定义"],
                definitions=["导数定义"],
                chapter_affinity={1: 1.0},
            )
        ],
    )
    plan = ChapterGenerationPlan(
        subject="calculus",
        chapters=[
            ChapterGenerationTask(
                chapter_index=1,
                confirmed_title="导数基础",
                enhanced_title="导数基础",
                content_points=["导数定义"],
            )
        ],
    )
    updated = apply_backbone_to_chapter_plan(plan=plan, backbone=backbone)

    assert not warnings
    assert backbone.canonical_claim_pool
    assert backbone.source_trust_summary["evidence_unit_count"] == 1
    assert "导数定义" in updated.chapters[0].claim_targets


def test_document_backbone_fallback_is_non_blocking():
    backbone, warnings = fallback_document_backbone(
        task_seeds=[
            ChapterGenerationTaskSeed(
                chapter_index=1,
                confirmed_title="第一章",
                chapter_goal="兜底目标",
            )
        ],
        reason="boom",
    )

    assert backbone.fallback_used
    assert backbone.canonical_claim_pool[0].claim_text == "兜底目标"
    assert warnings[0].warning_id == "bb_fallback_used"
