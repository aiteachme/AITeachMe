"""Repository package exports."""

from . import exams_repo as exams_repo  # noqa: F401
from . import profile_repo as profile_repo  # noqa: F401

# knowledge submodule re-exports for compatibility
from app.repositories.knowledge import curriculum_repo as curriculum_repo  # noqa: F401
from app.repositories.knowledge import kg_repo as kg_repo  # noqa: F401
from app.repositories.knowledge import knowledge_repo as knowledge_repo  # noqa: F401
