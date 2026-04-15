"""Canonical digest pedagogy facade.

New digest code should prefer this package over ``app.teaching.documents``.
The underlying implementation still delegates to the legacy teaching package
until the full migration lands.
"""

from app.workflows.digest._shared.pedagogy.content_blocks import *  # noqa: F401,F403
from app.workflows.digest._shared.pedagogy.report_generation import *  # noqa: F401,F403
