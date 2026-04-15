"""Canonical digest teaching-runtime facade.

During the transition away from ``app.teaching``, the implementation still
delegates to the legacy module. New digest code should import from here.
"""

from app.teaching.runtime_config import *  # noqa: F401,F403
