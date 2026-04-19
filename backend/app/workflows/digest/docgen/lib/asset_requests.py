"""Internal asset request placeholders for DocGen.

These blocks are not user-facing Markdown. They are an internal protocol
inserted by DocGen code after the writer returns, then consumed during the
enhancement stage before publishing.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

ASSET_REQUEST_LANGUAGE = "atm-docgen-internal-asset-request-v1"
ASSET_REQUEST_BEGIN = "ATM_DOCGEN_ASSET_REQUEST_V1_BEGIN::7A9F2E19E30B4B9DA0D2A9B1F6C8E7D3"
ASSET_REQUEST_END = "ATM_DOCGEN_ASSET_REQUEST_V1_END::7A9F2E19E30B4B9DA0D2A9B1F6C8E7D3"
VALID_ASSET_KINDS = {"mermaid", "image", "interactive"}

_ASSET_REQUEST_FENCE_RE = re.compile(
    rf"```{re.escape(ASSET_REQUEST_LANGUAGE)}\s*\n"
    rf"(?P<body>.*?{re.escape(ASSET_REQUEST_END)}\s*)```",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class AssetRequest:
    request_id: str
    kind: str
    description: str
    raw_block: str


def sanitize_asset_description(description: str) -> str:
    """Keep the internal request payload fence-safe and student-invisible."""

    text = str(description or "").replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for raw_line in text.split("\n"):
        stripped = raw_line.strip()
        if stripped in {ASSET_REQUEST_BEGIN, ASSET_REQUEST_END}:
            continue
        if stripped.startswith("```"):
            continue
        lines.append(raw_line.rstrip())
    cleaned = "\n".join(lines).strip()
    cleaned = cleaned.replace(ASSET_REQUEST_BEGIN, "").replace(ASSET_REQUEST_END, "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned[:1000].rstrip()


def normalize_asset_kind(kind: str) -> str:
    normalized = str(kind or "").strip().lower()
    if normalized in {"images", "picture", "figure"}:
        normalized = "image"
    if normalized in {"interactive_html", "interaction"}:
        normalized = "interactive"
    if normalized not in VALID_ASSET_KINDS:
        return ""
    return normalized


def build_asset_request_block(kind: str, description: str) -> str:
    normalized_kind = normalize_asset_kind(kind)
    cleaned_description = sanitize_asset_description(description)
    if not normalized_kind or not cleaned_description:
        return ""
    request_id = f"atm-docgen-asset-{uuid.uuid4().hex}"
    return (
        f"```{ASSET_REQUEST_LANGUAGE}\n"
        f"{ASSET_REQUEST_BEGIN}\n"
        f"id: {request_id}\n"
        f"kind: {normalized_kind}\n"
        "description:\n"
        f"{cleaned_description}\n"
        f"{ASSET_REQUEST_END}\n"
        "```"
    )


def _parse_asset_request_body(body: str, *, raw_block: str) -> AssetRequest | None:
    lines = str(body or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    stripped = [line.strip() for line in lines]
    if ASSET_REQUEST_BEGIN not in stripped or ASSET_REQUEST_END not in stripped:
        return None
    begin_index = stripped.index(ASSET_REQUEST_BEGIN)
    end_index = stripped.index(ASSET_REQUEST_END)
    if begin_index >= end_index:
        return None
    request_id = ""
    kind = ""
    description_lines: list[str] = []
    in_description = False
    for raw_line in lines[begin_index + 1 : end_index]:
        line = raw_line.strip()
        if in_description:
            description_lines.append(raw_line.rstrip())
            continue
        if line.lower().startswith("id:"):
            request_id = line.split(":", 1)[1].strip()
            continue
        if line.lower().startswith("kind:"):
            kind = normalize_asset_kind(line.split(":", 1)[1].strip())
            continue
        if line.lower() == "description:":
            in_description = True
            continue
    description = sanitize_asset_description("\n".join(description_lines))
    if not request_id or not kind or not description:
        return None
    return AssetRequest(request_id=request_id, kind=kind, description=description, raw_block=raw_block)


def iter_asset_requests(markdown: str) -> list[AssetRequest]:
    requests: list[AssetRequest] = []
    for match in _ASSET_REQUEST_FENCE_RE.finditer(str(markdown or "")):
        parsed = _parse_asset_request_body(match.group("body"), raw_block=match.group(0))
        if parsed is not None:
            requests.append(parsed)
    return requests


def extract_asset_request_descriptions(markdown: str, *, kind: str) -> list[str]:
    normalized_kind = normalize_asset_kind(kind)
    if not normalized_kind:
        return []
    return [
        request.description
        for request in iter_asset_requests(markdown)
        if request.kind == normalized_kind
    ]


def has_asset_request(markdown: str, *, kind: str) -> bool:
    return bool(extract_asset_request_descriptions(markdown, kind=kind))


def strip_asset_requests(markdown: str, *, kinds: Iterable[str] | None = None) -> str:
    normalized_kinds = {normalize_asset_kind(kind) for kind in kinds or []}
    normalized_kinds.discard("")

    def replace(match: re.Match[str]) -> str:
        parsed = _parse_asset_request_body(match.group("body"), raw_block=match.group(0))
        if parsed is None:
            return ""
        if normalized_kinds and parsed.kind not in normalized_kinds:
            return match.group(0)
        return ""

    return _ASSET_REQUEST_FENCE_RE.sub(replace, str(markdown or ""))


async def replace_asset_requests(
    markdown: str,
    *,
    kind: str,
    renderer: Callable[[str], Awaitable[str]],
) -> str:
    normalized_kind = normalize_asset_kind(kind)
    if not normalized_kind:
        return str(markdown or "")
    output: list[str] = []
    last_index = 0
    text = str(markdown or "")
    for match in _ASSET_REQUEST_FENCE_RE.finditer(text):
        output.append(text[last_index : match.start()])
        parsed = _parse_asset_request_body(match.group("body"), raw_block=match.group(0))
        if parsed is not None and parsed.kind == normalized_kind:
            output.append(await renderer(parsed.description))
        elif parsed is None:
            output.append("")
        else:
            output.append(match.group(0))
        last_index = match.end()
    output.append(text[last_index:])
    return "".join(output)


__all__ = [
    "ASSET_REQUEST_LANGUAGE",
    "AssetRequest",
    "build_asset_request_block",
    "extract_asset_request_descriptions",
    "has_asset_request",
    "iter_asset_requests",
    "normalize_asset_kind",
    "replace_asset_requests",
    "sanitize_asset_description",
    "strip_asset_requests",
]
