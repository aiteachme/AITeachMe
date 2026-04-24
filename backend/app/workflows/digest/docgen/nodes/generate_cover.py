"""Generate the DocGen cover inside the main graph."""

from __future__ import annotations

from time import perf_counter

from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.docgen.lib.cover import (
    build_docgen_cover_markdown,
    generate_docgen_cover_artifact,
)
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState


def build_generate_cover_node(*, context: WorkflowContext):
    """Build the best-effort cover generation node."""

    async def generate_cover_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        artifact = await generate_docgen_cover_artifact(
            subject=state["subject"],
            build_session_id=state.get("build_session_id") or "",
            user_prompt=state.get("user_prompt"),
            plan_summary=str((state.get("document_context") or {}).get("plan_summary") or ""),
            digest_mode=state.get("digest_mode"),
            confirmed_plan=state.get("confirmed_plan"),
            requested_at=state.get("requested_at"),
            file_summaries=list(state.get("file_summaries") or []),
            intent_profile=dict(state.get("intent_profile") or {}),
        )
        cover_artifact = dict(artifact or {})
        cover_markdown = build_docgen_cover_markdown(cover_artifact)
        await publish_docgen_progress(
            context,
            state=state,
            stage="cover_generated" if cover_artifact else "cover_skipped",
            payload={
                "cover_ready": bool(cover_artifact),
            },
        )
        return {
            "cover_artifact": cover_artifact,
            "cover_markdown": cover_markdown,
            "cover_ms": int((perf_counter() - started_at) * 1000),
        }

    return generate_cover_node


__all__ = ["build_generate_cover_node"]
