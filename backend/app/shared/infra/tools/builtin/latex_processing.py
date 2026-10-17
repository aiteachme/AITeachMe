"""LaTeX normalization helpers."""

from __future__ import annotations

import re

_BLOCK_PATTERN = re.compile(r"\\\[([\s\S]*?)\\\]")
_INLINE_PATTERN = re.compile(r"\\\(([\s\S]*?)\\\)")
_QUOTE_PREFIX_RE = re.compile(r"^(?:[ \t]{0,3}>[ \t]?)+")
_FENCE_LINE_RE = re.compile(r"^[ \t]*(?P<marker>`{3,}|~{3,})(?P<info>[^\r\n]*)$")
_SINGLE_LINE_BLOCK_RE = re.compile(r"\$\$[ \t]*([^\n$]+?)[ \t]*\$\$")
_EMPTY_INLINE_RE = re.compile(r"(?<!\$)\$\s+\$(?!\$)")
_EMPTY_BLOCK_RE = re.compile(r"\$\$\s*\$\$")


def normalize_math_delimiters(markdown: str) -> str:
    """Normalize common model-produced math delimiters outside code fences."""

    return _process_non_fenced(markdown, _normalize_math_segment)


def validate_latex(markdown: str) -> str:
    """Repair obvious math delimiter issues without trying to prove LaTeX validity.

    The goal is display stability: do not alter code fences or Mermaid blocks,
    but prevent common LLM mistakes such as empty math spans, odd ``$$`` blocks,
    or a line ending with an unclosed inline ``$``.
    """

    return _process_non_fenced(markdown, _validate_math_segment)


def _process_non_fenced(markdown: str, processor) -> str:
    """Process prose inside its quote container, keeping fenced code verbatim."""
    parts: list[str] = []
    prose: list[tuple[str, str]] = []
    quote_prefix = ""
    quote_depth = 0
    active_fence = ""
    active_math_closer = ""

    def flush_prose() -> None:
        text = "".join(body for _, body in prose)
        processed = _process_non_inline_code(text, processor)
        if processed == text:
            parts.append("".join(raw for raw, _ in prose))
        elif quote_prefix:
            parts.append("".join(quote_prefix + line for line in processed.splitlines(keepends=True)))
        else:
            parts.append(processed)
        prose.clear()

    for raw_line in str(markdown or "").splitlines(keepends=True):
        if active_math_closer:
            # A leading > inside display math can be a relation, not a new quote.
            container = re.match(rf"^(?:[ \t]{{0,3}}>[ \t]?){{{quote_depth}}}", raw_line)
            body = raw_line[container.end():] if container else raw_line
            prose.append((raw_line, body))
            if active_math_closer in body:
                active_math_closer = ""
            continue
        quoted = _QUOTE_PREFIX_RE.match(raw_line)
        prefix = quoted.group(0) if quoted else ""
        body = raw_line[len(prefix):]
        fence = _FENCE_LINE_RE.match(body.rstrip("\r\n"))
        if active_fence:
            parts.append(raw_line)
            if fence and not fence.group("info").strip() and (
                fence.group("marker")[0] == active_fence[0]
                and len(fence.group("marker")) >= len(active_fence)
            ):
                active_fence = ""
            continue
        if fence and (fence.group("marker")[0] != "`" or "`" not in fence.group("info")):
            flush_prose()
            parts.append(raw_line)
            active_fence = fence.group("marker")
            continue
        depth = prefix.count(">")
        if prose and depth != quote_depth:
            flush_prose()
        if not prose:
            quote_prefix, quote_depth = prefix, depth
        prose.append((raw_line, body))
        if body.strip() in ("$$", r"\["):
            active_math_closer = "$$" if body.strip() == "$$" else r"\]"
    flush_prose()
    return "".join(parts)


def _process_non_inline_code(segment: str, processor) -> str:
    """Apply math repairs outside inline code spans.

    DOS prompt strings and other command snippets often contain literal dollar
    signs, e.g. ``$P$G`` or ``$$``. Treating those inline-code dollars as LaTeX
    delimiters corrupts otherwise valid Markdown, so the math normalizer must
    leave code spans untouched.
    """

    text = str(segment or "")
    parts: list[str] = []
    cursor = 0
    length = len(text)
    while cursor < length:
        tick_index = text.find("`", cursor)
        if tick_index < 0:
            parts.append(processor(text[cursor:]))
            break
        parts.append(processor(text[cursor:tick_index]))
        tick_count = 1
        while tick_index + tick_count < length and text[tick_index + tick_count] == "`":
            tick_count += 1
        fence = "`" * tick_count
        closing = text.find(fence, tick_index + tick_count)
        if closing < 0:
            parts.append(text[tick_index:])
            break
        end = closing + tick_count
        parts.append(text[tick_index:end])
        cursor = end
    return "".join(parts)


def _normalize_math_segment(segment: str) -> str:
    normalized = _BLOCK_PATTERN.sub(lambda match: f"$$\n{match.group(1).strip()}\n$$", segment)
    normalized = _INLINE_PATTERN.sub(lambda match: f"${match.group(1).strip()}$", normalized)
    normalized = _SINGLE_LINE_BLOCK_RE.sub(lambda match: f"$$\n{match.group(1).strip()}\n$$", normalized)
    return normalized


def _validate_math_segment(segment: str) -> str:
    cleaned = _EMPTY_BLOCK_RE.sub("", segment)
    cleaned = _EMPTY_INLINE_RE.sub("", cleaned)
    cleaned = _separate_block_math(cleaned)
    cleaned = _close_unmatched_block_math(cleaned)
    keep_trailing_newline = cleaned.endswith("\n")
    lines = [_close_unmatched_inline_math(line) for line in cleaned.splitlines()]
    result = "\n".join(lines)
    if keep_trailing_newline and result and not result.endswith("\n"):
        result += "\n"
    return result


def _separate_block_math(segment: str) -> str:
    separated = re.sub(r"(?<=[^\n])\$\$", "\n$$", segment)
    separated = re.sub(r"\$\$(?=[^\n])", "$$\n", separated)
    return separated


def _close_unmatched_block_math(segment: str) -> str:
    if segment.count("$$") % 2 == 0:
        return segment
    return segment.rstrip() + "\n$$\n"


def _close_unmatched_inline_math(line: str) -> str:
    without_blocks = line.replace("$$", "")
    if without_blocks.count("$") % 2 == 0:
        return line
    if line.rstrip().endswith("$"):
        return line.replace("$", r"\$", 1)
    return line.rstrip() + "$"


__all__ = ["normalize_math_delimiters", "validate_latex"]
