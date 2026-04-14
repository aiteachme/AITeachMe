"""Ingest runtime package — modularized from monolithic runtime.py.

Submodules:
  _helpers  – DTOs, utility functions (asset builders, quality scoring)
  enhance   – Phase 2 deep OCR enhancement background task
  parse     – Main parse workflow entry point (Phase 1 + Phase 2 dispatch)
"""

from ._helpers import create_parse_file_initial_state
from .enhance import _run_deep_enhance_background
from .parse import run_parse_file_workflow

__all__ = [
    "create_parse_file_initial_state",
    "run_parse_file_workflow",
    "_run_deep_enhance_background",
]
