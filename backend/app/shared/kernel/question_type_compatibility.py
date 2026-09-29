"""Protocol compatibility for immutable custom question definitions.

New packages use the generic text form. Fixed template identities exist only to
read V1 packages and snapshots; they are not a catalog of new question types.
"""

from __future__ import annotations

from typing import Mapping


LEGACY_SCHEMA_ID = "aiteachme.question-skill/v1"
TEXT_FORM_SCHEMA_ID = "aiteachme.question-skill/v2"
TEXT_FORM_TEMPLATE_KEY = "generic_text_form_v2"

LEGACY_TEMPLATE_FIELDS = {
    "feynman_explanation_v1": ("explanation",),
    "oral_defense_v1": ("claim", "evidence", "boundary"),
    "scenario_interview_v1": ("analysis", "steps", "conclusion"),
    "argument_debate_v1": ("stance", "evidence", "counterargument", "rebuttal"),
}
LEGACY_TEMPLATE_RENDERERS = {
    key: "long_text_v1" if len(fields) == 1 else "structured_text_v1"
    for key, fields in LEGACY_TEMPLATE_FIELDS.items()
}


def is_legacy_question_type(definition: Mapping[str, object]) -> bool:
    # Early persisted snapshots did not include a schema version.
    return (
        str(definition.get("schema_version") or "") in {"", LEGACY_SCHEMA_ID}
        and str(definition.get("template_key") or "") in LEGACY_TEMPLATE_FIELDS
    )


def supports_text_form_definition(definition: Mapping[str, object]) -> bool:
    return is_legacy_question_type(definition) or (
        str(definition.get("schema_version") or "") in {"", TEXT_FORM_SCHEMA_ID}
        and str(definition.get("template_key") or "") == TEXT_FORM_TEMPLATE_KEY
    )


def requires_reference_answer_payload(definition: Mapping[str, object]) -> bool:
    """Keep the historical single-field response format at this boundary."""

    fields = list(definition.get("answer_fields") or [])
    return len(fields) > 1 or definition.get("schema_version") == TEXT_FORM_SCHEMA_ID
