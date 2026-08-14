"""Interactive HTML sidecar generation for DocGen chapter enhancement."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import structlog

from app.shared.infra.execution import TracedExecutionContext
from app.shared.infra.llm_support import acompletion_with_fallback, run_llm_tasks
from app.shared.infra.storage import CourseStorageScope, get_content_store, resolve_course_storage_scope
from app.shared.infra.tools.builtin.markdown_processing import validate_single_file_html
from app.utils.path_helpers import sanitize_doc_title
from app.workflows.digest.docgen.lib.html_sidecar import normalize_single_file_html
from app.workflows.digest.docgen.lib.interactive_design import (
    InteractionDesignBrief,
    InteractiveHtmlQualityReport,
    assess_interactive_html_quality,
    build_chapter_interaction_design_brief,
    build_selection_interaction_design_brief,
)
from app.workflows.digest.docgen.lib.interactive_widgets import (
    INTERACTIVE_ALLOWED_RESOURCE_HOSTS,
    InteractiveOutlineDecision,
    InteractiveSceneOutline,
    extract_html_document,
    extract_widget_config,
)
from app.workflows.digest.docgen.lib.model_policy import DocGenModelStep, docgen_completion_kwargs_with_metadata
from app.workflows.digest.docgen.lib.models import ChapterDraft, ClaimLedger, DocumentBackbone
from app.workflows.digest.docgen.prompts.interactive_html import (
    build_interactive_html_messages,
    build_interactive_widget_outline_messages,
    build_selection_interactive_html_messages,
    build_widget_interactive_html_messages,
)

logger = structlog.get_logger(__name__)

InteractiveMode = Literal["parameter_explorer", "process_stepper", "concept_mapper"]

_ANY_HEADING_RE = re.compile(r"^(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$", re.MULTILINE)
_HTML_DOCUMENT_SIGNAL_RE = re.compile(r"<!doctype\s+html|<html\b|```(?:html)?", re.IGNORECASE)
_REMOTE_URL_HOST_RE = re.compile(
    r"(?:https?:)?//(?P<host>[A-Za-z0-9.-]+)(?::\d+)?(?:[/?#]|$)",
    re.IGNORECASE,
)
_ACTIVE_NETWORK_API_RE = re.compile(r"\b(fetch|XMLHttpRequest|WebSocket)\s*\(", re.IGNORECASE)
_JAVASCRIPT_URL_RE = re.compile(r"\b(?:href|src|xlink:href)\s*=\s*(['\"])\s*javascript:", re.IGNORECASE)


@dataclass(frozen=True)
class _InteractiveSectionCandidate:
    index: int
    heading_id: str
    title: str
    level: int
    context: str
    insert_at: int
    score: float


@dataclass(frozen=True)
class _GeneratedInteractiveHtml:
    html: str
    validation_issues: list[str]
    quality_report: InteractiveHtmlQualityReport
    widget_config: dict[str, object] | None = None


@dataclass(frozen=True)
class GeneratedSelectionInteractiveHtml:
    title: str
    html: str
    validation_issues: list[str]
    quality_issues: list[str]
    design_brief: dict[str, str]
    widget_type: str = ""
    widget_outline: dict[str, object] = field(default_factory=dict)
    widget_config: dict[str, object] = field(default_factory=dict)
    language_directive: str = ""


def _plain_heading_text(raw: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", str(raw or ""))
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_~]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _heading_text_to_id(text: str) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fff]+", "-", str(text or "").strip().lower(), flags=re.UNICODE).strip("-")
    return slug or "section"


def _score_interactive_signal(title: str, context: str) -> float:
    formula_count = min(5, context.count("$$") + context.count("$"))
    text_len = len(re.sub(r"\s+", "", context))
    score = formula_count + min(3, text_len // 500)
    if text_len < 120:
        score -= 2
    return float(score)


def _section_end_for_heading(
    headings: Sequence[re.Match[str]],
    heading_index: int,
    markdown_len: int,
) -> int:
    current_level = len(headings[heading_index].group("marks"))
    for candidate in headings[heading_index + 1 :]:
        if len(candidate.group("marks")) <= current_level:
            return candidate.start()
    return markdown_len


def _iter_interactive_section_candidates(markdown: str, *, fallback_title: str) -> list[_InteractiveSectionCandidate]:
    text = str(markdown or "")
    headings = list(_ANY_HEADING_RE.finditer(text))
    candidates: list[_InteractiveSectionCandidate] = []
    heading_counts: dict[str, int] = {}
    for heading_index, heading in enumerate(headings):
        level = len(heading.group("marks"))
        title = _plain_heading_text(heading.group("title"))
        if not title:
            continue
        base_heading_id = _heading_text_to_id(title)
        heading_count = heading_counts.get(base_heading_id, 0) + 1
        heading_counts[base_heading_id] = heading_count
        heading_id = base_heading_id if heading_count == 1 else f"{base_heading_id}-{heading_count}"
        if level not in {2, 3}:
            continue
        end = _section_end_for_heading(headings, heading_index, len(text))
        body = text[heading.end() : end].strip()
        context = f"{title}\n\n{body[:2400].rstrip()}".strip()
        candidates.append(
            _InteractiveSectionCandidate(
                index=len(candidates) + 1,
                heading_id=heading_id,
                title=title,
                level=level,
                context=context,
                insert_at=end,
                score=_score_interactive_signal(title, context),
            )
        )

    if candidates:
        return candidates

    fallback_context = _chapter_context_excerpt_from_markdown(text)
    fallback_heading = _plain_heading_text(fallback_title)
    if not fallback_context or not fallback_heading:
        return []
    return [
        _InteractiveSectionCandidate(
            index=1,
            heading_id=_heading_text_to_id(fallback_title),
            title=fallback_heading,
            level=1,
            context=fallback_context,
            insert_at=len(text),
            score=_score_interactive_signal(fallback_title, fallback_context),
        )
    ]


def _select_interactive_section_candidates(
    markdown: str,
    *,
    fallback_title: str,
    max_count: int = 3,
) -> list[_InteractiveSectionCandidate]:
    candidates = _iter_interactive_section_candidates(markdown, fallback_title=fallback_title)
    if not candidates:
        return []

    positive = [item for item in candidates if item.score > 0]
    pool = positive or candidates
    target_count = 1
    if len(pool) >= 8:
        target_count = 3
    elif len(pool) >= 3:
        target_count = 2
    target_count = max(1, min(max_count, target_count, len(pool)))

    selected: list[_InteractiveSectionCandidate] = []
    for item in sorted(pool, key=lambda candidate: (-candidate.score, candidate.insert_at)):
        if any(abs(item.insert_at - existing.insert_at) < 80 for existing in selected):
            continue
        selected.append(item)
        if len(selected) >= target_count:
            break

    return sorted(selected or pool[:1], key=lambda candidate: candidate.insert_at)


def choose_interactive_mode(
    draft: ChapterDraft,
    *,
    claim_ledger: ClaimLedger | None = None,
) -> InteractiveMode:
    del draft
    claim_types = {item.claim_type for item in list((claim_ledger or ClaimLedger()).items or []) if item.claim_type}
    if claim_types & {"method", "procedure", "algorithm"}:
        return "process_stepper"
    if len(claim_types) >= 3:
        return "concept_mapper"
    return "parameter_explorer"


def should_generate_interactive_html(
    draft: ChapterDraft,
    *,
    claim_ledger: ClaimLedger | None = None,
    document_backbone: DocumentBackbone | None = None,
) -> bool:
    del claim_ledger, document_backbone
    return bool(_select_interactive_section_candidates(draft.markdown, fallback_title=draft.title))


def _chapter_context_excerpt(draft: ChapterDraft, *, limit: int = 2200) -> str:
    return _chapter_context_excerpt_from_markdown(draft.markdown, limit=limit)


def _chapter_context_excerpt_from_markdown(markdown: str, *, limit: int = 2200) -> str:
    text = re.sub(r"```.*?```", "", markdown, flags=re.DOTALL)
    text = re.sub(r"#+\s*", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:limit].rstrip()


def _sanitize_generated_html(
    html: str,
    *,
    title: str,
    allow_external_resources: bool = False,
    allowed_resource_hosts: set[str] | None = None,
) -> str:
    html_document = extract_html_document(html) or html
    return normalize_single_file_html(
        html_document,
        title=title,
        allow_scripts=True,
        allow_external_resources=allow_external_resources,
        allowed_resource_hosts=allowed_resource_hosts,
    )


def _generated_html_completeness_issues(html: str) -> list[str]:
    """Detect raw model outputs that look truncated before normalization can mask it."""

    text = str(html or "").strip()
    html_document = extract_html_document(text) or text
    structure = re.sub(
        r"<(?P<tag>script|style)\b[^>]*>.*?</(?P=tag)>",
        lambda match: f"<{match.group('tag')}></{match.group('tag')}>",
        html_document,
        flags=re.IGNORECASE | re.DOTALL,
    ).casefold()
    issues: list[str] = []
    required_markers = {
        "<!doctype html": "<!DOCTYPE html>",
        "<html": "<html>",
        "<head": "<head>",
        "</head>": "</head>",
        "<body": "<body>",
        "</body>": "</body>",
        "</html>": "</html>",
    }
    for marker, label in required_markers.items():
        if marker not in structure:
            issues.append(f"模型输出的原始 HTML 缺少 {label}，可能尚未生成完整。")
    for tag in ("script", "style"):
        open_count = len(re.findall(rf"<{tag}\b", html_document, re.IGNORECASE))
        close_count = len(re.findall(rf"</{tag}\s*>", html_document, re.IGNORECASE))
        if close_count < open_count:
            issues.append(f"模型输出的原始 HTML 存在未闭合的 <{tag}>，可能被截断。")
    return list(dict.fromkeys(issues))


def _interactive_generation_passed(result: _GeneratedInteractiveHtml) -> bool:
    return not result.validation_issues and result.quality_report.passed


def _structure_without_script_style(html: str) -> str:
    return re.sub(
        r"<(?P<tag>script|style)\b[^>]*>.*?</(?P=tag)>",
        lambda match: f"<{match.group('tag')}></{match.group('tag')}>",
        str(html or ""),
        flags=re.IGNORECASE | re.DOTALL,
    )


def _iter_remote_resource_hosts(html: str) -> list[str]:
    hosts: list[str] = []
    for match in _REMOTE_URL_HOST_RE.finditer(str(html or "")):
        host = match.group("host").casefold()
        if host and host not in hosts:
            hosts.append(host)
    return hosts


def _openmaic_style_validation_issues(
    *,
    raw_html: str,
    cleaned_html: str,
    allowed_resource_hosts: set[str] | None = None,
    widget_type: str = "",
) -> list[str]:
    """Loose OpenMAIC-style acceptance gate.

    The stricter local quality gate is intentionally kept below in
    `_strict_interactive_html_review`, but the active generation path now only
    rejects outputs that cannot be treated as an HTML document or violate basic
    sandbox/network constraints. Failed loose checks still feed retry feedback
    back to the model.
    """

    raw_text = str(raw_html or "").strip()
    cleaned_text = str(cleaned_html or "").strip()
    issues: list[str] = []

    extracted = extract_html_document(raw_text)
    if not raw_text or not extracted or not _HTML_DOCUMENT_SIGNAL_RE.search(raw_text):
        issues.append("模型输出没有可提取的 HTML 文档。请只返回完整 HTML。")

    raw_document = extracted or raw_text
    for tag in ("script", "style"):
        open_count = len(re.findall(rf"<{tag}\b", raw_document, re.IGNORECASE))
        close_count = len(re.findall(rf"</{tag}\s*>", raw_document, re.IGNORECASE))
        if close_count < open_count:
            issues.append(f"模型输出的原始 HTML 存在未闭合的 <{tag}>，可能被截断。")

    cleaned_structure = _structure_without_script_style(cleaned_text).casefold()
    if "<html" not in cleaned_structure or "</html>" not in cleaned_structure:
        issues.append("HTML 文档缺少完整的 <html> 结构。")
    if "<head" not in cleaned_structure or "</head>" not in cleaned_structure:
        issues.append("HTML 文档缺少完整的 <head> 结构。")
    if "<body" not in cleaned_structure or "</body>" not in cleaned_structure:
        issues.append("HTML 文档缺少完整的 <body> 结构。")
    if not re.search(r"<meta[^>]+name\s*=\s*['\"]viewport['\"]", cleaned_text, re.IGNORECASE):
        issues.append("HTML 文档缺少移动端 viewport meta。")

    if _ACTIVE_NETWORK_API_RE.search(cleaned_text):
        issues.append("HTML 包含不允许的主动联网 API：fetch/XMLHttpRequest/WebSocket。")
    if _JAVASCRIPT_URL_RE.search(cleaned_text):
        issues.append("HTML 包含不安全的 javascript: URL。")

    allowed_hosts = {
        host.casefold()
        for host in (allowed_resource_hosts or INTERACTIVE_ALLOWED_RESOURCE_HOSTS)
        if str(host).strip()
    }
    disallowed_hosts = [
        host
        for host in _iter_remote_resource_hosts(cleaned_text)
        if allowed_hosts and host not in allowed_hosts
    ]
    if disallowed_hosts:
        issues.append("HTML 包含未允许的远程资源域名：" + "、".join(disallowed_hosts) + "。")

    if widget_type == "visualization3d":
        issues.extend(_javascript_syntax_issues(cleaned_text, require_checker=True))

    return list(dict.fromkeys(issues))


def _openmaic_style_interactive_html_review(
    *,
    raw_html: str,
    cleaned_html: str,
    allowed_resource_hosts: set[str] | None = None,
    widget_type: str = "",
) -> tuple[list[str], InteractiveHtmlQualityReport]:
    validation_issues = _openmaic_style_validation_issues(
        raw_html=raw_html,
        cleaned_html=cleaned_html,
        allowed_resource_hosts=allowed_resource_hosts,
        widget_type=widget_type,
    )
    return validation_issues, InteractiveHtmlQualityReport(
        passed=not validation_issues,
        issues=(),
    )


def _script_blocks_for_syntax_check(html: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    for match in re.finditer(
        r"<script\b(?P<attrs>[^>]*)>(?P<body>.*?)</script\s*>",
        str(html or ""),
        flags=re.IGNORECASE | re.DOTALL,
    ):
        attrs = match.group("attrs") or ""
        body = match.group("body") or ""
        if not body.strip():
            continue
        type_match = re.search(r"\btype\s*=\s*['\"]?([^'\"\s>]+)", attrs, re.IGNORECASE)
        script_type = (type_match.group(1).strip().lower() if type_match else "")
        if script_type in {"application/json", "application/ld+json", "importmap", "speculationrules"}:
            continue
        if script_type and script_type not in {
            "module",
            "text/javascript",
            "application/javascript",
            "application/ecmascript",
            "text/ecmascript",
        }:
            continue
        extension = ".mjs" if script_type == "module" else ".cjs"
        blocks.append((extension, body))
    return blocks


def _node_executable_path() -> str | None:
    candidates = [
        shutil.which("node"),
        str(Path(sys.executable).with_name("node.exe")),
        str(Path(sys.executable).with_name("node")),
        str(Path(sys.prefix) / ("node.exe" if sys.platform.startswith("win") else "node")),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _javascript_syntax_issues(html: str, *, require_checker: bool = False) -> list[str]:
    node_path = _node_executable_path()
    if not node_path:
        if require_checker and _script_blocks_for_syntax_check(html):
            return ["JavaScript 语法检查器不可用：未找到 node 可执行文件，不能保存 3D 交互 HTML。"]
        return []

    issues: list[str] = []
    for index, (extension, script) in enumerate(_script_blocks_for_syntax_check(html), start=1):
        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=extension, delete=False) as temp_file:
                temp_file.write(script)
                temp_path = temp_file.name
            completed = subprocess.run(
                [node_path, "--check", temp_path],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.debug("interactive_html_js_syntax_check_skipped", error=str(exc))
            continue
        finally:
            if temp_path:
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except OSError:
                    pass

        if completed.returncode != 0:
            stderr = re.sub(r"\s+", " ", completed.stderr or completed.stdout or "").strip()
            if len(stderr) > 360:
                stderr = stderr[:360].rstrip() + "..."
            issues.append(f"第 {index} 个 JavaScript 脚本存在语法错误：{stderr}")

    return issues


def _non_ascii_javascript_identifier_issues(html: str, widget_type: str) -> list[str]:
    if widget_type != "visualization3d":
        return []

    issues: list[str] = []
    for _extension, script in _script_blocks_for_syntax_check(html):
        cleaned_script = re.sub(r"(['\"`])(?:\\.|(?!\1).)*\1", '""', script, flags=re.DOTALL)
        cleaned_script = re.sub(r"//.*?$|/\*.*?\*/", "", cleaned_script, flags=re.MULTILINE | re.DOTALL)
        for match in re.finditer(r"[^\W\d]\w*", cleaned_script, flags=re.UNICODE):
            identifier = match.group(0)
            if all(ord(char) < 128 for char in identifier):
                continue
            issues.append(
                f"3D JavaScript 里出现非 ASCII 裸标识符：{identifier}。变量名必须使用英文/ASCII；"
                f"如果这是文本、标签、ID 或术语，必须写成字符串 \"{identifier}\"。"
            )
            if len(issues) >= 5:
                return issues
    return list(dict.fromkeys(issues))


def _suspicious_unquoted_identifier_issues(html: str, widget_type: str) -> list[str]:
    if widget_type != "visualization3d":
        return []

    issues: list[str] = []
    allowed_identifiers = {
        "Infinity",
        "NaN",
        "Math",
        "Number",
        "String",
        "Boolean",
        "Array",
        "Object",
        "Date",
        "JSON",
        "THREE",
        "OrbitControls",
        "window",
        "document",
        "console",
        "requestAnimationFrame",
        "setTimeout",
        "setInterval",
        "clearTimeout",
        "clearInterval",
        "undefined",
        "null",
        "true",
        "false",
    }
    for _extension, script in _script_blocks_for_syntax_check(html):
        cleaned_script = re.sub(r"(['\"`])(?:\\.|(?!\1).)*\1", '""', script, flags=re.DOTALL)
        cleaned_script = re.sub(r"//.*?$|/\*.*?\*/", "", cleaned_script, flags=re.MULTILINE | re.DOTALL)
        for match in re.finditer(
            r"[:\[,]\s*([^\W\d][\w\u0080-\uffff]{1,})\s*(?=[,\]}])",
            cleaned_script,
            flags=re.UNICODE,
        ):
            identifier = match.group(1)
            if identifier in allowed_identifiers or identifier[0].isupper():
                continue
            if "." in identifier:
                continue
            issues.append(f"JavaScript 里疑似把文本/ID 写成了未加引号的标识符：{identifier}。应写成字符串 \"{identifier}\"。")
            if len(issues) >= 5:
                return issues
    return list(dict.fromkeys(issues))


def _visualization3d_runtime_contract_issues(html: str, widget_type: str) -> list[str]:
    if widget_type != "visualization3d":
        return []

    text = str(html or "")
    script_text = "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script>", text, flags=re.IGNORECASE | re.DOTALL))
    issues: list[str] = []

    required_patterns = [
        (r'id\s*=\s*["\']loading["\']', "3D HTML 缺少 id=\"loading\" 加载层。"),
        (r'id\s*=\s*["\']canvas-container["\']', "3D HTML 缺少 id=\"canvas-container\" 渲染容器。"),
        (r"function\s+checkWebGL\s*\(", "3D HTML 缺少 checkWebGL() 支持检查。"),
        (r"(?:async\s+)?function\s+initScene\s*\(", "3D HTML 缺少 initScene() 初始化函数。"),
        (r"\binitScene\s*\(\s*\)\s*;?", "3D HTML 没有调用 initScene()。"),
        (r"new\s+THREE\.WebGLRenderer", "3D HTML 没有创建 Three.js WebGLRenderer。"),
        (r"renderer\.render\s*\(", "3D HTML 没有执行 renderer.render()。"),
        (r"requestAnimationFrame\s*\(", "3D HTML 缺少 requestAnimationFrame 渲染循环。"),
        (r"loading[^;\n]*(?:style\.display\s*=\s*['\"]none['\"]|\.remove\s*\()", "3D HTML 没有在场景就绪后隐藏 loading 层。"),
    ]
    for pattern, message in required_patterns:
        if not re.search(pattern, text, re.IGNORECASE | re.DOTALL):
            issues.append(message)

    has_error_overlay_update = bool(
        re.search(r"catch\s*\([^)]*\)\s*\{[\s\S]{0,1600}(?:innerHTML|textContent)", script_text, re.IGNORECASE)
    )
    if not has_error_overlay_update:
        issues.append("3D HTML 初始化失败时没有把 loading 层改成可见错误信息。")

    return list(dict.fromkeys(issues))


def _strict_interactive_html_review(
    *,
    raw_html: str,
    cleaned_html: str,
    title: str,
    context: str,
    design_brief: InteractionDesignBrief,
    resources_allowed: bool,
    allowed_resource_hosts: set[str] | None,
    widget_type: str,
) -> tuple[list[str], InteractiveHtmlQualityReport]:
    """Former strict gate retained for future quality-hardening.

    This used to be the active generation gate. It is intentionally not deleted:
    once generation quality is more stable, we can re-enable strict checks or
    run them as advisory telemetry without changing the rest of the pipeline.
    """

    completeness_issues = _generated_html_completeness_issues(raw_html)
    validation_issues = [
        *completeness_issues,
        *validate_single_file_html(
            cleaned_html,
            allow_external_resources=resources_allowed,
            allowed_resource_hosts=allowed_resource_hosts if resources_allowed else None,
        ),
        *_visualization3d_runtime_contract_issues(cleaned_html, widget_type),
        *_javascript_syntax_issues(
            cleaned_html,
            require_checker=widget_type == "visualization3d",
        ),
        *_non_ascii_javascript_identifier_issues(cleaned_html, widget_type),
        *_suspicious_unquoted_identifier_issues(cleaned_html, widget_type),
    ]
    validation_issues = list(dict.fromkeys(validation_issues))
    quality_report = (
        InteractiveHtmlQualityReport(passed=False, issues=tuple(completeness_issues))
        if completeness_issues
        else assess_interactive_html_quality(
            cleaned_html,
            title=title,
            context=context,
            design_brief=design_brief.as_prompt_text(),
        )
    )
    return validation_issues, quality_report


async def _generate_interactive_html_with_retry(
    *,
    title: str,
    digest_mode: str,
    context: str,
    design_brief: InteractionDesignBrief,
    base_metadata: Mapping[str, object],
    messages_factory: Callable[[Sequence[str]], list[dict[str, str]]],
    allow_external_resources: bool = False,
    allowed_resource_hosts: set[str] | None = None,
    fallback_messages_factory: Callable[[Sequence[str]], list[dict[str, str]]] | None = None,
    fallback_allow_external_resources: bool = False,
) -> _GeneratedInteractiveHtml:
    empty_result = _GeneratedInteractiveHtml(
        html="",
        validation_issues=["interactive HTML generation did not run"],
        quality_report=InteractiveHtmlQualityReport(passed=False, issues=("生成未执行。",)),
    )

    async def _run_factory(
        factory: Callable[[Sequence[str]], list[dict[str, str]]],
        *,
        route: str,
        resources_allowed: bool,
        initial_feedback: Sequence[str] = (),
    ) -> _GeneratedInteractiveHtml:
        last_feedback: tuple[str, ...] = tuple(item for item in initial_feedback if item)
        last_result = empty_result

        for attempt in range(2):
            raw_html = str(
                await acompletion_with_fallback(
                    factory(last_feedback),
                    **docgen_completion_kwargs_with_metadata(
                        DocGenModelStep.INTERACTIVE_HTML,
                        digest_mode=digest_mode,
                        extra_metadata={
                            **dict(base_metadata),
                            "generation_route": route,
                            "quality_attempt": attempt + 1,
                            "quality_retry": attempt > 0,
                            "quality_retry_issue_count": len(last_feedback),
                            "allow_external_resources": resources_allowed,
                        },
                    ),
                )
                or ""
            )
            cleaned_html = _sanitize_generated_html(
                raw_html,
                title=title,
                allow_external_resources=resources_allowed,
                allowed_resource_hosts=allowed_resource_hosts if resources_allowed else None,
            )
            widget_type = str(base_metadata.get("widget_type") or "")
            validation_issues, quality_report = _openmaic_style_interactive_html_review(
                raw_html=raw_html,
                cleaned_html=cleaned_html,
                allowed_resource_hosts=allowed_resource_hosts if resources_allowed else None,
                widget_type=widget_type,
            )
            last_result = _GeneratedInteractiveHtml(
                html=cleaned_html,
                validation_issues=validation_issues,
                quality_report=quality_report,
                widget_config=extract_widget_config(cleaned_html),
            )
            if _interactive_generation_passed(last_result):
                return last_result
            last_feedback = tuple([*validation_issues, *quality_report.issues])

        return last_result

    primary_result = await _run_factory(
        messages_factory,
        route="widget" if allow_external_resources else "legacy",
        resources_allowed=allow_external_resources,
    )
    if _interactive_generation_passed(primary_result) or fallback_messages_factory is None:
        return primary_result

    return await _run_factory(
        fallback_messages_factory,
        route="legacy_fallback",
        resources_allowed=fallback_allow_external_resources,
        initial_feedback=[*primary_result.validation_issues, *primary_result.quality_report.issues],
    )


async def _generate_interactive_widget_outline(
    *,
    anchor_title: str,
    heading_path: Sequence[str],
    selected_text: str,
    user_prompt: str,
    section_excerpt: str,
    design_brief: InteractionDesignBrief,
    digest_mode: str,
    base_metadata: Mapping[str, object],
) -> InteractiveOutlineDecision | None:
    try:
        response = await acompletion_with_fallback(
            build_interactive_widget_outline_messages(
                anchor_title=anchor_title,
                heading_path=heading_path,
                selected_text=selected_text,
                user_prompt=user_prompt,
                section_excerpt=section_excerpt,
                design_brief=design_brief.as_prompt_text(),
            ),
            response_model=InteractiveOutlineDecision,
            **docgen_completion_kwargs_with_metadata(
                DocGenModelStep.INTERACTIVE_HTML,
                digest_mode=digest_mode,
                extra_metadata={
                    **dict(base_metadata),
                    "docgen_stage": "interactive_widget_outline",
                },
            ),
        )
    except Exception as exc:
        logger.warning(
            "docgen_interactive_widget_outline_failed",
            anchor_title=anchor_title,
            error=str(exc)[:240],
        )
        return None

    try:
        return (
            response
            if isinstance(response, InteractiveOutlineDecision)
            else InteractiveOutlineDecision.model_validate(response)
        )
    except Exception as exc:
        logger.warning(
            "docgen_interactive_widget_outline_invalid",
            anchor_title=anchor_title,
            error=str(exc)[:240],
        )
        return None


def _build_preview_url(*, course_id: str, asset_path: str, title: str) -> str:
    from urllib.parse import quote

    return (
        f"/courses/{quote(course_id)}/knowledge-docs/interactive"
        f"?asset={quote(asset_path, safe='/')}"
        f"&title={quote(title)}"
    )


def _build_auto_preview_url(
    *,
    course_id: str,
    plan_id: str,
    anchor_id: str,
    title: str,
    selected_text: str,
    prompt: str,
) -> str:
    from urllib.parse import quote

    return (
        f"/courses/{quote(course_id)}/knowledge-docs/interactive-auto"
        f"?plan={quote(plan_id)}"
        f"&anchor={quote(anchor_id)}"
        f"&title={quote(title)}"
        f"&selected={quote(selected_text[:900])}"
        f"&prompt={quote(prompt[:500])}"
    )


def _build_markdown_link(*, preview_url: str, link_label: str) -> str:
    return f"[{link_label}]({preview_url})"


def build_interactive_markdown_link(*, preview_url: str, link_label: str) -> str:
    return _build_markdown_link(preview_url=preview_url, link_label=link_label)


def _selection_title(*, anchor_title: str, selected_text: str, user_prompt: str) -> str:
    del user_prompt
    seed = (anchor_title or selected_text or "交互演示").strip()
    seed = re.sub(r"\s+", " ", seed)
    seed = seed.strip(" ：:，,。；;")
    if len(seed) > 18:
        seed = seed[:18].rstrip(" ：:，,。；;") + "..."
    return f"{seed}交互演示" if seed and seed != "交互演示" else "交互演示"


async def generate_selection_interactive_html_asset(
    *,
    course_id: str,
    course_scope: CourseStorageScope | None = None,
    traced_context: TracedExecutionContext,
    anchor_title: str,
    heading_path: Sequence[str],
    selected_text: str,
    user_prompt: str,
    section_excerpt: str,
) -> dict[str, object]:
    generated_result = await generate_selection_interactive_html(
        traced_context=traced_context,
        anchor_title=anchor_title,
        heading_path=heading_path,
        selected_text=selected_text,
        user_prompt=user_prompt,
        section_excerpt=section_excerpt,
    )
    title = generated_result.title
    cleaned_html = generated_result.html
    validation_issues = generated_result.validation_issues

    cs = get_content_store()
    course_scope = course_scope or resolve_course_storage_scope(course_id)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    filename = f"selection_interactive_{timestamp}_{uuid.uuid4().hex[:8]}_{sanitize_doc_title(title)}.html"
    storage_key = f"{course_scope.namespace}/assets/docgen/interactive/{filename}"
    asset_path = f"docgen/interactive/{filename}"
    await cs.write_text(storage_key, cleaned_html)
    preview_url = _build_preview_url(course_id=course_id, asset_path=asset_path, title=title)
    return {
        "title": title,
        "storage_key": storage_key,
        "asset_path": asset_path,
        "asset_url": f"/api/v1/courses/{course_id}/files/assets/{asset_path}",
        "preview_url": preview_url,
        "link_markdown": _build_markdown_link(preview_url=preview_url, link_label=title),
        "validation_issues": validation_issues,
        "quality_issues": generated_result.quality_issues,
        "design_brief": generated_result.design_brief,
        "widget_type": generated_result.widget_type,
        "widget_outline": generated_result.widget_outline,
        "widget_config": generated_result.widget_config,
        "language_directive": generated_result.language_directive,
    }


async def generate_selection_interactive_html(
    *,
    traced_context: TracedExecutionContext,
    anchor_title: str,
    heading_path: Sequence[str],
    selected_text: str,
    user_prompt: str,
    section_excerpt: str,
    docgen_stage: str = "interactive_html_selection",
    extra_metadata: Mapping[str, object] | None = None,
) -> GeneratedSelectionInteractiveHtml:
    title = _selection_title(
        anchor_title=anchor_title,
        selected_text=selected_text,
        user_prompt=user_prompt,
    )
    design_brief = build_selection_interaction_design_brief(
        anchor_title=anchor_title,
        selected_text=selected_text,
        user_prompt=user_prompt,
        section_excerpt=section_excerpt,
    )
    selection_context = "\n".join([selected_text, section_excerpt])
    base_metadata = traced_context.trace_metadata(
        docgen_stage=docgen_stage,
        asset_kind="interactive_html",
        design_brief=design_brief.as_metadata(),
    )
    if extra_metadata:
        base_metadata.update(
            {
                key: value
                for key, value in dict(extra_metadata).items()
                if value not in (None, "", [], {})
            }
        )
    outline_decision = await _generate_interactive_widget_outline(
        anchor_title=anchor_title,
        heading_path=heading_path,
        selected_text=selected_text,
        user_prompt=user_prompt,
        section_excerpt=section_excerpt,
        design_brief=design_brief,
        digest_mode=traced_context.digest_mode or "",
        base_metadata=base_metadata,
    )
    outline: InteractiveSceneOutline | None = None
    if outline_decision is not None:
        outline = outline_decision.first_interactive_outline()
        if outline.title and outline.title != "交互演示":
            title = outline.title

    def legacy_messages_factory(retry_feedback: Sequence[str]) -> list[dict[str, str]]:
        return build_selection_interactive_html_messages(
            anchor_title=anchor_title,
            heading_path=heading_path,
            selected_text=selected_text,
            user_prompt=user_prompt,
            section_excerpt=section_excerpt,
            design_brief=design_brief.as_prompt_text(),
            retry_feedback=retry_feedback,
        )
    if outline is not None and outline_decision is not None:
        generated = await _generate_interactive_html_with_retry(
            title=title,
            digest_mode=traced_context.digest_mode or "",
            context=selection_context,
            design_brief=design_brief,
            base_metadata={
                **dict(base_metadata),
                "widget_type": outline.widgetType,
                "widget_outline": outline.widgetOutline.model_dump(),
                "language_directive": outline_decision.languageDirective,
            },
            messages_factory=lambda retry_feedback: build_widget_interactive_html_messages(
                outline=outline,
                language_directive=outline_decision.languageDirective,
                source_context=selection_context,
                design_brief=design_brief.as_prompt_text(),
                retry_feedback=retry_feedback,
            ),
            allow_external_resources=True,
            allowed_resource_hosts=INTERACTIVE_ALLOWED_RESOURCE_HOSTS,
            fallback_messages_factory=legacy_messages_factory,
        )
    else:
        generated = await _generate_interactive_html_with_retry(
            title=title,
            digest_mode=traced_context.digest_mode or "",
            context=selection_context,
            design_brief=design_brief,
            base_metadata={**dict(base_metadata), "generation_route": "legacy_no_outline"},
            messages_factory=legacy_messages_factory,
        )
    cleaned_html = generated.html
    validation_issues = generated.validation_issues
    if validation_issues:
        raise ValueError("generated interactive HTML failed validation: " + "; ".join(validation_issues))
    if not generated.quality_report.passed:
        raise ValueError(
            "generated interactive HTML failed quality check: " + "; ".join(generated.quality_report.issues)
        )

    return GeneratedSelectionInteractiveHtml(
        title=title,
        html=cleaned_html,
        validation_issues=validation_issues,
        quality_issues=list(generated.quality_report.issues),
        design_brief=design_brief.as_metadata(),
        widget_type=outline.widgetType if outline is not None else "",
        widget_outline=outline.widgetOutline.model_dump() if outline is not None else {},
        widget_config=generated.widget_config or {},
        language_directive=outline_decision.languageDirective if outline_decision is not None else "",
    )


async def maybe_generate_interactive_html_asset(
    *,
    draft: ChapterDraft,
    traced_context: TracedExecutionContext,
    digest_mode: str,
    claim_ledger: ClaimLedger | None = None,
    document_backbone: DocumentBackbone | None = None,
    markdown: str | None = None,
) -> dict[str, object] | None:
    assets = await maybe_generate_interactive_html_assets(
        draft=draft,
        traced_context=traced_context,
        digest_mode=digest_mode,
        claim_ledger=claim_ledger,
        document_backbone=document_backbone,
        markdown=markdown,
        max_assets=1,
    )
    return assets[0] if assets else None


def plan_interactive_html_assets(
    *,
    draft: ChapterDraft,
    course_id: str,
    markdown: str | None = None,
    max_assets: int = 3,
) -> list[dict[str, object]]:
    working_markdown = markdown if markdown is not None else draft.markdown
    candidates = _select_interactive_section_candidates(
        working_markdown,
        fallback_title=draft.title,
        max_count=max_assets,
    )
    plans: list[dict[str, object]] = []
    for candidate in candidates:
        plan_id = f"ch{draft.chapter_index:02d}_interactive_{candidate.index:02d}"
        title = candidate.title or draft.title
        link_label = f"{title} 交互演示"
        preview_url = _build_auto_preview_url(
            course_id=course_id,
            plan_id=plan_id,
            anchor_id=candidate.heading_id,
            title=link_label,
            selected_text=candidate.context or title,
            prompt="",
        )
        plans.append(
            {
                "asset_id": plan_id,
                "chapter_index": draft.chapter_index,
                "kind": "interactive",
                "status": "planned",
                "title": link_label,
                "anchor_heading": title,
                "anchor_heading_id": candidate.heading_id,
                "anchor_heading_level": candidate.level,
                "insert_at": candidate.insert_at,
                "preview_url": preview_url,
                "open_mode": "inline_lazy",
                "link_markdown": (
                    f"<!-- ATM_INTERACTIVE_PLAN:{plan_id} -->\n"
                    f"{_build_markdown_link(preview_url=preview_url, link_label=link_label)}"
                ),
            }
        )
    return plans


async def maybe_generate_interactive_html_assets(
    *,
    draft: ChapterDraft,
    traced_context: TracedExecutionContext,
    digest_mode: str,
    claim_ledger: ClaimLedger | None = None,
    document_backbone: DocumentBackbone | None = None,
    markdown: str | None = None,
    max_assets: int = 3,
) -> list[dict[str, object]]:
    del document_backbone
    working_markdown = markdown if markdown is not None else draft.markdown
    candidates = _select_interactive_section_candidates(
        working_markdown,
        fallback_title=draft.title,
        max_count=max_assets,
    )
    if not candidates:
        return []

    interaction_mode = choose_interactive_mode(draft, claim_ledger=claim_ledger)
    concept_targets = [item.claim_text for item in list((claim_ledger or ClaimLedger()).items or []) if item.claim_type in {"definition", "core", "method"}][:4]
    formula_targets = [item.claim_text for item in list((claim_ledger or ClaimLedger()).items or []) if item.claim_type == "formula"][:3]
    claim_targets = [item.claim_text for item in list((claim_ledger or ClaimLedger()).items or []) if item.claim_text][:5]

    async def _generate_one(candidate: _InteractiveSectionCandidate) -> dict[str, object] | None:
        title = candidate.title or draft.title
        context = candidate.context or _chapter_context_excerpt(draft)
        design_brief = build_chapter_interaction_design_brief(
            title=title,
            objective=draft.summary_draft,
            context=context,
            interaction_mode=interaction_mode,
            concept_targets=concept_targets,
            formula_targets=formula_targets,
            claim_targets=claim_targets,
        )
        base_metadata = traced_context.trace_metadata(
            docgen_stage="interactive_html_sidecar",
            asset_kind="interactive_html",
            chapter_index=draft.chapter_index,
            section_index=candidate.index,
            section_title=title,
            design_brief=design_brief.as_metadata(),
        )
        outline_decision = await _generate_interactive_widget_outline(
            anchor_title=title,
            heading_path=[draft.title, title],
            selected_text=context,
            user_prompt="",
            section_excerpt=context,
            design_brief=design_brief,
            digest_mode=digest_mode,
            base_metadata=base_metadata,
        )
        outline: InteractiveSceneOutline | None = None
        if outline_decision is not None:
            outline = outline_decision.first_interactive_outline()
            if outline.title and outline.title != "交互演示":
                title = outline.title

        def legacy_messages_factory(retry_feedback: Sequence[str]) -> list[dict[str, str]]:
            return build_interactive_html_messages(
                chapter_title=title,
                chapter_objective=draft.summary_draft,
                digest_mode=digest_mode,
                interaction_mode=interaction_mode,
                design_brief=design_brief.as_prompt_text(),
                concept_targets=concept_targets,
                formula_targets=formula_targets,
                claim_targets=claim_targets,
                chapter_context=context,
                retry_feedback=retry_feedback,
            )
        if outline is not None and outline_decision is not None:
            generated = await _generate_interactive_html_with_retry(
                title=title,
                digest_mode=digest_mode,
                context=context,
                design_brief=design_brief,
                base_metadata={
                    **dict(base_metadata),
                    "widget_type": outline.widgetType,
                    "widget_outline": outline.widgetOutline.model_dump(),
                    "language_directive": outline_decision.languageDirective,
                },
                messages_factory=lambda retry_feedback: build_widget_interactive_html_messages(
                    outline=outline,
                    language_directive=outline_decision.languageDirective,
                    source_context=context,
                    design_brief=design_brief.as_prompt_text(),
                    retry_feedback=retry_feedback,
                ),
                allow_external_resources=True,
                allowed_resource_hosts=INTERACTIVE_ALLOWED_RESOURCE_HOSTS,
                fallback_messages_factory=legacy_messages_factory,
            )
        else:
            generated = await _generate_interactive_html_with_retry(
                title=title,
                digest_mode=digest_mode,
                context=context,
                design_brief=design_brief,
                base_metadata={**dict(base_metadata), "generation_route": "legacy_no_outline"},
                messages_factory=legacy_messages_factory,
            )
        cleaned_html = generated.html
        validation_issues = generated.validation_issues
        if validation_issues:
            logger.warning(
                "docgen_interactive_html_skipped_after_validation",
                chapter_index=draft.chapter_index,
                chapter_title=draft.title,
                section_title=title,
                validation_issues=validation_issues,
            )
            return None
        if not generated.quality_report.passed:
            logger.warning(
                "docgen_interactive_html_skipped_after_quality_check",
                chapter_index=draft.chapter_index,
                chapter_title=draft.title,
                section_title=title,
                quality_issues=list(generated.quality_report.issues),
                design_brief=design_brief.as_metadata(),
            )
            return None
        cs = get_content_store()
        course_scope = resolve_course_storage_scope(traced_context.course_id)
        filename = (
            f"docgen_interactive_{traced_context.build_session_id}_ch{draft.chapter_index:02d}"
            f"_s{candidate.index:02d}_{sanitize_doc_title(title)}.html"
        )
        storage_key = f"{course_scope.namespace}/assets/docgen/interactive/{filename}"
        asset_path = f"docgen/interactive/{filename}"
        await cs.write_text(storage_key, cleaned_html)
        preview_url = _build_preview_url(course_id=traced_context.course_id, asset_path=asset_path, title=title)
        link_label = f"{title} 交互演示"
        return {
            "asset_id": f"ch{draft.chapter_index:02d}_interactive_{candidate.index:02d}",
            "chapter_index": draft.chapter_index,
            "kind": "interactive",
            "title": link_label,
            "interaction_mode": interaction_mode,
            "anchor_heading": title,
            "anchor_heading_level": candidate.level,
            "insert_at": candidate.insert_at,
            "storage_key": storage_key,
            "asset_path": asset_path,
            "asset_url": f"/api/v1/courses/{traced_context.course_id}/files/assets/{asset_path}",
            "preview_url": preview_url,
            "open_mode": "inline",
            "link_markdown": _build_markdown_link(preview_url=preview_url, link_label=link_label),
            "validation_issues": validation_issues,
            "quality_issues": list(generated.quality_report.issues),
            "design_brief": design_brief.as_metadata(),
            "widget_type": outline.widgetType if outline is not None else "",
            "widget_outline": outline.widgetOutline.model_dump() if outline is not None else {},
            "widget_config": generated.widget_config or {},
            "language_directive": outline_decision.languageDirective if outline_decision is not None else "",
        }

    results = await run_llm_tasks(
        candidates,
        _generate_one,
    )
    return [item for item in results if item is not None]


__all__ = [
    "GeneratedSelectionInteractiveHtml",
    "build_interactive_markdown_link",
    "choose_interactive_mode",
    "generate_selection_interactive_html",
    "generate_selection_interactive_html_asset",
    "maybe_generate_interactive_html_asset",
    "maybe_generate_interactive_html_assets",
    "plan_interactive_html_assets",
    "should_generate_interactive_html",
]
