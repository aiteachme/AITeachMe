"""Lightweight markdown processing helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import urlparse

from markdown_it import MarkdownIt

MERMAID_PLACEHOLDER_PATTERN = re.compile(r"<!--\s*\[MERMAID:\s*(.+?)\]\s*-->")
IMAGE_PLACEHOLDER_PATTERN = re.compile(r"<!--\s*\[IMAGE:\s*(.+?)\]\s*-->")
HEADER_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
KNOWLEDGE_ANCHOR_PATTERN = re.compile(
    r"\s*(?:\{#ku_[\w-]+\}|<!--\s*ATM_KU:\s*ku_[\w-]+\s*-->)"
)
MERMAID_START_PATTERN = re.compile(
    r"^(?P<prefix>(?:>\s*)*)```\s*(?P<lang>mermaid|mindmap|graph|flowchart|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|erDiagram|gantt|pie|journey|timeline|gitGraph)?\s*$",
    re.IGNORECASE,
)
MERMAID_FENCE_PATTERN = re.compile(r"^```(?P<trailing>.*)$")
MARKDOWN_BOUNDARY_PATTERN = re.compile(r"^(#{1,6}\s+\S|[-*+]\s+\S|\d+\.\s+\S|>\s*\S|\|.+\||---\s*$)")
MERMAID_KEYWORD_PATTERN = re.compile(
    r"^(mindmap|graph|flowchart|sequencediagram|classdiagram|statediagram(?:-v2)?|erdiagram|gantt|pie|journey|timeline|gitgraph)\b",
    re.IGNORECASE,
)
MERMAID_INFO_PATTERN = re.compile(
    r"^(mermaid|mindmap|graph|flowchart|sequencediagram|classdiagram|statediagram(?:-v2)?|erdiagram|gantt|pie|journey|timeline|gitgraph)\b",
    re.IGNORECASE,
)
FLOWCHART_HEADER_PATTERN = re.compile(r"^(?:flowchart|graph)\b", re.IGNORECASE)
FLOWCHART_INLINE_HEADER_PATTERN = re.compile(
    r"^\s*((?:flowchart|graph)\s+(?:TD|TB|BT|LR|RL))\s+(.+)$",
    re.IGNORECASE,
)
FLOWCHART_NODE_LABEL_PATTERN = re.compile(r"(^|[^\w\"'])([A-Za-z_][\w-]*)\s*\[([^\]\n]+)\]")
FLOWCHART_EDGE_LABEL_PATTERN = re.compile(r"\|([^|\n]+)\|")
FLOWCHART_CLASS_LINE_PATTERN = re.compile(r"^(\s*class\s+)([^;\n]+?)(;?\s*)$", re.IGNORECASE)
FLOWCHART_CONTROL_LINE_PATTERN = re.compile(
    r"^\s*(?:%%|flowchart|graph|subgraph|end\b|direction\b|classDef\b|class\b|style\b|"
    r"linkStyle\b|click\b|accTitle\b|accDescr\b|title\b)",
    re.IGNORECASE,
)
FLOWCHART_EDGE_LINE_PATTERN = re.compile(r"^\s*[A-Za-z_][\w-]*\s*(?:-->|---|==>|-.->|==|--|~~~|o--|x--)")
FLOWCHART_NODE_LINE_PATTERN = re.compile(r"^\s*[A-Za-z_][\w-]*\s*(?:\[|\(|\{|\>)")
MINDMAP_ROOT_PATTERN = re.compile(r"^root\(\((.+)\)\)$", re.IGNORECASE)
MINDMAP_MIXED_SYNTAX_PATTERN = re.compile(
    r"-->|==>|\b(?:graph|flowchart|sequencediagram|classdiagram|statediagram|erdiagram|gantt)\b",
    re.IGNORECASE,
)
RAW_MERMAID_FENCE_PATTERN = re.compile(
    r"(?m)^\s{0,3}```\s*(?:mermaid|mindmap|graph|flowchart|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|erDiagram|gantt|pie|journey|timeline|gitGraph)\b",
    re.IGNORECASE,
)
MALFORMED_MERMAID_FENCE_PATTERN = re.compile(r"^\s*```\s*(?P<trailing>.+)$")
INLINE_FENCE_PATTERN = re.compile(r"^(?P<prefix>.*\S)\s*```\s*(?P<lang>[A-Za-z0-9_-]*)\s*$")
STUCK_MATH_FENCE_PATTERN = re.compile(
    r"(?m)^(?P<prefix>\s*)\$\$[ \t]*(?P<fence>```[ \t]*[A-Za-z0-9_-]*[ \t]*)$"
)
BLOCKQUOTE_PREFIX_PATTERN = re.compile(r"^\s*>\s?")
MATH_FENCE_PATTERN = re.compile(r"^\s*(?:>\s*)?\$\$\s*$")
CALLOUT_KINDS_PATTERN = r"NOTE|TIP|IMPORTANT|WARNING|CAUTION|EXAMPLE|PRACTICE"
CALLOUT_LINE_PATTERN = re.compile(
    rf"^(?P<indent>\s*)(?P<quote>>\s*)?\[!(?P<kind>{CALLOUT_KINDS_PATTERN})\](?P<rest>.*)$",
    re.IGNORECASE,
)
CALLOUT_FIELD_LABEL_PATTERN = (
    r"题目/任务|解析/判定依据|答案/结论|判定依据|正确答案|参考答案|"
    r"题目|任务|案例|例题|解析|解法|步骤|答案|结论|易错点|错因|注意"
)
CALLOUT_FIELD_MARKER_TOKEN_PATTERN = re.compile(
    rf"(?<!\*)\s*(?:\*\*(?:{CALLOUT_FIELD_LABEL_PATTERN})\*\*|(?:{CALLOUT_FIELD_LABEL_PATTERN}))\s*[：:]"
)
CALLOUT_FIELD_SPLIT_PATTERN = re.compile(
    rf"(?<!\*)(?=\s*(?:\*\*(?:{CALLOUT_FIELD_LABEL_PATTERN})\*\*|(?:{CALLOUT_FIELD_LABEL_PATTERN}))\s*[：:])"
)
LEARNING_CALLOUT_TASK_FIELD_PATTERN = re.compile(r"(题目/任务|题目|任务|案例|例题)", re.IGNORECASE)
LEARNING_CALLOUT_REASON_FIELD_PATTERN = re.compile(r"(解析/判定依据|解析|解法|步骤|判定依据|错因)", re.IGNORECASE)
LEARNING_CALLOUT_ANSWER_FIELD_PATTERN = re.compile(r"(答案/结论|答案|结论|正确答案|参考答案)", re.IGNORECASE)
BARE_CALLOUT_PATTERN = re.compile(
    rf"(?m)^(?!\s*>)\s*\[!(?:{CALLOUT_KINDS_PATTERN})\]",
    re.IGNORECASE,
)
RAW_MARK_OPEN_PATTERN = re.compile(r"<mark\b[^>]*>", re.IGNORECASE)
RAW_MARK_CLOSE_PATTERN = re.compile(r"</mark>", re.IGNORECASE)
RAW_HTML_TAG_PATTERN = re.compile(r"</?(?!mark\b|br\b)[A-Za-z][^>\n]{0,120}>", re.IGNORECASE)
DOUBLE_EQUALS_HIGHLIGHT_PATTERN = re.compile(r"==\s*(?P<body>[^=\n]{1,160}?)\s*==")
RAW_MARK_HIGHLIGHT_PATTERN = re.compile(r"<mark\b[^>]*>\s*(?P<body>[^<>\n]{1,160}?)\s*</mark>", re.IGNORECASE)
FLOWCHART_RELATION_LABEL_PATTERN = re.compile(r"--[^|\n]*\|(?P<label>[^|\n]{1,24})\|[^-\n]*--?>|-->\s*\|(?P<label2>[^|\n]{1,24})\|")
KNOWLEDGE_GRAPH_RELATION_LABELS = {
    "前置",
    "归属",
    "推导",
    "应用",
    "用方法",
    "考察",
    "解释",
    "补救",
    "易混",
    "相似",
    "拓展",
    "part_of",
    "prerequisite_for",
    "derives_to",
    "applies_to",
    "uses_method",
    "assesses",
    "explains",
    "remediates",
    "confuses_with",
    "similar_to",
    "extends_to",
}
MATH_MARKDOWN_BOUNDARY_PATTERN = re.compile(
    r"^(?:#{1,6}\s+\S|[-*+]\s+(?:\*\*|`|\[|.{12,})|\d+\.\s+\S|>\s*\S|"
    rf"\[!(?:{CALLOUT_KINDS_PATTERN})\]|```)",
    re.IGNORECASE,
)
INLINE_MATH_MARKDOWN_PATTERN = re.compile(
    r"(^|\n)\s*(?:#{1,6}\s+\S|[-*+]\s+(?:\*\*|`|\[|.{12,})|\d+\.\s+\S|>\s*\S|"
    rf"\[!(?:{CALLOUT_KINDS_PATTERN})\]|```)",
    re.IGNORECASE,
)
_MARKDOWN_PARSER = MarkdownIt("commonmark")


def _trim_blank_lines(lines: list[str]) -> list[str]:
    trimmed = list(lines)
    while trimmed and not trimmed[0].strip():
        trimmed.pop(0)
    while trimmed and not trimmed[-1].strip():
        trimmed.pop()
    return trimmed


def _split_callout_learning_fields(line: str) -> list[str]:
    stripped = str(line or "").strip()
    if not stripped:
        return [line]
    if re.match(r"^(?:[-*+]|\d+\.)\s+", stripped):
        return [line]
    if len(CALLOUT_FIELD_MARKER_TOKEN_PATTERN.findall(stripped)) < 2:
        return [line]
    parts = [part.strip() for part in CALLOUT_FIELD_SPLIT_PATTERN.split(stripped) if part.strip()]
    return parts if len(parts) > 1 else [line]


def _normalize_callout_body_lines(body_lines: list[str]) -> list[str]:
    normalized: list[str] = []
    for body_line in body_lines:
        parts = _split_callout_learning_fields(body_line)
        if len(parts) <= 1:
            normalized.append(body_line)
            continue
        if normalized and normalized[-1].strip():
            normalized.append("")
        for index, part in enumerate(parts):
            if index > 0:
                normalized.append("")
            normalized.append(part)
    return _trim_blank_lines(normalized)


def _append_callout_block(output: list[str], *, kind: str, body_lines: list[str]) -> None:
    body = _normalize_callout_body_lines(_trim_blank_lines(body_lines))
    output.append(f"> [!{kind.upper()}]")
    if not body:
        output.append("")
        return
    # react-markdown does not implement GitHub's callout extension. Keeping the
    # marker in its own blockquote paragraph lets the frontend recognize it
    # without flattening the marker and body into one ordinary quote paragraph.
    output.append(">")
    for body_line in body:
        output.append(f"> {body_line}" if body_line.strip() else ">")
    output.append("")



def extract_mermaid_placeholders(markdown: str) -> list[str]:
    return [match.strip() for match in MERMAID_PLACEHOLDER_PATTERN.findall(markdown)]



def extract_image_placeholders(markdown: str) -> list[str]:
    return [match.strip() for match in IMAGE_PLACEHOLDER_PATTERN.findall(markdown)]



def count_words(markdown: str) -> int:
    compact = re.sub(r"\s+", "", markdown).strip()
    return len(compact)


def _strip_blockquote_prefix(line: str, *, prefix: str) -> str:
    candidate = str(line or "")
    if prefix and candidate.startswith(prefix):
        candidate = candidate[len(prefix) :]
    return re.sub(r"^(?:>\s*)+", "", candidate)


def _looks_like_mermaid_line(line: str) -> bool:
    stripped = str(line or "").strip()
    if not stripped:
        return True
    if MERMAID_KEYWORD_PATTERN.match(stripped):
        return True
    if line.startswith((" ", "\t")):
        return True
    if stripped.startswith(("%%", ":::", "subgraph ", "style ", "classDef ", "class ", "click ", "section ", "title ")):
        return True
    if any(token in stripped for token in ("-->", "---", "==>", "|", "[", "]", "(", ")", "{", "}")):
        return True
    return False


def _looks_like_mermaid_garbage(line: str) -> bool:
    stripped = str(line or "").strip()
    if not stripped:
        return False
    return any(token in stripped for token in ("-->", "[", "]", "classDef", "subgraph"))


def _sanitize_mermaid_label(value: str, *, max_length: int = 44) -> str:
    cleaned = str(value or "").strip().strip("\"'")
    cleaned = cleaned.replace("\\n", " ")
    cleaned = re.sub(r"[`$#]+", " ", cleaned)
    cleaned = re.sub(r"[{}]+", " ", cleaned)
    cleaned = cleaned.replace("|", " ")
    cleaned = cleaned.replace(">", "大于").replace("<", "小于").replace("=", "等于")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return (cleaned[:max_length].strip() or "节点").rstrip("：:，,。；; ")


def _normalize_flowchart_control_line(line: str) -> str:
    if re.match(r"^\s*classDef\b", line, re.IGNORECASE):
        return line
    match = FLOWCHART_CLASS_LINE_PATTERN.match(line)
    if match is None:
        return line

    prefix = match.group(1) or ""
    body = (match.group(2) or "").strip()
    suffix = match.group(3) or ""
    parts = [part for part in re.split(r"\s+", body) if part]
    if len(parts) < 2:
        return line

    class_name = parts.pop()
    node_list = ",".join(node_id.strip() for node_id in " ".join(parts).split(",") if node_id.strip())
    if not node_list or not class_name:
        return line
    return f"{prefix}{node_list} {class_name}{suffix}"


def _quote_flowchart_labels(line: str) -> str:
    if re.match(r"^\s*(?:classDef|class|style|linkStyle|click)\b", line, re.IGNORECASE):
        return _normalize_flowchart_control_line(line)

    def replace_node_label(match: re.Match[str]) -> str:
        label = _sanitize_mermaid_label(match.group(3)).replace('"', "'")
        return f'{match.group(1)}{match.group(2)}["{label}"]'

    def replace_edge_label(match: re.Match[str]) -> str:
        label = _sanitize_mermaid_label(match.group(1), max_length=32).replace('"', "'")
        return f"|{label}|"

    quoted = FLOWCHART_NODE_LABEL_PATTERN.sub(replace_node_label, line)
    return FLOWCHART_EDGE_LABEL_PATTERN.sub(replace_edge_label, quoted)


def _split_inline_flowchart_header(line: str) -> list[str]:
    match = FLOWCHART_INLINE_HEADER_PATTERN.match(line)
    if match is None:
        return [line]
    header = match.group(1).strip()
    body = match.group(2).strip()
    if not header or not body:
        return [line]
    return [header, body]


def _normalize_flowchart_line(line: str, index: int) -> str:
    quoted = _quote_flowchart_labels(line)
    stripped = quoted.strip()
    if not stripped:
        return quoted
    if (
        FLOWCHART_CONTROL_LINE_PATTERN.search(stripped)
        or FLOWCHART_EDGE_LINE_PATTERN.search(stripped)
        or FLOWCHART_NODE_LINE_PATTERN.search(stripped)
    ):
        return quoted
    label = _sanitize_mermaid_label(stripped).replace('"', "'")
    return f'ATM_AUTO_{index}["{label}"]'


def _sanitize_flowchart_source(source: str) -> str:
    lines: list[str] = []
    for raw_line in str(source or "").splitlines():
        if not raw_line.strip():
            continue
        lines.extend(_split_inline_flowchart_header(raw_line.rstrip()))
    if not lines:
        return "flowchart TD"
    if not FLOWCHART_HEADER_PATTERN.match(lines[0].strip()):
        lines.insert(0, "flowchart TD")
    return "\n".join(_normalize_flowchart_line(line, index) for index, line in enumerate(lines)).strip()


def _sanitize_mindmap_label(value: str, *, max_length: int = 28) -> str:
    cleaned = re.sub(
        r"\b(?:mindmap|root|graph|flowchart|subgraph|classDef|class|style|click|section|title|LR|RL|TB|BT)\b",
        " ",
        str(value or ""),
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"[`$#<>{}\[\]]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_length].rstrip("：:，,。；; ")


def _extract_mindmap_labels(source: str, *, limit: int = 6) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()

    def push(value: str) -> None:
        cleaned = _sanitize_mindmap_label(value)
        if not cleaned:
            return
        key = cleaned.casefold()
        if key in seen:
            return
        seen.add(key)
        labels.append(cleaned)

    for match in re.finditer(r"root\(\((.+?)\)\)", source, re.IGNORECASE):
        push(match.group(1))
    for match in re.finditer(r"\[([^\]]+)\]", source):
        push(match.group(1))

    for raw_line in str(source or "").splitlines():
        line = raw_line.strip()
        if not line or line.lower() == "mindmap" or line.startswith("```"):
            continue
        root_match = MINDMAP_ROOT_PATTERN.match(line)
        if root_match is not None:
            push(root_match.group(1))
            continue
        if MINDMAP_MIXED_SYNTAX_PATTERN.search(line):
            arrow_labels = re.findall(r"\[([^\]]+)\]", line)
            if arrow_labels:
                for item in arrow_labels:
                    push(item)
            else:
                push(line.split("-->")[-1].split("==>")[-1])
            continue
        push(re.sub(r"^[-*+]\s+", "", line))
        if len(labels) >= limit:
            break
    return labels[:limit]


def _build_simplified_mindmap(source: str) -> str:
    labels = _extract_mindmap_labels(source, limit=6)
    root = labels[0] if labels else "核心主题"
    lines = ["mindmap", f"  root(({root}))"]
    for label in labels[1:]:
        lines.append(f"    {label}")
    return "\n".join(lines)


def _sanitize_mindmap_source(source: str) -> str:
    raw_lines = [line.rstrip() for line in str(source or "").splitlines() if line.strip()]
    if not raw_lines or not raw_lines[0].strip().lower().startswith("mindmap"):
        return _build_simplified_mindmap(source)
    body_lines = raw_lines[1:]
    if any(MINDMAP_MIXED_SYNTAX_PATTERN.search(line) for line in body_lines):
        return _build_simplified_mindmap(source)

    output = ["mindmap"]
    has_root = False
    child_count = 0
    for raw_line in body_lines:
        expanded = raw_line.replace("\t", "  ")
        indent_chars = len(re.match(r"^\s*", expanded).group(0))
        indent_level = max(1, indent_chars // 2)
        stripped = re.sub(r"^[-*+]\s+", "", expanded.strip())
        if not stripped:
            continue
        root_match = MINDMAP_ROOT_PATTERN.match(stripped)
        if root_match is not None:
            root_label = _sanitize_mindmap_label(root_match.group(1))
            if root_label:
                output.append(f"  root(({root_label}))")
                has_root = True
            continue
        label = _sanitize_mindmap_label(stripped)
        if not label:
            continue
        if not has_root and indent_level <= 1:
            output.append(f"  root(({label}))")
            has_root = True
            continue
        output.append(f"{'  ' * max(2, indent_level)}{label}")
        child_count += 1
        if child_count >= 8:
            break
    if not has_root:
        return _build_simplified_mindmap(source)
    return "\n".join(output)


def sanitize_mermaid_source(source: str) -> str:
    """Normalize Mermaid body text without changing surrounding Markdown."""

    normalized = str(source or "").replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [line.rstrip() for line in normalized.splitlines() if line.strip()]
    if not lines:
        return ""
    first_line = lines[0].strip()
    joined = "\n".join(lines)
    if first_line.lower().startswith("mindmap"):
        return _sanitize_mindmap_source(joined)
    if FLOWCHART_HEADER_PATTERN.match(first_line) or any(token in joined for token in ("-->", "==>")):
        return _sanitize_flowchart_source(joined)
    return joined


def _is_indented_context_echo(line: str) -> bool:
    if not line.startswith(("    ", "\t")):
        return False
    stripped = line.strip()
    if not stripped:
        return False
    return (
        stripped.startswith("#")
        or stripped.startswith(("```", "**", "✅", "🔥", ">", "|", "---"))
        or len(stripped) > 18
    )


def _is_malformed_mermaid_fence(line: str) -> bool:
    match = MALFORMED_MERMAID_FENCE_PATTERN.match(line)
    if match is None:
        return False
    trailing = (match.group("trailing") or "").strip()
    if not trailing:
        return False
    return _looks_like_mermaid_line(trailing) or _looks_like_mermaid_garbage(trailing)


def _append_mermaid_block(output_lines: list[str], block_lines: list[str]) -> None:
    body_lines = list(block_lines)
    while body_lines and not body_lines[0].strip():
        body_lines.pop(0)
    while body_lines and not body_lines[-1].strip():
        body_lines.pop()
    if not body_lines:
        return
    body = sanitize_mermaid_source("\n".join(body_lines))
    if not body.strip():
        return
    output_lines.append("```mermaid")
    output_lines.extend(body.splitlines())
    output_lines.append("```")


def normalize_mermaid_blocks(markdown: str) -> str:
    text = _split_stuck_math_fences(str(markdown or ""))
    if "```" not in text:
        return text

    original_has_trailing_newline = text.endswith("\n")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    normalized_lines: list[str] = []
    mermaid_lines: list[str] = []
    mermaid_prefix = ""
    in_mermaid = False
    after_mermaid_close = False
    skipping_artifact = False
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped_line = line.strip()

        if skipping_artifact:
            if not stripped_line:
                index += 1
                continue
            if _is_indented_context_echo(line) or _is_malformed_mermaid_fence(line):
                index += 1
                continue
            if stripped_line.startswith("```"):
                skipping_artifact = False
                after_mermaid_close = False
                index += 1
                continue
            if MARKDOWN_BOUNDARY_PATTERN.match(stripped_line):
                skipping_artifact = False
                after_mermaid_close = False
                continue
            index += 1
            continue

        if not in_mermaid:
            if after_mermaid_close:
                if stripped_line == "```" or _is_indented_context_echo(line) or _is_malformed_mermaid_fence(line):
                    skipping_artifact = True
                    index += 1
                    continue
                after_mermaid_close = False
            start_match = MERMAID_START_PATTERN.match(line)
            lang = (start_match.group("lang") if start_match is not None else "") or ""
            if start_match and lang:
                in_mermaid = True
                mermaid_prefix = start_match.group("prefix") or ""
                normalized_lang = lang.strip()
                mermaid_lines = [] if normalized_lang.lower() == "mermaid" else [normalized_lang]
                index += 1
                continue
            malformed_match = MALFORMED_MERMAID_FENCE_PATTERN.match(line)
            malformed_trailing = (malformed_match.group("trailing") if malformed_match is not None else "") or ""
            if malformed_match is not None and _looks_like_mermaid_line(malformed_trailing):
                in_mermaid = True
                mermaid_prefix = ""
                mermaid_lines = [malformed_trailing.strip()]
                index += 1
                continue
            normalized_lines.append(line)
            index += 1
            continue

        if mermaid_lines and MARKDOWN_BOUNDARY_PATTERN.match(stripped_line):
            _append_mermaid_block(normalized_lines, mermaid_lines)
            mermaid_lines = []
            mermaid_prefix = ""
            in_mermaid = False
            after_mermaid_close = True
            continue

        cleaned_line = _strip_blockquote_prefix(line, prefix=mermaid_prefix).rstrip()
        fence_match = MERMAID_FENCE_PATTERN.match(cleaned_line.strip())
        if fence_match:
            _append_mermaid_block(normalized_lines, mermaid_lines)
            trailing = (fence_match.group("trailing") or "").strip()
            if trailing and not _looks_like_mermaid_garbage(trailing):
                normalized_lines.append(trailing)
            mermaid_lines = []
            mermaid_prefix = ""
            in_mermaid = False
            after_mermaid_close = True
            index += 1
            continue

        if mermaid_lines and not _looks_like_mermaid_line(cleaned_line):
            _append_mermaid_block(normalized_lines, mermaid_lines)
            mermaid_lines = []
            mermaid_prefix = ""
            in_mermaid = False
            after_mermaid_close = False
            continue

        mermaid_lines.append(cleaned_line)
        index += 1

    if in_mermaid:
        _append_mermaid_block(normalized_lines, mermaid_lines)

    normalized = "\n".join(normalized_lines)
    if original_has_trailing_newline and not normalized.endswith("\n"):
        normalized += "\n"
    return normalized


def _strip_quote_prefix(line: str) -> str:
    return BLOCKQUOTE_PREFIX_PATTERN.sub("", str(line or ""), count=1).rstrip()


def _split_markdown_table_cells(line: str) -> list[str]:
    stripped = _strip_quote_prefix(line).strip()
    if "|" not in stripped:
        return []
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]

    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in stripped:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            current.append(char)
            escaped = True
            continue
        if char == "|":
            cells.append("".join(current))
            current = []
            continue
        current.append(char)
    cells.append("".join(current))
    return cells


def _is_table_separator_line(line: str) -> bool:
    cells = _split_markdown_table_cells(line)
    if len(cells) < 2:
        return False
    return all(re.fullmatch(r"\s*:?-{3,}:?\s*", cell or "") is not None for cell in cells)


def _is_probable_table_row(line: str) -> bool:
    stripped = _strip_quote_prefix(line).strip()
    if not stripped:
        return False
    if not (stripped.startswith("|") or stripped.endswith("|")):
        return False
    cells = _split_markdown_table_cells(stripped)
    return len(cells) >= 2 and any(cell.strip() for cell in cells)


def _is_gfm_table_boundary(lines: list[str], index: int) -> bool:
    if index < 0 or index >= len(lines):
        return False
    line = lines[index]
    previous_line = lines[index - 1] if index > 0 else ""
    next_line = lines[index + 1] if index + 1 < len(lines) else ""
    if _is_table_separator_line(line):
        return _is_probable_table_row(previous_line) or _is_probable_table_row(next_line)
    if not _is_probable_table_row(line):
        return False
    return _is_table_separator_line(previous_line) or _is_table_separator_line(next_line)


def _is_structural_markdown_boundary(lines: list[str], index: int) -> bool:
    if index < 0 or index >= len(lines):
        return False
    stripped = _strip_quote_prefix(lines[index]).strip()
    if not stripped:
        return False
    if MATH_MARKDOWN_BOUNDARY_PATTERN.match(stripped):
        return True
    if re.match(r"^(?:---|\*\*\*|___)\s*$", stripped):
        return True
    return _is_gfm_table_boundary(lines, index)


def _next_nonempty_line_index(lines: list[str], start_index: int) -> int | None:
    for index in range(start_index, len(lines)):
        if lines[index].strip():
            return index
    return None


def _is_orphan_display_math_opener(lines: list[str], index: int) -> bool:
    next_index = _next_nonempty_line_index(lines, index + 1)
    if next_index is None:
        return True
    return _is_structural_markdown_boundary(lines, next_index)


def _quoted_markdown_body(line: str) -> str | None:
    match = re.match(r"^\s*>\s?(.*)$", str(line or ""))
    if match is None:
        return None
    return str(match.group(1) or "").rstrip()


def _math_fence_prefix(line: str) -> str:
    match = re.match(r"^(\s*>\s*)?\$\$\s*$", str(line or ""))
    if match is None:
        return ""
    return str(match.group(1) or "")


def _normalize_math_fence_line(line: str) -> str:
    return f"{_math_fence_prefix(line)}$$"


def _collect_loose_display_math_block(lines: list[str], start_index: int) -> tuple[list[str], int]:
    body_lines = ["$$"]
    index = start_index + 1
    while index < len(lines):
        current = lines[index].rstrip()
        quoted = _quoted_markdown_body(current)
        body_line = quoted if quoted is not None else current
        body_lines.append(body_line)
        index += 1
        if MATH_FENCE_PATTERN.match(body_line):
            break
    return body_lines, index


def _is_markdown_boundary_inside_math(line: str, *, lines: list[str] | None = None, index: int | None = None) -> bool:
    stripped = _strip_quote_prefix(line).strip()
    if not stripped:
        return False
    if MATH_MARKDOWN_BOUNDARY_PATTERN.match(stripped):
        return True
    if lines is None or index is None:
        return False
    return _is_gfm_table_boundary(lines, index)


def _repair_display_math_boundaries(markdown: str) -> str:
    """Close display math before obvious Markdown blocks leak into it."""

    lines = str(markdown or "").split("\n")
    fixed: list[str] = []
    in_math = False
    math_prefix = ""
    for index, raw_line in enumerate(lines):
        line = raw_line.rstrip()
        if MATH_FENCE_PATTERN.match(line):
            if not in_math and _is_orphan_display_math_opener(lines, index):
                continue
            delimiter_prefix = _math_fence_prefix(line)
            if in_math:
                fixed.append(f"{delimiter_prefix or math_prefix}$$")
                in_math = False
                math_prefix = ""
            else:
                math_prefix = delimiter_prefix
                fixed.append(f"{math_prefix}$$")
                in_math = True
            continue
        if in_math and _is_markdown_boundary_inside_math(line, lines=lines, index=index):
            closing_delimiter = f"{math_prefix}$$"
            if not fixed or fixed[-1] != closing_delimiter:
                fixed.append(closing_delimiter)
            in_math = False
            math_prefix = ""
        fixed.append(line)
    if in_math:
        fixed.append(f"{math_prefix}$$")
    return "\n".join(fixed)


def _repair_split_inline_code_math_literals(markdown: str) -> str:
    """Undo a known corruption from math cleanup touching inline code dollars."""

    lines = str(markdown or "").split("\n")
    fixed: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        if (
            index + 3 < len(lines)
            and line.rstrip().endswith("`")
            and MATH_FENCE_PATTERN.match(lines[index + 1])
            and lines[index + 2].lstrip().startswith("`")
            and lines[index + 2].rstrip().endswith("$")
            and MATH_FENCE_PATTERN.match(lines[index + 3])
        ):
            tail = lines[index + 2].lstrip().rstrip()
            fixed.append(f"{line}$$" + tail[:-1])
            index += 4
            continue

        if (
            MATH_FENCE_PATTERN.match(line)
            and index + 1 < len(lines)
            and lines[index + 1].lstrip().startswith("```")
        ):
            previous = next((item.strip() for item in reversed(fixed) if item.strip()), "")
            if "示例" in previous or "代码" in previous or "命令" in previous:
                index += 1
                continue

        fixed.append(line)
        index += 1
    return "\n".join(fixed)


def _normalize_callout_blocks(markdown: str) -> str:
    """Convert GitHub callout variants to a frontend-stable blockquote shape."""

    lines = str(markdown or "").split("\n")
    output: list[str] = []
    in_fence = False
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            output.append(line)
            index += 1
            continue
        if in_fence:
            output.append(line)
            index += 1
            continue

        match = CALLOUT_LINE_PATTERN.match(line)
        if match is None:
            output.append(line)
            index += 1
            continue

        kind = str(match.group("kind") or "").upper()
        rest = str(match.group("rest") or "").strip()
        if match.group("quote"):
            body_lines: list[str] = [rest] if rest else []
            index += 1
            while index < len(lines):
                body_line = lines[index].rstrip()
                inner = _quoted_markdown_body(body_line)
                if inner is None:
                    if MATH_FENCE_PATTERN.match(body_line):
                        math_lines, index = _collect_loose_display_math_block(lines, index)
                        body_lines.extend(math_lines)
                        continue
                    if not body_line.strip():
                        next_line = lines[index + 1].rstrip() if index + 1 < len(lines) else ""
                        if _quoted_markdown_body(next_line) is not None or MATH_FENCE_PATTERN.match(next_line):
                            body_lines.append("")
                            index += 1
                            continue
                    break
                if inner.strip() and CALLOUT_LINE_PATTERN.match(inner):
                    break
                body_lines.append(inner)
                index += 1
            _append_callout_block(output, kind=kind, body_lines=body_lines)
            continue

        body_lines = [rest] if rest else []
        if rest:
            _append_callout_block(output, kind=kind, body_lines=body_lines)
            index += 1
            continue

        index += 1
        while index < len(lines):
            body_line = lines[index].rstrip()
            body_stripped = body_line.strip()
            if not body_stripped:
                output.append(">")
                index += 1
                break
            if body_stripped.startswith(("```", "---", "***", "___")) or re.match(r"^#{1,6}\s+\S", body_stripped):
                break
            if body_lines and body_stripped.startswith("**") and any(
                marker in body_stripped for marker in ("自测", "例题", "题目", "解析", "正确答案")
            ):
                break
            if CALLOUT_LINE_PATTERN.match(body_line):
                break
            body_lines.append(body_line)
            index += 1
        _append_callout_block(output, kind=kind, body_lines=body_lines)
    return "\n".join(output)


def _unescaped_single_dollar_positions(line: str) -> list[int]:
    positions: list[int] = []
    index = 0
    while index < len(line):
        if line[index] == "`":
            tick_count = 1
            while index + tick_count < len(line) and line[index + tick_count] == "`":
                tick_count += 1
            fence = "`" * tick_count
            closing = line.find(fence, index + tick_count)
            if closing >= 0:
                index = closing + tick_count
                continue
            index += tick_count
            continue
        if line[index] != "$":
            index += 1
            continue
        if index + 1 < len(line) and line[index + 1] == "$":
            index += 2
            continue
        if index > 0 and line[index - 1] == "\\":
            index += 1
            continue
        positions.append(index)
        index += 1
    return positions


def _inline_math_body_has_math_signal(body: str) -> bool:
    trimmed = str(body or "").strip()
    return bool(
        re.search(
            r"\\(?:frac|dfrac|tfrac|lim|sum|prod|int|sqrt|left|right|to|infty|text|cdot|times|leq?|geq?|neq|approx|alpha|beta|gamma|delta|theta|lambda|mu|pi|sigma|omega)\b",
            trimmed,
        )
        or re.search(r"[_^{}∞∑∫√≤≥≈≠]|[A-Za-z0-9]\s*[=+\-*/<>]\s*[A-Za-z0-9\\]", trimmed)
    )


def _inline_math_body_is_unsafe(body: str) -> bool:
    trimmed = str(body or "").strip()
    if not trimmed:
        return True
    if "\n" in body:
        return True
    if len(trimmed) > 800 and not _inline_math_body_has_math_signal(trimmed):
        return True
    if INLINE_MATH_MARKDOWN_PATTERN.search(body):
        return True
    return any(marker in body for marker in ("```", "`", "**", "[!", "<div", "</", "<table"))


def _restore_escaped_inline_math_spans(markdown: str) -> str:
    r"""Recover likely math spans previously over-escaped as ``\$...\$``."""

    lines = str(markdown or "").split("\n")
    fixed: list[str] = []
    in_fence = False
    in_math = False

    def replace(match: re.Match[str]) -> str:
        body = str(match.group(1) or "").strip()
        if not body or not _inline_math_body_has_math_signal(body) or _inline_math_body_is_unsafe(body):
            return match.group(0)
        return f"${body}$"

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            fixed.append(line)
            continue
        if in_fence:
            fixed.append(line)
            continue
        if MATH_FENCE_PATTERN.match(line):
            in_math = not in_math
            fixed.append(_normalize_math_fence_line(line))
            continue
        if in_math:
            fixed.append(line)
            continue
        fixed.append(re.sub(r"\\\$([^\n]*?)\\\$", replace, line))
    return "\n".join(fixed)


def _find_unsafe_inline_math_spans(markdown: str) -> list[str]:
    issues: list[str] = []
    lines = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    in_fence = False
    in_math = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if MATH_FENCE_PATTERN.match(line):
            in_math = not in_math
            continue
        if in_math:
            continue
        positions = _unescaped_single_dollar_positions(line)
        if len(positions) % 2 != 0:
            issues.append("存在未成对的单美元内联公式分隔符。")
            continue
        for left, right in zip(positions[0::2], positions[1::2], strict=False):
            if _inline_math_body_is_unsafe(line[left + 1 : right]):
                issues.append("内联公式疑似吞入 Markdown 正文。")
                break
    return issues


def _escape_unpaired_inline_dollars(markdown: str) -> str:
    """Escape dangling single dollar delimiters outside code/display math."""

    lines = str(markdown or "").split("\n")
    fixed: list[str] = []
    in_fence = False
    in_math = False
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            fixed.append(line)
            continue
        if in_fence:
            fixed.append(line)
            continue
        if MATH_FENCE_PATTERN.match(line):
            in_math = not in_math
            fixed.append(_normalize_math_fence_line(line))
            continue
        if in_math:
            fixed.append(line)
            continue

        positions = _unescaped_single_dollar_positions(line)
        if len(positions) % 2 == 0:
            fixed.append(line)
            continue
        dangling = positions[-1]
        fixed.append(line[:dangling] + r"\$" + line[dangling + 1 :])
    return "\n".join(fixed)


def _escape_unsafe_inline_math_spans(markdown: str) -> str:
    """Escape paired inline math spans that clearly contain Markdown blocks."""

    lines = str(markdown or "").split("\n")
    fixed: list[str] = []
    in_fence = False
    in_math = False
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            fixed.append(line)
            continue
        if in_fence:
            fixed.append(line)
            continue
        if MATH_FENCE_PATTERN.match(line):
            in_math = not in_math
            fixed.append(_normalize_math_fence_line(line))
            continue
        if in_math:
            fixed.append(line)
            continue

        positions = _unescaped_single_dollar_positions(line)
        if len(positions) < 2 or len(positions) % 2 != 0:
            fixed.append(line)
            continue

        rebuilt: list[str] = []
        cursor = 0
        changed = False
        for left, right in zip(positions[0::2], positions[1::2], strict=False):
            body = line[left + 1 : right]
            rebuilt.append(line[cursor:left])
            if _inline_math_body_is_unsafe(body):
                rebuilt.append(r"\$")
                rebuilt.append(body)
                rebuilt.append(r"\$")
                changed = True
            else:
                rebuilt.append(line[left : right + 1])
            cursor = right + 1
        rebuilt.append(line[cursor:])
        fixed.append("".join(rebuilt) if changed else line)
    return "\n".join(fixed)


def _trim_inline_math_padding(markdown: str) -> str:
    """Remove padding just inside paired single-dollar math delimiters."""

    lines = str(markdown or "").split("\n")
    fixed: list[str] = []
    in_fence = False
    in_math = False
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            fixed.append(line)
            continue
        if in_fence:
            fixed.append(line)
            continue
        if MATH_FENCE_PATTERN.match(line):
            in_math = not in_math
            fixed.append(_normalize_math_fence_line(line))
            continue
        if in_math:
            fixed.append(line)
            continue

        positions = _unescaped_single_dollar_positions(line)
        if len(positions) < 2 or len(positions) % 2 != 0:
            fixed.append(line)
            continue

        rebuilt: list[str] = []
        cursor = 0
        changed = False
        for left, right in zip(positions[0::2], positions[1::2], strict=False):
            body = line[left + 1 : right]
            trimmed = body.strip()
            rebuilt.append(line[cursor:left])
            if trimmed and trimmed != body:
                rebuilt.append("$")
                rebuilt.append(trimmed)
                rebuilt.append("$")
                changed = True
            else:
                rebuilt.append(line[left : right + 1])
            cursor = right + 1
        rebuilt.append(line[cursor:])
        fixed.append("".join(rebuilt) if changed else line)
    return "\n".join(fixed)


def _normalize_vertical_bars_in_math_body(body: str) -> str:
    """Use KaTeX-safe absolute value delimiters inside inline math table cells."""

    def replace_absolute(match: re.Match[str]) -> str:
        inner = match.group(1).strip()
        if not inner:
            return match.group(0)
        return rf"\lvert {inner}\rvert"

    return re.sub(r"(?<!\\)\|([^|\n]+?)(?<!\\)\|", replace_absolute, body)


def _protect_inline_math_pipes_in_table_row(line: str) -> str:
    positions = _unescaped_single_dollar_positions(line)
    if len(positions) < 2 or len(positions) % 2 != 0:
        return line

    rebuilt: list[str] = []
    cursor = 0
    changed = False
    for left, right in zip(positions[0::2], positions[1::2], strict=False):
        body = line[left + 1 : right]
        normalized_body = _normalize_vertical_bars_in_math_body(body.strip())
        rebuilt.append(line[cursor:left])
        if normalized_body != body:
            rebuilt.append("$")
            rebuilt.append(normalized_body)
            rebuilt.append("$")
            changed = True
        else:
            rebuilt.append(line[left : right + 1])
        cursor = right + 1
    rebuilt.append(line[cursor:])
    return "".join(rebuilt) if changed else line


def _normalize_table_inline_math_pipes(markdown: str) -> str:
    """Protect raw pipes in inline math only while traversing GFM table rows."""

    lines = str(markdown or "").split("\n")
    fixed: list[str] = []
    in_fence = False
    in_math = False
    in_table = False
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            in_table = False
            fixed.append(line)
            index += 1
            continue
        if in_fence:
            fixed.append(line)
            index += 1
            continue
        if MATH_FENCE_PATTERN.match(line):
            in_math = not in_math
            in_table = False
            fixed.append(_normalize_math_fence_line(line))
            index += 1
            continue
        if in_math:
            fixed.append(line)
            index += 1
            continue

        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        starts_table = _is_probable_table_row(line) and _is_table_separator_line(next_line)
        if starts_table:
            in_table = True
            fixed.append(_protect_inline_math_pipes_in_table_row(line))
            index += 1
            continue
        if in_table and _is_probable_table_row(line):
            fixed.append(_protect_inline_math_pipes_in_table_row(line))
            index += 1
            continue

        in_table = False
        fixed.append(line)
        index += 1
    return "\n".join(fixed)


def _replace_outside_inline_code(line: str, pattern: re.Pattern[str], repl) -> str:
    """Apply a regex replacement outside inline-code spans on one line."""

    parts = re.split(r"(`+[^`]*`+)", str(line or ""))
    for index, part in enumerate(parts):
        if part.startswith("`") and part.endswith("`"):
            continue
        parts[index] = pattern.sub(repl, part)
    return "".join(parts)


def normalize_markdown_highlights(markdown: str) -> str:
    """Normalize safe learner-facing highlights without enabling raw HTML.

    ``<mark>...</mark>`` and ``==...==`` are both accepted as authoring
    syntax. This pass only trims tiny inline highlights and leaves code/math
    fences untouched; frontend rendering is responsible for displaying them.
    """

    lines = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    fixed: list[str] = []
    in_fence = False
    in_math = False
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            fixed.append(line)
            continue
        if MATH_FENCE_PATTERN.match(line):
            in_math = not in_math
            fixed.append(line)
            continue
        if in_fence or in_math:
            fixed.append(line)
            continue

        line = _replace_outside_inline_code(
            line,
            RAW_MARK_HIGHLIGHT_PATTERN,
            lambda match: f"<mark>{match.group('body').strip()}</mark>",
        )
        line = _replace_outside_inline_code(
            line,
            DOUBLE_EQUALS_HIGHLIGHT_PATTERN,
            lambda match: f"=={match.group('body').strip()}==",
        )
        fixed.append(line)
    return "\n".join(fixed)


def _normalize_list_embedded_headings(markdown: str) -> str:
    """Turn list items that accidentally contain Markdown headings back into text."""

    lines = str(markdown or "").split("\n")
    fixed: list[str] = []
    in_fence = False
    in_math = False
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            fixed.append(line)
            continue
        if in_fence:
            fixed.append(line)
            continue
        if MATH_FENCE_PATTERN.match(line):
            in_math = not in_math
            fixed.append(_normalize_math_fence_line(line))
            continue
        if in_math:
            fixed.append(line)
            continue

        fixed.append(re.sub(r"^(\s*(?:[-*+]|\d+[.)])\s+)#{1,6}\s+(.+)$", r"\1\2", line))
    return "\n".join(fixed)


def normalize_markdown_rendering(markdown: str) -> str:
    """修复学生文档里最容易破坏渲染的 Markdown 结构。

    LLM 常见问题是把 display math 或 fenced code 混进 blockquote，
    例如 ``> ```dos`` 或 ``$$`` 内部行仍带 ``>``。这里做确定性清洗，
    不改知识内容，只修可渲染结构。
    """

    text = _split_stuck_math_fences(str(markdown or "").replace("\r\n", "\n").replace("\r", "\n"))
    text = _repair_split_inline_code_math_literals(text)
    text = _repair_display_math_boundaries(text)
    text = _restore_escaped_inline_math_spans(text)
    text = _escape_unpaired_inline_dollars(text)
    text = _escape_unsafe_inline_math_spans(text)
    text = _trim_inline_math_padding(text)
    text = _normalize_table_inline_math_pipes(text)
    text = normalize_markdown_highlights(text)
    text = _normalize_list_embedded_headings(text)
    text = _normalize_callout_blocks(text)
    if not text:
        return ""

    lines = text.split("\n")
    fixed: list[str] = []
    in_math = False
    math_prefix = ""
    in_fence = False

    for line_index, raw_line in enumerate(lines):
        line = raw_line.rstrip()
        stripped = line.strip()

        if in_math:
            if MATH_FENCE_PATTERN.match(line):
                delimiter_prefix = _math_fence_prefix(line)
                fixed.append(f"{delimiter_prefix or math_prefix}$$")
                in_math = False
                math_prefix = ""
                continue
            cleaned_math_line = (
                line if math_prefix else _strip_quote_prefix(line) if BLOCKQUOTE_PREFIX_PATTERN.match(line) else line
            )
            if not cleaned_math_line.strip():
                continue
            fixed.append(cleaned_math_line)
            continue

        if in_fence:
            if stripped.startswith("```"):
                fixed.append("```")
                in_fence = False
                continue
            fixed.append(_strip_quote_prefix(line) if BLOCKQUOTE_PREFIX_PATTERN.match(line) else line)
            continue

        inline_fence = INLINE_FENCE_PATTERN.match(line)
        if inline_fence and not stripped.startswith("```"):
            prefix = inline_fence.group("prefix").rstrip()
            lang = inline_fence.group("lang").strip()
            if prefix:
                fixed.append(prefix)
            fixed.append(f"```{lang}".rstrip())
            in_fence = True
            continue

        if MATH_FENCE_PATTERN.match(line):
            if _is_orphan_display_math_opener(lines, line_index):
                continue
            delimiter_prefix = _math_fence_prefix(line)
            if not delimiter_prefix and fixed and fixed[-1].strip() == ">":
                fixed[-1] = ""
            fixed.append(f"{delimiter_prefix}$$")
            in_math = True
            math_prefix = delimiter_prefix
            continue

        if stripped.startswith("> ```"):
            fixed.append("```" + stripped.removeprefix("> ```").strip())
            in_fence = True
            continue

        if re.match(r"^```\s*[A-Za-z0-9_-]+\s*$", stripped):
            fixed.append(line)
            in_fence = True
            continue

        if stripped == "```":
            fixed.append("```text")
            in_fence = True
            continue

        fixed.append(line)

    normalized = "\n".join(fixed)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    return normalized + ("\n" if normalized else "")


def find_markdown_rendering_issues(markdown: str) -> list[str]:
    """返回会影响 Markdown 渲染的结构问题。"""

    text = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n")
    issues: list[str] = []
    if re.search(r"(?m)^>\s*.*```\s*[A-Za-z0-9_-]*\s*$", text):
        issues.append("代码块起始符被放在引用行内。")
    if _display_math_has_mixed_blockquote_prefix(text):
        issues.append("display math 内混入 blockquote 前缀。")
    if text.count("```") % 2 != 0:
        issues.append("Markdown fenced code block 数量不成对。")
    if _display_math_fence_line_count(text) % 2 != 0:
        issues.append("display math 分隔符数量不成对。")
    if STUCK_MATH_FENCE_PATTERN.search(text):
        issues.append("display math 分隔符和代码围栏粘连。")
    if _display_math_contains_markdown(text):
        issues.append("display math 疑似吞入 Markdown 正文。")
    if BARE_CALLOUT_PATTERN.search(text):
        issues.append("GitHub callout 未使用 blockquote 语法。")
    issues.extend(_find_unsafe_inline_math_spans(text))
    if _raw_mermaid_fence_count(text) != _parsed_mermaid_fence_count(text):
        issues.append("Mermaid 代码围栏未被 Markdown 解析为独立代码块。")
    return list(dict.fromkeys(issues))


def find_markdown_presentation_issues(markdown: str) -> list[str]:
    """Return rendering plus style-contract issues for student-facing docs."""

    text = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n")
    issues = list(find_markdown_rendering_issues(text))
    issues.extend(_find_heading_structure_issues(text))
    issues.extend(_find_emphasis_highlight_issues(text))
    issues.extend(_find_table_shape_issues(text))
    issues.extend(_find_code_fence_style_issues(text))
    issues.extend(_find_mermaid_knowledge_graph_issues(text))
    issues.extend(_find_learning_callout_field_issues(text))
    issues.extend(_find_readability_rhythm_issues(text))
    return list(dict.fromkeys(issue for issue in issues if issue))


def summarize_markdown_presentation(markdown: str) -> dict[str, object]:
    """Build a compact presentation-quality summary safe for manifests/traces."""

    text = str(markdown or "")
    issues = find_markdown_presentation_issues(text)
    callout_counts = _count_callouts_by_kind(text)
    table_count = _count_gfm_tables(text)
    mermaid_block_count = _parsed_mermaid_fence_count(text)
    math_block_count = _count_display_math_blocks(text)
    code_block_count = text.count("```") // 2
    return {
        "issue_count": len(issues),
        "issues": issues[:20],
        "heading_count": len(HEADER_PATTERN.findall(text)),
        "callout_count": sum(callout_counts.values()),
        "example_callout_count": callout_counts.get("example", 0),
        "practice_callout_count": callout_counts.get("practice", 0),
        "table_count": table_count,
        "code_block_count": code_block_count,
        "mermaid_block_count": mermaid_block_count,
        "math_block_count": math_block_count,
        "highlight_count": len(DOUBLE_EQUALS_HIGHLIGHT_PATTERN.findall(text)) + len(RAW_MARK_HIGHLIGHT_PATTERN.findall(text)),
        "long_paragraph_count": _count_long_plain_paragraphs(text),
        "max_consecutive_list_items": _max_consecutive_list_items(text),
        "reading_block_count": sum(callout_counts.values()) + table_count + mermaid_block_count + math_block_count + code_block_count,
    }


_HTML_SCRIPT_STYLE_RE = re.compile(r"<(?P<tag>script|style)\b[^>]*>.*?</(?P=tag)>", re.IGNORECASE | re.DOTALL)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_HTML_REMOTE_RESOURCE_ATTR_RE = re.compile(
    r"""\b(?:src|href|data|poster|action|formaction|srcset|xlink:href)\s*=\s*(?:"[^"]*(?:https?:)?//|'[^']*(?:https?:)?//|[^\s>]*(?:https?:)?//)""",
    re.IGNORECASE,
)


def _html_structure_text(html: str) -> str:
    """Return HTML text suitable for structural tag counting."""

    text = _HTML_COMMENT_RE.sub("", str(html or ""))
    return _HTML_SCRIPT_STYLE_RE.sub(lambda match: f"<{match.group('tag')}></{match.group('tag')}>", text)


def _html_resource_attribute_text(html: str) -> str:
    """Return HTML text for URL-attribute scanning without script/style bodies."""

    text = _HTML_COMMENT_RE.sub("", str(html or ""))

    def _keep_shell(match: re.Match[str]) -> str:
        opening = match.group(0).split(">", 1)[0] + ">"
        return f"{opening}</{match.group('tag')}>"

    return _HTML_SCRIPT_STYLE_RE.sub(_keep_shell, text)


def _html_tag_count(html: str, tag: str) -> int:
    return len(re.findall(rf"<{re.escape(tag)}\b", html, re.IGNORECASE))


def validate_single_file_html(html: str) -> list[str]:
    """Check an interactive sidecar HTML document without executing it."""

    text = str(html or "").strip()
    structure_lower = _html_structure_text(text).lower()
    resource_text = _html_resource_attribute_text(text)
    issues: list[str] = []
    if not structure_lower.startswith("<!doctype html>"):
        issues.append("HTML sidecar 缺少 <!doctype html>。")
    if len(re.findall(r"<!doctype\s+html", structure_lower, re.IGNORECASE)) != 1:
        issues.append("HTML sidecar 必须只包含一个 <!doctype html>。")
    for tag in ("html", "head", "body"):
        count = _html_tag_count(structure_lower, tag)
        tag_label = f"<{tag}"
        if count == 0:
            issues.append(f"HTML sidecar 缺少 {tag_label}> 结构。")
        elif count > 1:
            issues.append(f"HTML sidecar 包含重复的 {tag_label}> 结构。")
    for tag in ("</html>", "</head>", "</body>"):
        if tag not in structure_lower:
            issues.append(f"HTML sidecar 缺少 {tag}。")
    if not re.search(r"<meta[^>]+name\s*=\s*['\"]viewport['\"]", text, re.IGNORECASE):
        issues.append("HTML sidecar 缺少移动端 viewport meta。")
    if re.search(r"<script[^>]+src\s*=", text, re.IGNORECASE):
        issues.append("HTML sidecar 包含外部脚本引用。")
    if re.search(r"<link[^>]+href\s*=\s*['\"]https?://", text, re.IGNORECASE):
        issues.append("HTML sidecar 包含外部样式、字体或资源引用。")
    if re.search(r"<img[^>]+src\s*=\s*['\"]https?://", text, re.IGNORECASE):
        issues.append("HTML sidecar 包含远程图片资源。")
    if _HTML_REMOTE_RESOURCE_ATTR_RE.search(resource_text):
        issues.append("HTML sidecar 包含远程资源 URL。")
    if re.search(r"@import\b", text, re.IGNORECASE):
        issues.append("HTML sidecar 包含外部样式 import。")
    if re.search(r"url\s*\(\s*['\"]?(?:https?:)?//", text, re.IGNORECASE):
        issues.append("HTML sidecar 包含远程样式资源。")
    if re.search(r"\b(fetch|XMLHttpRequest|WebSocket)\s*\(", text) or re.search(r"\b(localStorage|sessionStorage)\b", text):
        issues.append("HTML sidecar 包含不允许的联网或持久化 API。")
    return list(dict.fromkeys(issues))


def _find_heading_structure_issues(markdown: str) -> list[str]:
    issues: list[str] = []
    in_fence = False
    previous_level = 0
    first_heading_seen = False
    for raw_line in markdown.split("\n"):
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", raw_line)
        if match is None:
            continue
        level = len(match.group(1))
        title = KNOWLEDGE_ANCHOR_PATTERN.sub("", match.group(2)).strip()
        if not first_heading_seen:
            first_heading_seen = True
            if level != 1:
                issues.append("Markdown 首个标题不是一级标题。")
        if previous_level and level > previous_level + 1:
            issues.append("Markdown 标题层级存在跳级。")
        if len(title) > 80:
            issues.append("Markdown 标题过长，影响目录和阅读。")
        previous_level = level
    return issues


def _plain_text_outside_fences(markdown: str) -> str:
    lines: list[str] = []
    in_fence = False
    in_math = False
    for raw_line in str(markdown or "").split("\n"):
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if MATH_FENCE_PATTERN.match(raw_line):
            in_math = not in_math
            continue
        if in_fence or in_math:
            continue
        lines.append(raw_line)
    return "\n".join(lines)


def _visible_markdown_text(text: str) -> str:
    cleaned = re.sub(r"`([^`]+)`", r"\1", str(text or ""))
    cleaned = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"[*_~`>#|]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _iter_plain_paragraphs(markdown: str) -> list[str]:
    paragraphs: list[str] = []
    current: list[str] = []
    in_fence = False
    in_math = False

    def flush() -> None:
        nonlocal current
        if current:
            paragraphs.append(" ".join(item.strip() for item in current if item.strip()))
            current = []

    for raw_line in str(markdown or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            flush()
            in_fence = not in_fence
            continue
        if MATH_FENCE_PATTERN.match(raw_line):
            flush()
            in_math = not in_math
            continue
        if in_fence or in_math:
            continue
        if not stripped:
            flush()
            continue
        if (
            stripped.startswith(("#", ">", "|"))
            or re.match(r"^(?:[-*+]|\d+[.)])\s+\S", stripped)
            or _is_table_separator_line(stripped)
        ):
            flush()
            continue
        current.append(stripped)

    flush()
    return paragraphs


def _count_long_plain_paragraphs(markdown: str, *, soft_limit: int = 320) -> int:
    return sum(1 for paragraph in _iter_plain_paragraphs(markdown) if len(_visible_markdown_text(paragraph)) > soft_limit)


def _max_consecutive_list_items(markdown: str) -> int:
    max_run = 0
    current = 0
    in_fence = False
    in_math = False
    for raw_line in str(markdown or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            current = 0
            continue
        if MATH_FENCE_PATTERN.match(raw_line):
            in_math = not in_math
            current = 0
            continue
        if in_fence or in_math:
            continue
        if re.match(r"^(?:[-*+]|\d+[.)])\s+\S", stripped):
            current += 1
            max_run = max(max_run, current)
        elif stripped:
            current = 0
    return max_run


def _count_display_math_blocks(markdown: str) -> int:
    return _display_math_fence_line_count(str(markdown or "")) // 2


def _count_callouts_by_kind(markdown: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for match in re.finditer(rf"(?m)^>\s*\[!(?P<kind>{CALLOUT_KINDS_PATTERN})\]", str(markdown or ""), re.IGNORECASE):
        kind = match.group("kind").lower()
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def _find_emphasis_highlight_issues(markdown: str) -> list[str]:
    text = _plain_text_outside_fences(markdown)
    issues: list[str] = []
    if len(re.findall(r"(?<!\\)\*\*", text)) % 2 != 0:
        issues.append("Markdown 加粗标记 ** 未成对闭合。")
    if len(re.findall(r"(?<!\\)==", text)) % 2 != 0:
        issues.append("Markdown 高亮标记 == 未成对闭合。")
    if len(RAW_MARK_OPEN_PATTERN.findall(text)) != len(RAW_MARK_CLOSE_PATTERN.findall(text)):
        issues.append("Markdown <mark> 高亮标签未成对闭合。")
    if RAW_HTML_TAG_PATTERN.search(text):
        issues.append("Markdown 正文包含不受控 HTML 标签。")
    highlight_count = len(DOUBLE_EQUALS_HIGHLIGHT_PATTERN.findall(text)) + len(RAW_MARK_HIGHLIGHT_PATTERN.findall(text))
    paragraph_count = max(1, len([line for line in text.split("\n") if line.strip() and not line.lstrip().startswith(("#", ">", "|"))]))
    if highlight_count > max(12, paragraph_count):
        issues.append("Markdown 高亮过多，重点可能失效。")
    return issues


def _find_table_shape_issues(markdown: str) -> list[str]:
    issues: list[str] = []
    lines = str(markdown or "").split("\n")
    in_fence = False
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            index += 1
            continue
        if in_fence or not (_is_probable_table_row(line) and index + 1 < len(lines) and _is_table_separator_line(lines[index + 1])):
            index += 1
            continue
        expected = len(_split_markdown_table_cells(line))
        if expected > 5:
            issues.append("Markdown 表格列数过多，建议控制在 3 到 5 列。")
        cursor = index + 2
        while cursor < len(lines) and _is_probable_table_row(lines[cursor]):
            if len(_split_markdown_table_cells(lines[cursor])) != expected:
                issues.append("Markdown 表格行列数不一致。")
                break
            cursor += 1
        index = cursor
    return issues


def _find_code_fence_style_issues(markdown: str) -> list[str]:
    issues: list[str] = []
    in_fence = False
    for raw_line in str(markdown or "").split("\n"):
        stripped = raw_line.strip()
        if not stripped.startswith("```"):
            continue
        if not in_fence:
            language = stripped[3:].strip()
            if not language:
                issues.append("Markdown 代码块缺少语言标记。")
            in_fence = True
        else:
            in_fence = False
    return issues


def _iter_mermaid_blocks(markdown: str) -> list[str]:
    blocks: list[str] = []
    lines = str(markdown or "").split("\n")
    in_mermaid = False
    body: list[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if not in_mermaid and re.match(r"^```\s*mermaid\s*$", stripped, re.IGNORECASE):
            in_mermaid = True
            body = []
            continue
        if in_mermaid and stripped.startswith("```"):
            blocks.append("\n".join(body))
            in_mermaid = False
            continue
        if in_mermaid:
            body.append(raw_line)
    return blocks


def _find_mermaid_knowledge_graph_issues(markdown: str) -> list[str]:
    issues: list[str] = []
    for block in _iter_mermaid_blocks(markdown):
        first_line = next((line.strip() for line in block.split("\n") if line.strip()), "")
        if first_line and not MERMAID_INFO_PATTERN.match(first_line):
            issues.append("Mermaid 代码块缺少合法图类型开头。")
        if "知识图谱" not in block and "K01" not in block:
            continue
        for match in FLOWCHART_RELATION_LABEL_PATTERN.finditer(block):
            label = (match.group("label") or match.group("label2") or "").strip()
            if label and label not in KNOWLEDGE_GRAPH_RELATION_LABELS:
                issues.append("Mermaid 知识图谱关系标签不在允许的 8 类关系中。")
                break
    return issues


def _iter_callout_blocks(markdown: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    lines = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    in_fence = False
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            index += 1
            continue
        if in_fence:
            index += 1
            continue

        marker = re.match(rf"^\s*>\s*\[!(?P<kind>{CALLOUT_KINDS_PATTERN})\](?P<rest>.*)$", line, re.IGNORECASE)
        if marker is None:
            index += 1
            continue

        kind = marker.group("kind").upper()
        body_lines = [str(marker.group("rest") or "").strip()]
        index += 1
        while index < len(lines):
            body_match = re.match(r"^\s*>\s?(?P<body>.*)$", lines[index])
            if body_match is None:
                break
            body_lines.append(str(body_match.group("body") or "").strip())
            index += 1
        blocks.append((kind, "\n".join(line for line in body_lines if line.strip())))
    return blocks


def _find_learning_callout_field_issues(markdown: str) -> list[str]:
    issues: list[str] = []
    for kind, body in _iter_callout_blocks(markdown):
        if kind not in {"EXAMPLE", "PRACTICE"}:
            continue
        visible = _visible_markdown_text(body)
        if len(visible) < 20:
            continue
        has_task = bool(LEARNING_CALLOUT_TASK_FIELD_PATTERN.search(body))
        has_reason = bool(LEARNING_CALLOUT_REASON_FIELD_PATTERN.search(body))
        has_answer = bool(LEARNING_CALLOUT_ANSWER_FIELD_PATTERN.search(body))
        if not (has_task and has_reason and has_answer):
            issues.append("例题/练习 callout 缺少题目、解析或答案字段。")
            break
    return issues


def _find_readability_rhythm_issues(markdown: str) -> list[str]:
    issues: list[str] = []
    text = str(markdown or "")
    plain_visible_length = len(_visible_markdown_text(_plain_text_outside_fences(text)))
    long_paragraph_count = _count_long_plain_paragraphs(text)
    if long_paragraph_count >= 2:
        issues.append("Markdown 存在多个过长正文段落，建议拆成步骤、表格或 callout。")
    elif any(len(_visible_markdown_text(paragraph)) > 520 for paragraph in _iter_plain_paragraphs(text)):
        issues.append("Markdown 存在超长正文段落，影响学生扫读。")

    if _max_consecutive_list_items(text) >= 9:
        issues.append("Markdown 连续列表过长，建议拆分为小节、表格或练习块。")

    callout_count = sum(_count_callouts_by_kind(text).values())
    reading_block_count = (
        callout_count
        + _count_gfm_tables(text)
        + _parsed_mermaid_fence_count(text)
        + _count_display_math_blocks(text)
        + text.count("```") // 2
    )
    if plain_visible_length > 1200 and reading_block_count == 0:
        issues.append("Markdown 长章节缺少 callout、表格、公式或图示等阅读分组。")

    return issues


def _count_gfm_tables(markdown: str) -> int:
    lines = str(markdown or "").split("\n")
    count = 0
    in_fence = False
    for index, line in enumerate(lines[:-1]):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and _is_probable_table_row(line) and _is_table_separator_line(lines[index + 1]):
            count += 1
    return count


def _display_math_contains_markdown(markdown: str) -> bool:
    in_math = False
    lines = str(markdown or "").split("\n")
    for index, line in enumerate(lines):
        if MATH_FENCE_PATTERN.match(line):
            in_math = not in_math
            continue
        if in_math and _is_markdown_boundary_inside_math(line, lines=lines, index=index):
            return True
    return False


def _display_math_has_mixed_blockquote_prefix(markdown: str) -> bool:
    in_math = False
    math_prefix = ""
    for line in str(markdown or "").split("\n"):
        if MATH_FENCE_PATTERN.match(line):
            if in_math:
                in_math = False
                math_prefix = ""
            else:
                in_math = True
                math_prefix = _math_fence_prefix(line)
            continue
        if not in_math or not line.strip():
            continue
        if math_prefix:
            if not line.startswith(math_prefix):
                return True
            continue
        if BLOCKQUOTE_PREFIX_PATTERN.match(line):
            return True
    return False


def _display_math_fence_line_count(markdown: str) -> int:
    return sum(1 for line in str(markdown or "").split("\n") if MATH_FENCE_PATTERN.match(line))


def _split_stuck_math_fences(markdown: str) -> str:
    return STUCK_MATH_FENCE_PATTERN.sub(
        lambda match: f"{match.group('prefix')}$$\n{match.group('prefix')}{match.group('fence').rstrip()}",
        str(markdown or ""),
    )


def _raw_mermaid_fence_count(markdown: str) -> int:
    return len(RAW_MERMAID_FENCE_PATTERN.findall(str(markdown or "")))


def _parsed_mermaid_fence_count(markdown: str) -> int:
    count = 0
    for token in _MARKDOWN_PARSER.parse(str(markdown or "")):
        if token.type != "fence":
            continue
        info = str(token.info or "").strip()
        if MERMAID_INFO_PATTERN.match(info):
            count += 1
    return count



def build_draft_excerpt(markdown: str, *, max_chars: int = 420) -> str:
    cleaned = re.sub(r"\s+", " ", markdown).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."


def extract_markdown_headers(
    markdown: str,
    *,
    min_level: int = 1,
    max_level: int = 6,
) -> list[dict[str, str | int]]:
    headers: list[dict[str, str | int]] = []
    for hashes, title in HEADER_PATTERN.findall(markdown):
        level = len(hashes)
        if level < min_level or level > max_level:
            continue
        cleaned_title = KNOWLEDGE_ANCHOR_PATTERN.sub("", title).strip()
        lowered = cleaned_title.lower()
        if lowered in {"table of contents", "knowledge document overview", "目录", "知识文档总览"}:
            continue
        headers.append(
            {
                "level": level,
                "title": cleaned_title,
                "anchor": slugify_markdown_anchor(cleaned_title),
            }
        )
    return headers


def slugify_markdown_anchor(text: str) -> str:
    cleaned = KNOWLEDGE_ANCHOR_PATTERN.sub("", text).strip().lower()
    cleaned = re.sub(r"[^\w\s-]", "", cleaned)
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned.strip("-")


def build_table_of_contents(
    markdown: str,
    *,
    heading: str = "## 目录",
    min_level: int = 1,
    max_level: int = 3,
    max_entries: int = 24,
) -> str:
    headers = extract_markdown_headers(markdown, min_level=min_level, max_level=max_level)
    if not headers:
        return ""
    lines = [heading, ""]
    base_level = min(int(item["level"]) for item in headers)
    for item in headers[:max_entries]:
        level = int(item["level"])
        indent = "  " * max(0, level - base_level)
        title = str(item["title"])
        anchor = str(item["anchor"])
        lines.append(f"{indent}- [{title}](#{anchor})")
    return "\n".join(lines).strip() + "\n"


def prepend_table_of_contents(
    markdown: str,
    *,
    heading: str = "## 目录",
    min_level: int = 1,
    max_level: int = 3,
    max_entries: int = 24,
) -> str:
    if heading.lower() in markdown.lower():
        return markdown
    toc = build_table_of_contents(
        markdown,
        heading=heading,
        min_level=min_level,
        max_level=max_level,
        max_entries=max_entries,
    ).strip()
    if not toc:
        return markdown
    return toc + "\n\n" + markdown.lstrip()



def normalize_source_details(source_details: list[Mapping[str, object]] | None) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in source_details or []:
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or "").strip()
        source = str(item.get("source") or "").strip()
        score = item.get("score")
        key = url or f"{title}::{source}"
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "url": url,
                "title": title or url or "Untitled source",
                "source": source,
                "score": f"{float(score):.3f}" if isinstance(score, (int, float)) else "",
            }
        )
    return normalized



def _format_source_bullet(item: Mapping[str, str]) -> str:
    url = str(item.get("url") or "").strip()
    title = str(item.get("title") or url or "Untitled source").strip()
    source = str(item.get("source") or "").strip()
    if url.startswith("local://") or not url:
        label = source or "local_material"
        return f"- {title} ({label})"
    domain = urlparse(url).netloc.strip()
    suffix = f" - {source}" if source else (f" - {domain}" if domain else "")
    return f"- [{title}]({url}){suffix}"



def build_reference_section(
    source_details: list[Mapping[str, object]] | None,
    *,
    heading: str = "## 参考资料与延伸阅读",
) -> str:
    normalized = normalize_source_details(source_details)
    if not normalized:
        return ""
    bullets = [_format_source_bullet(item) for item in normalized]
    return heading + "\n\n" + "\n".join(bullets).strip() + "\n"



def append_reference_section(
    markdown: str,
    source_details: list[Mapping[str, object]] | None,
    *,
    heading: str = "## 参考资料与延伸阅读",
) -> str:
    reference_block = build_reference_section(source_details, heading=heading).strip()
    if not reference_block:
        return markdown
    if heading.lower() in markdown.lower():
        return markdown
    return markdown.rstrip() + "\n\n" + reference_block + "\n"


__all__ = [
    "append_reference_section",
    "build_table_of_contents",
    "build_draft_excerpt",
    "build_reference_section",
    "count_words",
    "extract_image_placeholders",
    "extract_markdown_headers",
    "extract_mermaid_placeholders",
    "find_markdown_presentation_issues",
    "find_markdown_rendering_issues",
    "normalize_markdown_highlights",
    "normalize_markdown_rendering",
    "normalize_source_details",
    "normalize_mermaid_blocks",
    "sanitize_mermaid_source",
    "summarize_markdown_presentation",
    "validate_single_file_html",
    "prepend_table_of_contents",
    "slugify_markdown_anchor",
]
