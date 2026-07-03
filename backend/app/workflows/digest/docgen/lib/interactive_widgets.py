"""OpenMAIC-style widget outline helpers for DocGen interactive HTML."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

InteractiveWidgetType = Literal["simulation", "diagram", "game", "visualization3d"]

ALLOWED_INTERACTIVE_WIDGET_TYPES: tuple[InteractiveWidgetType, ...] = (
    "simulation",
    "diagram",
    "game",
)

INTERACTIVE_ALLOWED_RESOURCE_HOSTS: set[str] = {
    "unpkg.com",
    "cdn.jsdelivr.net",
    "cdnjs.cloudflare.com",
}

_HTML_DOC_RE = re.compile(r"<!doctype\s+html[^>]*>.*?</html>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_RE = re.compile(r"<html\b.*?</html>", re.IGNORECASE | re.DOTALL)
_HTML_CODE_FENCE_RE = re.compile(r"```(?:html)?\s*(?P<body>[\s\S]*?)```", re.IGNORECASE)
_WIDGET_CONFIG_RE = re.compile(
    r"<script\b[^>]*id\s*=\s*['\"]widget-config['\"][^>]*>(?P<body>.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)


def _clean_text(value: object, *, limit: int = 240) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _clean_list(value: object, *, limit: int = 8) -> list[str]:
    if isinstance(value, str):
        raw_items = re.split(r"[,，、\n]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = []
    items: list[str] = []
    for item in raw_items:
        cleaned = _clean_text(item, limit=80)
        if cleaned and cleaned not in items:
            items.append(cleaned)
        if len(items) >= limit:
            break
    return items


class InteractiveWidgetOutline(BaseModel):
    """Flexible widget-specific configuration chosen by the outline model."""

    concept: str = ""
    keyVariables: list[str] = Field(default_factory=list)
    diagramType: str = ""
    nodeCount: int | None = None
    gameType: str = ""
    challenge: str = ""
    playerControls: list[str] = Field(default_factory=list)
    visualizationType: str = ""
    objects: list[str] = Field(default_factory=list)
    interactions: list[str] = Field(default_factory=list)

    model_config = {"extra": "allow"}

    @field_validator("concept", "diagramType", "gameType", "challenge", "visualizationType", mode="before")
    @classmethod
    def _text(cls, value: object) -> str:
        return _clean_text(value)

    @field_validator("keyVariables", "playerControls", "objects", "interactions", mode="before")
    @classmethod
    def _list(cls, value: object) -> list[str]:
        return _clean_list(value)

    @field_validator("nodeCount", mode="before")
    @classmethod
    def _node_count(cls, value: object) -> int | None:
        try:
            count = int(value)
        except (TypeError, ValueError):
            return None
        return max(2, min(18, count))


class InteractiveSceneOutline(BaseModel):
    """One interactive scene outline, matching OpenMAIC's widget outline shape."""

    id: str = "scene_1"
    type: str = "interactive"
    title: str = "交互演示"
    description: str = ""
    keyPoints: list[str] = Field(default_factory=list)
    order: int = 1
    widgetType: InteractiveWidgetType = "simulation"
    widgetOutline: InteractiveWidgetOutline = Field(default_factory=InteractiveWidgetOutline)

    model_config = {"extra": "allow"}

    @field_validator("id", "type", "title", "description", mode="before")
    @classmethod
    def _text(cls, value: object) -> str:
        return _clean_text(value)

    @field_validator("keyPoints", mode="before")
    @classmethod
    def _key_points(cls, value: object) -> list[str]:
        return _clean_list(value, limit=6)

    @field_validator("order", mode="before")
    @classmethod
    def _order(cls, value: object) -> int:
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 1

    @model_validator(mode="after")
    def _ensure_interactive(self) -> "InteractiveSceneOutline":
        self.type = "interactive"
        if not self.title:
            self.title = "交互演示"
        if self.widgetType not in ALLOWED_INTERACTIVE_WIDGET_TYPES:
            self.widgetType = "diagram" if self.widgetType == "visualization3d" else "simulation"
        return self


class InteractiveOutlineDecision(BaseModel):
    """Top-level JSON object returned by the outline-selection LLM call."""

    languageDirective: str = "请使用中文教学；专业术语可保留英文并给出中文解释。"
    courseTitle: str = "交互演示"
    outlines: list[InteractiveSceneOutline] = Field(default_factory=list)

    model_config = {"extra": "allow"}

    @field_validator("languageDirective", "courseTitle", mode="before")
    @classmethod
    def _text(cls, value: object) -> str:
        return _clean_text(value, limit=320)

    @model_validator(mode="after")
    def _ensure_outline(self) -> "InteractiveOutlineDecision":
        if not self.outlines:
            self.outlines = [InteractiveSceneOutline()]
        return self

    def first_interactive_outline(self) -> InteractiveSceneOutline:
        for item in self.outlines:
            if item.type == "interactive" and item.widgetType in ALLOWED_INTERACTIVE_WIDGET_TYPES:
                return item
        return self.outlines[0] if self.outlines else InteractiveSceneOutline()


def extract_html_document(response: str) -> str | None:
    """Extract exactly one HTML document from a model response."""

    text = str(response or "").strip()
    if not text:
        return None

    lower = text.casefold()
    doctype_start = lower.find("<!doctype html")
    html_start = lower.find("<html")
    start = doctype_start if doctype_start != -1 else html_start
    if start != -1:
        html_end = lower.rfind("</html>")
        if html_end != -1:
            return text[start : html_end + len("</html>")].strip()

    doc_match = _HTML_DOC_RE.search(text)
    if doc_match is not None:
        return doc_match.group(0).strip()

    tag_match = _HTML_TAG_RE.search(text)
    if tag_match is not None:
        return tag_match.group(0).strip()

    fence_match = _HTML_CODE_FENCE_RE.search(text)
    if fence_match is not None:
        body = fence_match.group("body").strip()
        if "<html" in body.casefold() or "<!doctype" in body.casefold():
            return body

    if text.casefold().startswith(("<!doctype", "<html")):
        return text
    return None


def extract_widget_config(html: str) -> dict[str, Any] | None:
    """Read the embedded widget config JSON if the generated HTML includes it."""

    match = _WIDGET_CONFIG_RE.search(str(html or ""))
    if match is None:
        return None
    raw = match.group("body").strip()
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


__all__ = [
    "ALLOWED_INTERACTIVE_WIDGET_TYPES",
    "INTERACTIVE_ALLOWED_RESOURCE_HOSTS",
    "InteractiveOutlineDecision",
    "InteractiveSceneOutline",
    "InteractiveWidgetOutline",
    "InteractiveWidgetType",
    "extract_html_document",
    "extract_widget_config",
]
