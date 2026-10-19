"""Typed contracts for multimodal DocGen visual understanding."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


VisualType = Literal[
    "diagram",
    "flowchart",
    "architecture",
    "chart",
    "geometry",
    "formula",
    "table",
    "screenshot",
    "photo",
    "page_scan",
    "decorative",
    "unknown",
]
DetailLossRisk = Literal["low", "medium", "high"]


class MultimodalDocGenModel(BaseModel):
    """Strict base model for the multimodal lane."""

    model_config = ConfigDict(extra="forbid")


class RereadAssessment(MultimodalDocGenModel):
    """Separate checks required before sending an original image to Writer."""

    knowledge_scope: Literal["common", "source_specific", "uncertain"] = Field(
        default="uncertain",
        description="Whether the specific missing teaching knowledge is source-specific, not whether the general topic is familiar. Style and conventional labels are not knowledge gaps.",
    )
    text_coverage: Literal["covered", "missing", "uncertain"] = Field(
        default="uncertain",
        description="Coverage of the specific knowledge in original Section prose, before image evidence is added. A topic name, figure reference or broad overview alone is not coverage of detailed connections.",
    )
    original_required: bool = Field(
        default=False,
        description="True only if a compact summary and limited extracted facts cannot safely retain important source-specific knowledge. Do not assume the full transcription reaches Writer.",
    )
    missing_knowledge: str = Field(
        default="",
        description="Concrete missing source-specific numbers, formula, constraints or connections; empty when none.",
    )
    original_required_reason: str = Field(
        default="",
        description="The precision or relation that still requires direct inspection after evidence extraction; empty when not required.",
    )

    @property
    def allows_reread(self) -> bool:
        return (
            self.knowledge_scope == "source_specific"
            and self.text_coverage == "missing"
            and self.original_required
            and bool(self.missing_knowledge.strip())
            and bool(self.original_required_reason.strip())
        )


class MaterialImageOccurrence(MultimodalDocGenModel):
    """One ordered occurrence of an image inside a parsed source section."""

    image_id: str
    file_id: str
    source_filename: str
    section_ref: str
    section_title: str = ""
    occurrence_index: int = Field(ge=1)
    markdown_target: str
    asset_key: str
    asset_filename: str
    alt_text: str = ""
    nearby_text: str = ""
    section_text: str = ""
    page_number: int | None = None
    mime_type: str
    file_size: int = Field(ge=0)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    sha256: str
    context_sha256: str
    data_url: str = Field(exclude=True, repr=False)


class VisualEvidence(MultimodalDocGenModel):
    """Reusable teaching evidence extracted from one meaningful source image."""

    image_id: str
    file_id: str
    source_filename: str
    section_ref: str
    section_title: str = ""
    asset_filename: str
    visual_type: VisualType = "unknown"
    summary: str
    key_facts: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    formulas: list[str] = Field(default_factory=list)
    extracted_text: list[str] = Field(default_factory=list)
    key_concepts: list[str] = Field(default_factory=list)
    teaching_value: float = Field(default=0.5, ge=0.0, le=1.0)
    detail_loss_risk: DetailLossRisk = "low"
    reread_recommended: bool = False
    reread_reason: str = ""
    reread_assessment: RereadAssessment | None = None
    uncertainty_notes: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    image_sha256: str
    context_sha256: str
    model: str
    prompt_version: str
    detail: Literal["high"] = "high"

    @property
    def can_reread(self) -> bool:
        return bool(
            self.reread_recommended
            and self.reread_reason.strip()
            and self.reread_assessment
            and self.reread_assessment.allows_reread
        )

    @model_validator(mode="after")
    def enforce_reread_requirements(self) -> "VisualEvidence":
        self.reread_reason = self.reread_reason.strip()
        self.reread_recommended = self.can_reread
        if not self.reread_recommended:
            self.reread_reason = ""
        return self


class VisualEvidenceDecision(MultimodalDocGenModel):
    """Model decision for one image; meaningless images carry no evidence."""

    image_id: str
    is_meaningful: bool
    visual_type: VisualType | None = None
    summary: str | None = None
    key_facts: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    formulas: list[str] = Field(default_factory=list)
    extracted_text: list[str] = Field(default_factory=list)
    key_concepts: list[str] = Field(default_factory=list)
    teaching_value: float | None = Field(default=None, ge=0.0, le=1.0)
    detail_loss_risk: DetailLossRisk | None = None
    reread_recommended: bool | None = None
    reread_reason: str | None = None
    reread_assessment: RereadAssessment | None = None
    uncertainty_notes: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def enforce_meaningful_payload(self) -> "VisualEvidenceDecision":
        if not self.is_meaningful:
            self.visual_type = None
            self.summary = None
            self.key_facts = []
            self.relationships = []
            self.labels = []
            self.formulas = []
            self.extracted_text = []
            self.key_concepts = []
            self.teaching_value = None
            self.detail_loss_risk = None
            self.reread_recommended = None
            self.reread_reason = None
            self.reread_assessment = None
            self.uncertainty_notes = []
            self.confidence = None
            return self
        if not str(self.summary or "").strip():
            raise ValueError("meaningful image decision requires summary")
        # Missing or uncertain checks never authorize another original-image read.
        self.reread_reason = str(self.reread_reason or "").strip()
        self.reread_recommended = bool(
            self.reread_recommended
            and self.reread_reason
            and self.reread_assessment
            and self.reread_assessment.allows_reread
        )
        if not self.reread_recommended:
            self.reread_reason = ""
        return self

    def to_evidence(
        self,
        occurrence: MaterialImageOccurrence,
        *,
        model: str,
        prompt_version: str,
    ) -> VisualEvidence | None:
        if not self.is_meaningful:
            return None
        return VisualEvidence(
            image_id=occurrence.image_id,
            file_id=occurrence.file_id,
            source_filename=occurrence.source_filename,
            section_ref=occurrence.section_ref,
            section_title=occurrence.section_title,
            asset_filename=occurrence.asset_filename,
            visual_type=self.visual_type or "unknown",
            summary=str(self.summary or "").strip(),
            key_facts=list(self.key_facts),
            relationships=list(self.relationships),
            labels=list(self.labels),
            formulas=list(self.formulas),
            extracted_text=list(self.extracted_text),
            key_concepts=list(self.key_concepts),
            teaching_value=float(self.teaching_value if self.teaching_value is not None else 0.5),
            detail_loss_risk=self.detail_loss_risk or "low",
            reread_recommended=bool(self.reread_recommended),
            reread_reason=str(self.reread_reason or ""),
            reread_assessment=self.reread_assessment,
            uncertainty_notes=list(self.uncertainty_notes),
            confidence=float(self.confidence if self.confidence is not None else 0.5),
            image_sha256=occurrence.sha256,
            context_sha256=occurrence.context_sha256,
            model=model,
            prompt_version=prompt_version,
        )


class VisualEvidenceBatchResponse(MultimodalDocGenModel):
    """Structured response for a bounded multimodal image batch."""

    decisions: list[VisualEvidenceDecision] = Field(default_factory=list)


class WriterRereadImage(MultimodalDocGenModel):
    """Ephemeral Writer request image; never persisted in graph state."""

    image_id: str
    file_id: str
    section_ref: str
    asset_filename: str
    summary: str
    reread_reason: str
    prepared_bytes: int
    data_url: str = Field(exclude=True, repr=False)


class VisualEvidenceCacheEntry(MultimodalDocGenModel):
    """Content-addressed cache entry for one image occurrence."""

    schema_version: int = 1
    cache_key: str
    image_sha256: str
    context_sha256: str
    model: str
    prompt_version: str
    detail: Literal["high"] = "high"
    decision: VisualEvidenceDecision
    created_at: datetime


__all__ = [
    "DetailLossRisk",
    "MaterialImageOccurrence",
    "RereadAssessment",
    "VisualEvidence",
    "VisualEvidenceBatchResponse",
    "VisualEvidenceCacheEntry",
    "VisualEvidenceDecision",
    "VisualType",
    "WriterRereadImage",
]
