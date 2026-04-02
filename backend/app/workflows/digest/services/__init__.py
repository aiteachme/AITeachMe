"""Digest 服务层。

新增的教学重组服务：
- segmentation: 教学语义切分
- material_profiler: 材料画像
- blueprint_planner: 蓝图规划
"""

from app.workflows.digest.services.blueprint_planner import (
    BLUEPRINT_PROMPT,
    build_evidence_bundles,
    infer_archetype,
    plan_document_blueprint_from_clusters,
)
from app.workflows.digest.services.material_profiler import (
    build_material_profile,
    compute_material_stats,
    decide_digest_mode,
)
from app.workflows.digest.services.segmentation import (
    PRIMITIVE_CLASSIFY_PROMPT,
    assemble_blocks,
    classify_primitives_by_rules,
    get_uncertain_primitives,
    segment_sections,
)

__all__ = [
    # segmentation
    "classify_primitives_by_rules",
    "get_uncertain_primitives",
    "assemble_blocks",
    "segment_sections",
    "PRIMITIVE_CLASSIFY_PROMPT",
    # material_profiler
    "compute_material_stats",
    "decide_digest_mode",
    "build_material_profile",
    # blueprint_planner
    "infer_archetype",
    "plan_document_blueprint_from_clusters",
    "build_evidence_bundles",
    "BLUEPRINT_PROMPT",
]
