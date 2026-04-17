"""Build raw planner material context from uploaded material."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from app.shared.infra.llm_support.common import resolve_settings_model
from app.shared.infra.llm_support.context_window import ContextWindowManager
from app.shared.infra.llm_support.litellm_loader import load_litellm
from app.shared.infra.settings import get_settings
from app.workflows.digest.common.models import DigestMaterialContext, SourcePacket

logger = structlog.get_logger(__name__)

FILE_CONTEXT_TOKENS = 10_000


@dataclass(frozen=True)
class MaterialDigestResult:
    """Outcome of the raw context packing pass."""

    digest: str
    total_chars: int
    total_tokens: int
    source_count: int
    llm_used: bool
    truncated: bool


def _source_label(packet: SourcePacket, *, index: int) -> str:
    return packet.filename or f"file_{packet.file_id or index + 1}"


def _planner_token_model() -> str:
    try:
        model, _selector = resolve_settings_model(get_settings(), "reason")
    except Exception:  # pragma: no cover - defensive local fallback
        return "gpt-4o-mini"
    return model or "gpt-4o-mini"


def _truncate_text_by_tokens(text: str, *, max_tokens: int) -> tuple[str, int, bool]:
    """Return the first ``max_tokens`` tokens, with a char estimate fallback."""

    if not text.strip():
        return "", 0, False
    model = _planner_token_model()
    try:
        litellm = load_litellm()
        tokens = list(litellm.encode(model=model, text=text))
        token_count = len(tokens)
        if token_count <= max_tokens:
            return text, token_count, False
        return litellm.decode(model=model, tokens=tokens[:max_tokens]), token_count, True
    except Exception:
        manager = ContextWindowManager()
        estimated = manager.estimate_tokens(text)
        if estimated <= max_tokens:
            return text, estimated, False
        logger.exception(
            "planner_material_token_truncate_fallback_used",
            max_tokens=max_tokens,
            estimated_tokens=estimated,
        )
        return manager.truncate_text(text, max_tokens), estimated, True


def _render_packet_context(packet: SourcePacket, *, index: int, total: int) -> tuple[str, int, bool]:
    content = (packet.normalized_content or "").strip()
    if not content:
        return "", 0, False
    excerpt, token_count, truncated = _truncate_text_by_tokens(content, max_tokens=FILE_CONTEXT_TOKENS)
    label = _source_label(packet, index=index)
    token_note = (
        f"本资料已按前 {FILE_CONTEXT_TOKENS} tokens 截断；原文约 {token_count} tokens。"
        if truncated
        else f"本资料约 {token_count} tokens，未截断。"
    )
    section = (
        f"===== 资料 {index + 1}/{total}：{label} =====\n"
        f"{token_note}\n"
        f"{excerpt}"
    ).strip()
    return section, token_count, truncated


async def build_material_digest(
    material_context: DigestMaterialContext,
) -> MaterialDigestResult:
    """Return concatenated raw context for planner prompts.

    Planner 不再先走摘要模型。这里直接拼接每份资料的原文片段，
    且每份资料最多保留前 ``FILE_CONTEXT_TOKENS`` tokens。
    """

    packets = [
        packet
        for packet in list(material_context.source_documents)
        if (packet.normalized_content or "").strip()
    ]
    if not packets:
        return MaterialDigestResult(
            digest="",
            total_chars=0,
            total_tokens=0,
            source_count=0,
            llm_used=False,
            truncated=False,
        )

    total_chars = sum(len((packet.normalized_content or "").strip()) for packet in packets)
    results = [
        _render_packet_context(packet, index=index, total=len(packets))
        for index, packet in enumerate(packets)
    ]
    sections = [section for section, _token_count, _truncated in results if section]
    return MaterialDigestResult(
        digest="\n\n".join(sections),
        total_chars=total_chars,
        total_tokens=sum(token_count for _section, token_count, _truncated in results),
        source_count=len(packets),
        llm_used=False,
        truncated=any(truncated for _section, _token_count, truncated in results),
    )


__all__ = [
    "FILE_CONTEXT_TOKENS",
    "MaterialDigestResult",
    "build_material_digest",
]
