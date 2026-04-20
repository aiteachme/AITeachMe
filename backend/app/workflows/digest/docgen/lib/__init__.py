"""Tiny DocGen helper facade used by graph nodes."""

from app.workflows.digest.docgen.lib.chapter_context import DocGenChapterContextRuntime
from app.workflows.digest.docgen.lib.writer import DocGenWriterRuntime

__all__ = [
    "DocGenChapterContextRuntime",
    "DocGenWriterRuntime",
]
