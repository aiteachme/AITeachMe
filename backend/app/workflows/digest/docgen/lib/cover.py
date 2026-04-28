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
from app.shared.infra.knowledge.build_store import append_knowledge_build_recent_event
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib.model_policy import DocGenModelStep, get_docgen_model_policy

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


def _file_summary_cues(file_summaries: list[Mapping[str, Any]] | None, *, limit: int = 8) -> list[str]:
    cues: list[str] = []
    seen: set[str] = set()
    for summary in list(file_summaries or []):
        if not isinstance(summary, Mapping):
            continue
        candidates = [
            str(summary.get("summary") or "").strip(),
            *[str(item).strip() for item in list(summary.get("concepts") or [])],
            *[str(item).strip() for item in list(summary.get("key_terms") or [])],
        ]
        for item in candidates:
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
    subject_name: str,
    user_prompt: str,
    plan_summary: str,
    digest_mode: str,
    confirmed_plan: Mapping[str, Any] | None,
    file_summaries: list[Mapping[str, Any]] | None = None,
    intent_profile: Mapping[str, Any] | None = None,
) -> str:
    chapter_titles = "；".join(_chapter_titles(confirmed_plan)) or "课程主线"
    course_cues = "；".join(_course_cues(confirmed_plan)) or subject_name
    file_cues = "；".join(_file_summary_cues(file_summaries)) or course_cues
    mode_hint = (
        "compressed, focused, tense but elegant, like dusk before an exam"
        if digest_mode == "sprint"
        else "slow, layered, spacious, calm, like a long journey through changing landscapes"
    )
    abstract_intent = str((intent_profile or {}).get("teaching_intent") or "").strip()

    return (
        "Create a poetic panoramic cover image for a teaching document.\n"
        "\n"
        "Creative direction:\n"
        "- wide cinematic landscape banner\n"
        "- abstract or semi-abstract environment, not a literal textbook illustration\n"
        "- treat the course as emotional weather, terrain, light, season, depth, rhythm, and motion\n"
        "- let the model freely associate from the learning themes into mountains, coastlines, forests, rivers, sky, mist, wind, architecture silhouettes, paths, reflections, or layered geological forms\n"
        "- prioritize beauty, atmosphere, metaphor, and artistic restraint over explicit explanation\n"
        "- painterly, contemporary editorial illustration, or dreamlike landscape art\n"
        "- no text, no letters, no numbers, no equations, no charts, no diagrams, no UI\n"
        "- no book mockup, no classroom scene, no obvious education props\n"
        "- leave clean breathing space so it can sit above the document as a cover\n"
        "\n"
        "Course signals to loosely absorb, not literally depict:\n"
        f"- subject: {subject_name}\n"
        f"- build intent: {user_prompt or 'teaching document cover'}\n"
        f"- plan summary: {plan_summary or 'structured learning document'}\n"
        f"- chapter arc: {chapter_titles}\n"
        f"- curriculum motifs: {course_cues}\n"
        f"- source material cues: {file_cues}\n"
        f"- mood: {mode_hint}\n"
        f"- teaching intent hint: {abstract_intent or 'guide the learner through a meaningful landscape of ideas'}\n"
        "\n"
        "The final image should feel like a refined abstract landscape that quietly resonates with the course, "
        "as if the subject had dissolved into scenery."
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


def _is_docgen_cover_filename(filename: str) -> bool:
    lowered = str(filename or "").strip().lower()
    return lowered.startswith("docgen_cover_") or lowered.startswith("cover.")


async def _cleanup_stale_docgen_covers(*, namespace: str, keep_key: str) -> None:
    """Keep one stable DocGen cover in assets/docgen/.

    Older builds used build-session-specific names. Once the current build
    writes the stable cover path, those legacy images only create duplicate
    files and confuse Markdown asset resolution.
    """

    cs = get_content_store()
    prefix = f"{namespace}/assets/docgen/"
    try:
        keys = await cs.list_prefix(prefix)
        for key in keys:
            if key == keep_key:
                continue
            filename = key.rsplit("/", 1)[-1]
            if _is_docgen_cover_filename(filename):
                await cs.delete(key)
    except Exception as exc:  # pragma: no cover - best-effort cleanup
        logger.warning("docgen_cover_cleanup_failed", namespace=namespace, error=str(exc))


async def read_docgen_cover_artifact(subject_id: str) -> dict[str, Any] | None:
    cs = get_content_store()
    subject_scope = resolve_subject_storage_scope(subject_id)
    payload = await cs.read_json_raw(subject_scope.knowledge_build_prefix() + DOCGEN_COVER_ARTIFACT_NAME)
    return payload if isinstance(payload, dict) else None


async def wait_for_docgen_cover_artifact(
    subject_id: str,
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
        artifact = await read_docgen_cover_artifact(subject_id)
        if artifact:
            return artifact
        await asyncio.sleep(poll_interval_seconds)
        waited += poll_interval_seconds
    return None


async def generate_docgen_cover_artifact(
    *,
    subject_id: str,
    subject_name: str,
    build_session_id: str,
    user_prompt: str | None,
    plan_summary: str | None,
    digest_mode: str | None,
    confirmed_plan: Mapping[str, Any] | None,
    requested_at: datetime | None = None,
    file_summaries: list[Mapping[str, Any]] | None = None,
    intent_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Best-effort cover generation used by the DocGen main graph."""

    settings = get_settings()
    if not settings.docgen.generate_cover_image:
        return None
    if not settings.image_generation_enabled:
        logger.info(
            "docgen_cover_generation_skipped",
            subject_id=subject_id,
            reason="image_generation_disabled",
        )
        return None

    subject_scope = resolve_subject_storage_scope(subject_id)
    cs = get_content_store()
    prompt = _build_cover_prompt(
        subject_name=subject_name,
        user_prompt=str(user_prompt or "").strip(),
        plan_summary=str(plan_summary or "").strip(),
        digest_mode=str(digest_mode or "").strip().lower(),
        confirmed_plan=confirmed_plan,
        file_summaries=file_summaries,
        intent_profile=intent_profile,
    )

    last_error: Exception | None = None
    size_candidates = _cover_size_candidates(
        settings.models.image_generation,
        api_base=get_env("LLM_BASE_URL"),
    )
    model_policy = get_docgen_model_policy(DocGenModelStep.COVER_IMAGE)
    for size in size_candidates:
        try:
            result = await agenerate_image(
                prompt,
                model=str(model_policy.model or "image_generation"),
                size=size,
                n=1,
                extra_metadata={
                    **model_policy.metadata(),
                    "docgen_stage": "cover_generation",
                    "subject_id": subject_id,
                    "subject_name": subject_name,
                    "build_session_id": build_session_id,
                },
            )
            if not result.images:
                return None
            image = result.images[0]
            image_bytes, mime_type = await _image_bytes(image)
            extension = _mime_extension(mime_type)
            filename = f"cover{extension}"
            storage_key = f"{subject_scope.namespace}/assets/docgen/{filename}"
            # merged_knowledge_base.md lives under knowledge_markdowns/, so it
            # needs to walk up one level to reach the sibling assets/ tree.
            asset_path = f"../assets/docgen/{filename}"
            await cs.write_bytes(storage_key, image_bytes)
            await _cleanup_stale_docgen_covers(namespace=subject_scope.namespace, keep_key=storage_key)
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
                subject_id,
                requested_at=requested_at,
                event={
                    "stage": "docgen_cover_ready",
                    "summary": "文档封面已生成，将在发布时置于文档顶部。",
                    "created_at": utcnow(),
                },
            )
            logger.info(
                "docgen_cover_generation_completed",
                subject_id=subject_id,
                subject_name=subject_name,
                build_session_id=build_session_id,
                size=size,
                asset_path=asset_path,
            )
            return artifact
        except Exception as exc:  # pragma: no cover - provider/network behavior
            last_error = exc
            logger.warning(
                "docgen_cover_generation_attempt_failed",
                subject_id=subject_id,
                subject_name=subject_name,
                build_session_id=build_session_id,
                size=size,
                error=str(exc),
            )
    logger.warning(
        "docgen_cover_generation_failed",
        subject_id=subject_id,
        subject_name=subject_name,
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
