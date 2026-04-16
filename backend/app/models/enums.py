"""Shared enum definitions used across the application."""

from __future__ import annotations

from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DigestStep(str, Enum):
    CLEANED = "cleaned"
    OUTLINED = "outlined"
    STORED = "stored"
    CHUNKED = "chunked"
    EMBEDDED = "embedded"


class QuestionType(str, Enum):
    SINGLE_CHOICE = "single_choice"
    FILL_BLANK = "fill_blank"
    SHORT_ANSWER = "short_answer"


class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class KnowledgeUnitType(str, Enum):
    CONCEPT = "concept"
    DEFINITION = "definition"
    THEOREM = "theorem"
    FORMULA = "formula"
    EXAMPLE = "example"
    EXERCISE = "exercise"
    METHOD = "method"
    PROOF_STEP = "proof_step"
    REMARK = "remark"


class KnowledgeUnitTypeSource(str, Enum):
    RULE = "rule"
    LLM = "llm"
    MANUAL = "manual"


class KnowledgeRelationType(str, Enum):
    PREREQUISITE = "prerequisite"
    DERIVATION = "derivation"
    APPLICATION = "application"
    EXAMPLE_OF = "example_of"
    SIMILAR = "similar"
    CONTRAST = "contrast"


class KnowledgeUnitStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    MERGED = "merged"
    PENDING = "pending"


class KnowledgeRelationStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    PENDING = "pending"


class EntityMatchDecision(str, Enum):
    EXACT = "exact"
    ALIAS = "alias"
    BROADER = "broader"
    NARROWER = "narrower"
    RELATED_NOT_SAME = "related_not_same"
    NO_MATCH = "no_match"
    UNSURE = "unsure"


class RevisionReason(str, Enum):
    NEW_EVIDENCE = "new_evidence"
    MERGE = "merge"
    SPLIT = "split"
    HUMAN_EDIT = "human_edit"
    CONFLICT_RESOLUTION = "conflict_resolution"


class EvidenceRole(str, Enum):
    SUPPORTS = "supports"
    ELABORATES = "elaborates"
    CONTRADICTS = "contradicts"
    EXEMPLIFIES = "exemplifies"
    TAXONOMY_HINT = "taxonomy_hint"


class ExtractionMethod(str, Enum):
    LLM = "llm"
    MANUAL = "manual"
    RULE = "rule"


class FieldScope(str, Enum):
    NAME = "name"
    SUMMARY = "summary"
    BODY = "body"
    EDGE_DESCRIPTION = "edge_description"
    TAXONOMY_HINT = "taxonomy_hint"


class AliasStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class UnitMemberRole(str, Enum):
    CORE = "core"
    SUPPORT = "support"
    EXAMPLE = "example"
    PREREQUISITE_BRIDGE = "prerequisite_bridge"


class UnitStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    MERGED = "merged"
    PENDING = "pending"


class AnchorType(str, Enum):
    TEACHER_DEFINED = "teacher_defined"
    SYLLABUS = "syllabus"
    TEXTBOOK_TOC = "textbook_toc"
    GRAPH_DISCOVERED = "graph_discovered"
    SYSTEM = "system"


class AnchorStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class TreeVersionStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class ThemeTreeNodeType(str, Enum):
    CHAPTER = "chapter"
    SECTION = "section"
    THEME = "theme"
    UNIT_BUCKET = "unit_bucket"
    UNCATEGORIZED = "uncategorized"


class UnitTreeMembershipRole(str, Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    CROSS_LINK = "cross_link"


class MembershipSource(str, Enum):
    AUTO = "auto"
    HUMAN_FIXED = "human_fixed"


class DependencyType(str, Enum):
    PREREQUISITE = "prerequisite"
    COREQUISITE = "corequisite"


class DigestJobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ExamMode(str, Enum):
    WEB_PRACTICE = "web_practice"
    PAPER_EXAM = "paper_exam"
    DIAGNOSTIC = "diagnostic"
    PRACTICE = "practice"
    WEAKPOINT_BOOST = "weakpoint_boost"
    REVIEW = "review"
    MOCK_FINAL = "mock_final"
    REAL_EXAM = "real_exam"


_EXAM_MODE_ALIAS_TO_CANONICAL: dict[str, str] = {
    ExamMode.WEB_PRACTICE.value: ExamMode.WEB_PRACTICE.value,
    ExamMode.PAPER_EXAM.value: ExamMode.PAPER_EXAM.value,
    ExamMode.DIAGNOSTIC.value: ExamMode.WEB_PRACTICE.value,
    ExamMode.PRACTICE.value: ExamMode.WEB_PRACTICE.value,
    ExamMode.WEAKPOINT_BOOST.value: ExamMode.WEB_PRACTICE.value,
    ExamMode.REVIEW.value: ExamMode.WEB_PRACTICE.value,
    ExamMode.MOCK_FINAL.value: ExamMode.PAPER_EXAM.value,
    ExamMode.REAL_EXAM.value: ExamMode.PAPER_EXAM.value,
}


def normalize_exam_mode(mode: "ExamMode | str") -> str:
    raw = mode.value if isinstance(mode, ExamMode) else str(mode or "")
    normalized = raw.strip().lower()
    return _EXAM_MODE_ALIAS_TO_CANONICAL.get(normalized, ExamMode.WEB_PRACTICE.value)


def is_paper_exam_mode(mode: "ExamMode | str") -> bool:
    return normalize_exam_mode(mode) == ExamMode.PAPER_EXAM.value


def is_web_practice_mode(mode: "ExamMode | str") -> bool:
    return normalize_exam_mode(mode) == ExamMode.WEB_PRACTICE.value


class ExamPaperStatus(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    GRADING = "grading"
    GRADED = "graded"
    ARCHIVED = "archived"


EXAM_PAPER_STATUS_TRANSITIONS: dict[ExamPaperStatus, list[ExamPaperStatus]] = {
    ExamPaperStatus.DRAFT: [ExamPaperStatus.READY],
    ExamPaperStatus.READY: [ExamPaperStatus.IN_PROGRESS],
    ExamPaperStatus.IN_PROGRESS: [ExamPaperStatus.SUBMITTED],
    ExamPaperStatus.SUBMITTED: [ExamPaperStatus.GRADING],
    ExamPaperStatus.GRADING: [ExamPaperStatus.GRADED],
    ExamPaperStatus.GRADED: [ExamPaperStatus.ARCHIVED],
    ExamPaperStatus.ARCHIVED: [],
}


class QuestionTemplateStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class MasteryGranularity(str, Enum):
    UNIT = "unit"
    NODE = "node"


class ReviewTaskType(str, Enum):
    REVIEW_UNIT = "review_unit"
    REVIEW_NODE = "review_node"
    REVIEW_EXAM = "review_exam"
    PREREQ_PATCH = "prereq_patch"


class ReviewTaskStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    EXPIRED = "expired"


class ErrorCauseLabel(str, Enum):
    CONCEPT_CONFUSION = "concept_confusion"
    CALCULATION_ERROR = "calculation_error"
    PREREQUISITE_GAP = "prerequisite_gap"
    CARELESS_MISTAKE = "careless_mistake"
    INCOMPLETE_UNDERSTANDING = "incomplete_understanding"
    METHOD_MISAPPLICATION = "method_misapplication"
    UNKNOWN = "unknown"


class WeaknessReason(str, Enum):
    FORGETTING_DUE = "forgetting_due"
    REPEATED_WRONG = "repeated_wrong"
    PREREQ_GAP = "prereq_gap"
    NEWLY_LEARNED = "newly_learned"


class TemplateNodeRole(str, Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    PREREQUISITE = "prerequisite"
    TRANSFER = "transfer"


class AsyncJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


def validate_status_transition(current: ExamPaperStatus, target: ExamPaperStatus) -> bool:
    allowed_targets = EXAM_PAPER_STATUS_TRANSITIONS.get(current, [])
    if target not in allowed_targets:
        raise ValueError(f"illegal exam paper status transition: {current.value} -> {target.value}")
    return True


class DocGenStep(str, Enum):
    CLEANSING = "cleansing"
    OUTLINING = "outlining"
    DRAFTING = "drafting"
    FINALIZING = "finalizing"


class KnowledgeDocStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class IngestStatus(str, Enum):
    PENDING = "pending"
    CLASSIFYING = "classifying"
    FAST_PARSING = "fast_parsing"
    FAST_PARSED = "fast_parsed"
    ENHANCING = "enhancing"
    READY_FOR_DIGEST = "ready_for_digest"
    ENHANCE_FAILED = "enhance_failed"
    RETRY_PENDING = "retry_pending"
    FAILED = "failed"

    # Backward-compatible aliases for older persisted values.
    PARSING = "fast_parsing"
    VALIDATING = "fast_parsed"

