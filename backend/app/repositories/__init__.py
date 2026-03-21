"""数据访问层。"""

from . import assessment_repo as assessment_repo  # noqa: F401

# knowledge 子模块 re-export，保持 `from app.repositories import kg_repo` 兼容
from app.repositories.knowledge import curriculum_repo as curriculum_repo  # noqa: F401
from app.repositories.knowledge import kg_repo as kg_repo  # noqa: F401
from app.repositories.knowledge import knowledge_repo as knowledge_repo  # noqa: F401
