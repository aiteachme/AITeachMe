"""Paper-export helpers for printable exam artifacts."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel
from sqlmodel import Session

from app.models import ExamPaper, ExamPaperItem, QuestionType
from app.repositories import exams_repo
from app.utils.path_helpers import build_exam_dir
from app.utils.time import utcnow


_INVALID_FILENAME_RE = re.compile(r"[^\w\-]+")
_SECTION_LABELS = {
    QuestionType.SINGLE_CHOICE.value: "一、单项选择题",
    QuestionType.FILL_BLANK.value: "二、填空题",
    QuestionType.SHORT_ANSWER.value: "三、简答题",
}
_OPTION_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


class PaperExportResult(BaseModel):
    markdown_path: str
    tex_path: str
    pdf_path: str | None = None
    compiler: str | None = None
    compile_log_path: str | None = None


class _PaperSection(BaseModel):
    label: str
    items: list[ExamPaperItem]


def _parse_selection_context(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if isinstance(decoded, dict):
        return decoded
    return {}


def _sanitize_filename_component(value: str) -> str:
    normalized = re.sub(r"\s+", "_", value.strip().lower())
    cleaned = _INVALID_FILENAME_RE.sub("_", normalized).strip("_")
    compacted = re.sub(r"_+", "_", cleaned)
    return compacted[:48] or "paper"


def _paper_title(paper: ExamPaper, *, selection_context: dict[str, object]) -> str:
    raw = selection_context.get("paper_title")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return f"{paper.subject} 试卷 #{paper.id}"


def _parse_options(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(decoded, list):
        return []
    return [str(item).strip() for item in decoded if str(item).strip()]


def _resolve_sections(
    items: list[ExamPaperItem],
    *,
    selection_context: dict[str, object],
) -> list[_PaperSection]:
    raw_plan = selection_context.get("section_plan")
    if isinstance(raw_plan, list) and raw_plan:
        sections: list[_PaperSection] = []
        for entry in raw_plan:
            if not isinstance(entry, dict):
                continue
            label_value = entry.get("label")
            start_order_value = entry.get("start_order")
            count_value = entry.get("count")
            if not isinstance(label_value, str):
                continue
            try:
                start_order = int(start_order_value)
                count = int(count_value)
            except (TypeError, ValueError):
                continue
            if start_order <= 0 or count <= 0:
                continue
            section_items = [
                item
                for item in items
                if start_order <= item.item_order < (start_order + count)
            ]
            if section_items:
                sections.append(_PaperSection(label=label_value, items=section_items))
        if sections:
            covered_ids = {
                item.id
                for section in sections
                for item in section.items
                if item.id is not None
            }
            leftovers = [
                item
                for item in items
                if item.id is None or item.id not in covered_ids
            ]
            if leftovers:
                sections.append(_PaperSection(label="附加题目", items=leftovers))
            return sections

    grouped: dict[str, list[ExamPaperItem]] = {}
    for item in items:
        key = item.question_type or "other"
        grouped.setdefault(key, []).append(item)
    ordered_sections = sorted(grouped.items(), key=lambda entry: entry[1][0].item_order if entry[1] else 0)
    return [
        _PaperSection(
            label=_SECTION_LABELS.get(question_type, question_type),
            items=section_items,
        )
        for question_type, section_items in ordered_sections
        if section_items
    ]


def _render_markdown(
    *,
    paper: ExamPaper,
    title: str,
    sections: list[_PaperSection],
    generated_at: str,
) -> str:
    lines: list[str] = [
        f"# {title}",
        "",
        f"- 学科：{paper.subject}",
        f"- 试卷ID：{paper.id}",
        f"- 生成时间：{generated_at}",
        "",
        "---",
        "",
    ]

    for section in sections:
        lines.append(f"## {section.label}")
        lines.append("")
        for item in section.items:
            lines.append(f"### {item.item_order}. {item.stem_snapshot.strip()}")
            lines.append(f"- 题型：{item.question_type}  | 难度：{item.difficulty}")
            options = _parse_options(item.options_snapshot_json)
            if options:
                for index, option in enumerate(options):
                    label = _OPTION_LABELS[index] if index < len(_OPTION_LABELS) else str(index + 1)
                    lines.append(f"  - {label}. {option}")
            else:
                lines.extend(["", "答题区：", "", "", ""])
            lines.append("")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _escape_tex(text: str) -> str:
    escaped = text
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for source, target in replacements.items():
        escaped = escaped.replace(source, target)
    return escaped


def _render_tex(
    *,
    paper: ExamPaper,
    title: str,
    sections: list[_PaperSection],
    generated_at: str,
) -> str:
    lines: list[str] = [
        r"\documentclass[UTF8]{ctexart}",
        r"\usepackage[a4paper,margin=2.0cm]{geometry}",
        r"\usepackage{enumitem}",
        r"\setlist[itemize]{leftmargin=2em}",
        r"\begin{document}",
        rf"\section*{{{_escape_tex(title)}}}",
        rf"\textbf{{学科}}：{_escape_tex(paper.subject)}\\",
        rf"\textbf{{试卷ID}}：{paper.id}\\",
        rf"\textbf{{生成时间}}：{_escape_tex(generated_at)}\\",
        r"\vspace{0.6em}",
        r"\hrule",
        r"\vspace{1em}",
    ]

    for section in sections:
        lines.append(rf"\subsection*{{{_escape_tex(section.label)}}}")
        for item in section.items:
            lines.append(rf"\paragraph{{{item.item_order}. {_escape_tex(item.stem_snapshot.strip())}}}")
            lines.append(rf"\textit{{题型}}：{_escape_tex(item.question_type)}，\textit{{难度}}：{_escape_tex(item.difficulty)}\\")
            options = _parse_options(item.options_snapshot_json)
            if options:
                lines.append(r"\begin{itemize}")
                for index, option in enumerate(options):
                    label = _OPTION_LABELS[index] if index < len(_OPTION_LABELS) else str(index + 1)
                    lines.append(rf"\item[{label}.] {_escape_tex(option)}")
                lines.append(r"\end{itemize}")
            else:
                lines.append(r"\vspace{3.2em}")
                lines.append(r"\hrule")
                lines.append(r"\vspace{2.4em}")
        lines.append(r"\vspace{0.8em}")

    lines.append(r"\end{document}")
    return "\n".join(lines) + "\n"


def _run_tex_compile(command: list[str], *, working_dir: Path, timeout_seconds: int) -> tuple[bool, str]:
    completed = subprocess.run(
        command,
        cwd=working_dir,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    merged_log = f"{completed.stdout}\n{completed.stderr}".strip()
    return completed.returncode == 0, merged_log


def _compile_tex_to_pdf(tex_path: Path) -> tuple[str | None, str | None, str | None]:
    compiler_candidates = [
        ("tectonic", ["tectonic", "--outdir", str(tex_path.parent), str(tex_path)]),
        ("xelatex", ["xelatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name]),
        ("pdflatex", ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name]),
    ]

    for compiler, command in compiler_candidates:
        if shutil.which(compiler) is None:
            continue
        ok, log_text = _run_tex_compile(command, working_dir=tex_path.parent, timeout_seconds=180)
        log_path = tex_path.with_suffix(f".{compiler}.log")
        log_path.write_text(log_text or f"{compiler} finished with empty logs.", encoding="utf-8")
        pdf_path = tex_path.with_suffix(".pdf")
        if ok and pdf_path.exists():
            return str(pdf_path), compiler, str(log_path)

    return None, None, None


def compile_tex_to_pdf_artifact(tex_path: str | Path) -> tuple[str | None, str | None, str | None]:
    """Compile an existing tex artifact to PDF."""

    return _compile_tex_to_pdf(Path(tex_path))


def export_exam_paper_artifacts(
    session: Session,
    *,
    paper: ExamPaper,
    compile_pdf: bool = True,
) -> PaperExportResult:
    if paper.id is None:
        raise ValueError("Exam paper id is required for export.")

    items = exams_repo.list_items_by_paper(session, paper.id)
    if not items:
        raise ValueError(f"Exam paper `{paper.id}` has no items to export.")

    selection_context = _parse_selection_context(paper.selection_context_json)
    title = _paper_title(paper, selection_context=selection_context)
    sections = _resolve_sections(items, selection_context=selection_context)
    generated_at = utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    timestamp_token = utcnow().strftime("%Y%m%d_%H%M%S")
    title_token = _sanitize_filename_component(title)
    base_name = f"{timestamp_token}_paper_{paper.id}_{title_token}"

    export_dir = build_exam_dir(paper.subject)
    export_dir.mkdir(parents=True, exist_ok=True)

    markdown_path = export_dir / f"{base_name}.md"
    tex_path = export_dir / f"{base_name}.tex"
    markdown_path.write_text(
        _render_markdown(
            paper=paper,
            title=title,
            sections=sections,
            generated_at=generated_at,
        ),
        encoding="utf-8",
    )
    tex_path.write_text(
        _render_tex(
            paper=paper,
            title=title,
            sections=sections,
            generated_at=generated_at,
        ),
        encoding="utf-8",
    )

    pdf_path: str | None = None
    compiler: str | None = None
    compile_log_path: str | None = None
    if compile_pdf:
        pdf_path, compiler, compile_log_path = _compile_tex_to_pdf(tex_path)
    return PaperExportResult(
        markdown_path=str(markdown_path),
        tex_path=str(tex_path),
        pdf_path=pdf_path,
        compiler=compiler,
        compile_log_path=compile_log_path,
    )
