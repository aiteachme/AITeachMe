"""DocGen cover-image sidecar generation."""

from __future__ import annotations

import asyncio
import base64
import mimetypes
from collections.abc import Mapping
from datetime import datetime
from typing import Any

import httpx
import structlog

from app.shared.infra.env_support import get_env
from app.shared.infra.llm_support import GeneratedImage, agenerate_image
from app.shared.infra.settings import get_settings
from app.shared.infra.settings.support import (
    normalize_openai_compatible_image_model_name,
    resolve_runtime_llm_provider,
)
from app.shared.infra.storage import get_content_store, resolve_subject_storage_scope
from app.utils.docgen_store import append_knowledge_build_recent_event
from app.utils.time import utcnow

logger = structlog.get_logger(__name__)

DOCGEN_COVER_ARTIFACT_NAME = "cover_artifact.json"
DOCGEN_COVER_SIZE_CANDIDATES = (
    "1792x1024",
    "1536x1024",
    "1024x1024",
)
PREDICTION_IMAGE_COVER_SIZE_CANDIDATES = ("1024x1024",)
_REMOTE_IMAGE_TIMEOUT_S = 45


def _chapter_titles(confirmed_plan: Mapping[str, Any] | None, *, limit: int = 5) -> list[str]:
    titles: list[str] = []
    for chapter in list((confirmed_plan or {}).get("chapter_plan") or []):
        if not isinstance(chapter, Mapping):
            continue
        title = str(chapter.get("title") or "").strip()
        if title:
            titles.append(title)
        if len(titles) >= limit:
            break
    return titles


def _course_cues(confirmed_plan: Mapping[str, Any] | None, *, limit: int = 8) -> list[str]:
    cues: list[str] = []
    seen: set[str] = set()
    for chapter in list((confirmed_plan or {}).get("chapter_plan") or []):
        if not isinstance(chapter, Mapping):
            continue
        items = [
            str(chapter.get("title") or "").strip(),
            str(chapter.get("objective") or "").strip(),
            *[
                str(item).strip()
                for item in list(chapter.get("required_elements") or [])
            ],
        ]
        for item in items:
            if not item:
                continue
            normalized = item.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            cues.append(item)
            if len(cues) >= limit:
                return cues
    return cues


def _build_cover_prompt(
    *,
    subject: str,
    user_prompt: str,
    plan_summary: str,
    digest_mode: str,
    confirmed_plan: Mapping[str, Any] | None,
) -> str:
    chapter_titles = "；".join(_chapter_titles(confirmed_plan)) or "课程主线"
    course_cues = "；".join(_course_cues(confirmed_plan)) or subject
    mode_hint = "冲刺复习感、重点收束、克制而有张力" if digest_mode == "sprint" else "系统学习感、结构层次、平静而有纵深"

    return (
        "Create a refined panoramic cover illustration for a teaching document.\n"
        "\n"
        "Hard requirements:\n"
        "- wide horizontal banner composition with a low-height, panoramic feel\n"
        "- abstract artistic landscape or environmental scene\n"
        "- scenic, atmospheric, elegant, calm, slightly surreal\n"
        "- no text, no letters, no numbers, no typography anywhere\n"
        "- no equations, no charts, no diagrams, no UI, no book cover mockup\n"
        "- not literal classroom imagery; keep it metaphorical and scenic\n"
        "- visually connected to the course only through subtle motifs and atmosphere\n"
        "- clean composition, open negative space, suitable as a document top cover\n"
        "- painterly or modern illustration style, not photo collage\n"
        "\n"
        f"Course subject: {subject}\n"
        f"Build intent: {user_prompt or 'teaching document cover'}\n"
        f"Plan summary: {plan_summary or 'structured learning document'}\n"
        f"Digest mode mood: {mode_hint}\n"
        f"Chapter cues: {chapter_titles}\n"
        f"Subtle course motifs to translate into terrain, light, layers, motion, or texture: {course_cues}\n"
        "\n"
        "The result should feel like an abstract landscape cover that hints at the course theme without spelling it out."
    )


def _mime_extension(mime_type: str | None) -> str:
    normalized = str(mime_type or "").split(";", 1)[0].strip().lower()
    if normalized == "image/jpeg":
        return ".jpg"
    guessed = mimetypes.guess_extension(normalized or "image/png")
    return guessed or ".png"


async def _image_bytes(image: GeneratedImage) -> tuple[bytes, str]:
    mime_type = str(image.mime_type or "").split(";", 1)[0].strip() or "image/png"
    if image.b64_json:
        return base64.b64decode(image.b64_json, validate=False), mime_type
    if image.url:
        async with httpx.AsyncClient(timeout=_REMOTE_IMAGE_TIMEOUT_S) as client:
            response = await client.get(image.url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
        return response.content, content_type or mime_type
    raise ValueError("image payload contains neither b64_json nor url")


def _cover_size_candidates(model: str | None, *, api_base: str | None) -> tuple[str, ...]:
    runtime_provider = resolve_runtime_llm_provider(base_url=api_base)
    normalized_model = normalize_openai_compatible_image_model_name(
        model,
        runtime_provider=runtime_provider,
    ) or ""
    if runtime_provider == "openai_compatible" and "/" in normalized_model:
        return PREDICTION_IMAGE_COVER_SIZE_CANDIDATES
    return DOCGEN_COVER_SIZE_CANDIDATES


def build_docgen_cover_markdown(artifact: Mapping[str, Any] | None) -> str:
    asset_path = str((artifact or {}).get("asset_path") or "").strip()
    if not asset_path:
        return ""
    return f"![]({asset_path})"


async def read_docgen_cover_artifact(subject: str) -> dict[str, Any] | None:
    cs = get_content_store()
    subject_scope = resolve_subject_storage_scope(subject)
    payload = await cs.read_json_raw(subject_scope.knowledge_build_prefix() + DOCGEN_COVER_ARTIFACT_NAME)
    return payload if isinstance(payload, dict) else None


async def wait_for_docgen_cover_artifact(
    subject: str,
    *,
    max_wait_seconds: float = 4.0,
    poll_interval_seconds: float = 0.2,
) -> dict[str, Any] | None:
    """Wait briefly for the cover sidecar so publish behavior is deterministic."""

    settings = get_settings()
    if not settings.docgen.generate_cover_image or not settings.image_generation_enabled:
        return None

    waited = 0.0
    while waited <= max_wait_seconds:
        artifact = await read_docgen_cover_artifact(subject)
        if artifact:
            return artifact
        await asyncio.sleep(poll_interval_seconds)
        waited += poll_interval_seconds
    return None


async def generate_docgen_cover_artifact(
    *,
    subject: str,
    build_session_id: str,
    user_prompt: str | None,
    plan_summary: str | None,
    digest_mode: str | None,
    confirmed_plan: Mapping[str, Any] | None,
    requested_at: datetime | None = None,
) -> dict[str, Any] | None:
    """Best-effort cover generation that never raises into the main DocGen flow."""

    settings = get_settings()
    if not settings.docgen.generate_cover_image:
        return None
    if not settings.image_generation_enabled:
        logger.info(
            "docgen_cover_generation_skipped",
            subject=subject,
            reason="image_generation_disabled",
        )
        return None

    subject_scope = resolve_subject_storage_scope(subject)
    cs = get_content_store()
    prompt = _build_cover_prompt(
        subject=subject,
        user_prompt=str(user_prompt or "").strip(),
        plan_summary=str(plan_summary or "").strip(),
        digest_mode=str(digest_mode or "").strip().lower(),
        confirmed_plan=confirmed_plan,
    )

    last_error: Exception | None = None
    size_candidates = _cover_size_candidates(
        settings.models.image_generation,
        api_base=get_env("LLM_BASE_URL"),
    )
    for size in size_candidates:
        try:
            result = await agenerate_image(
                prompt,
                size=size,
                n=1,
                extra_metadata={
                    "docgen_stage": "cover_generation",
                    "subject": subject,
                    "build_session_id": build_session_id,
                },
            )
            if not result.images:
                return None
            image = result.images[0]
            image_bytes, mime_type = await _image_bytes(image)
            extension = _mime_extension(mime_type)
            filename = f"docgen_cover_{build_session_id}{extension}"
            storage_key = f"{subject_scope.namespace}/assets/docgen/{filename}"
            asset_path = f"assets/docgen/{filename}"
            await cs.write_bytes(storage_key, image_bytes)
            artifact = {
                "kind": "docgen_cover",
                "asset_path": asset_path,
                "storage_key": storage_key,
                "mime_type": mime_type or "image/png",
                "requested_size": size,
                "generated_at": utcnow().isoformat(),
                "revised_prompt": str(image.revised_prompt or "").strip(),
                "prompt": prompt,
                "cover_markdown": build_docgen_cover_markdown({"asset_path": asset_path}),
            }
            await cs.write_json_raw(
                subject_scope.knowledge_build_prefix() + DOCGEN_COVER_ARTIFACT_NAME,
                artifact,
            )
            append_knowledge_build_recent_event(
                subject,
                requested_at=requested_at,
                event={
                    "stage": "docgen_cover_ready",
                    "summary": "文档封面已生成，将在发布时置于文档顶部。",
                    "created_at": utcnow(),
                },
            )
            logger.info(
                "docgen_cover_generation_completed",
                subject=subject,
                build_session_id=build_session_id,
                size=size,
                asset_path=asset_path,
            )
            return artifact
        except Exception as exc:  # pragma: no cover - provider/network behavior
            last_error = exc
            logger.warning(
                "docgen_cover_generation_attempt_failed",
                subject=subject,
                build_session_id=build_session_id,
                size=size,
                error=str(exc),
            )
    logger.warning(
        "docgen_cover_generation_failed",
        subject=subject,
        build_session_id=build_session_id,
        error=str(last_error) if last_error else "",
    )
    return None


__all__ = [
    "DOCGEN_COVER_ARTIFACT_NAME",
    "build_docgen_cover_markdown",
    "generate_docgen_cover_artifact",
    "read_docgen_cover_artifact",
    "wait_for_docgen_cover_artifact",
]
