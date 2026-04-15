"""Canonical cross-lane shared facade for digest workflows.

The historical implementation still lives under ``digest.shared`` during the
migration. New code should prefer ``digest._shared`` so the private/shared
boundary is explicit in the directory structure.
"""

from app.workflows.digest._shared.contracts import *  # noqa: F401,F403
from app.workflows.digest._shared.models import *  # noqa: F401,F403
from app.workflows.digest._shared.prepare import *  # noqa: F401,F403
from app.workflows.digest._shared.primitives import *  # noqa: F401,F403
