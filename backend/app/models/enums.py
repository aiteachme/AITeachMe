"""项目统一使用的枚举定义。"""

from __future__ import annotations

from enum import Enum


class TaskStatus(str, Enum):
    """异步任务通用状态。"""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DigestStep(str, Enum):
    """知识构建的细粒度步骤。"""

    CLEANED = "cleaned"
    OUTLINED = "outlined"
    STORED = "stored"
    CHUNKED = "chunked"
    EMBEDDED = "embedded"


class QuestionType(str, Enum):
    """题目类型。"""

    SINGLE_CHOICE = "single_choice"
    FILL_BLANK = "fill_blank"
    SHORT_ANSWER = "short_answer"


class Difficulty(str, Enum):
    """题目难度。"""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


# ── 知识图谱增量构建 + 多视图课程结构派生 ──


class KGNodeType(str, Enum):
    """知识图谱节点类型。"""

    TOPIC = "Topic"
    CONCEPT = "Concept"
    DEFINITION = "Definition"
    METHOD = "Method"
    EXAMPLE = "Example"


class KGEdgeType(str, Enum):
    """知识图谱边类型。"""

    BELONGS_TO_TOPIC = "belongs_to_topic"
    PREREQUISITE_OF = "prerequisite_of"
    DEFINED_BY = "defined_by"
    ILLUSTRATED_BY = "illustrated_by"
    PART_OF = "part_of"


class KGNodeStatus(str, Enum):
    """知识节点状态。"""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    MERGED = "merged"
    PENDING = "pending"


class KGEdgeStatus(str, Enum):
    """知识边状态。"""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    PENDING = "pending"


class EntityMatchDecision(str, Enum):
    """实体对齐判定结果。"""

    EXACT = "exact"
    ALIAS = "alias"
    BROADER = "broader"
    NARROWER = "narrower"
    RELATED_NOT_SAME = "related_not_same"
    NO_MATCH = "no_match"
    UNSURE = "unsure"


class RevisionReason(str, Enum):
    """修订原因。"""

    NEW_EVIDENCE = "new_evidence"
    MERGE = "merge"
    SPLIT = "split"
    HUMAN_EDIT = "human_edit"
    CONFLICT_RESOLUTION = "conflict_resolution"


class EvidenceRole(str, Enum):
    """证据角色。"""

    SUPPORTS = "supports"
    ELABORATES = "elaborates"
    CONTRADICTS = "contradicts"
    EXEMPLIFIES = "exemplifies"
    TAXONOMY_HINT = "taxonomy_hint"


class ExtractionMethod(str, Enum):
    """抽取方法。"""

    LLM = "llm"
    MANUAL = "manual"
    RULE = "rule"


class FieldScope(str, Enum):
    """证据字段范围。"""

    NAME = "name"
    SUMMARY = "summary"
    BODY = "body"
    EDGE_DESCRIPTION = "edge_description"
    TAXONOMY_HINT = "taxonomy_hint"


class AliasStatus(str, Enum):
    """别名状态。"""

    ACTIVE = "active"
    DEPRECATED = "deprecated"


class UnitMemberRole(str, Enum):
    """教学单元成员角色。"""

    CORE = "core"
    SUPPORT = "support"
    EXAMPLE = "example"
    PREREQUISITE_BRIDGE = "prerequisite_bridge"


class UnitStatus(str, Enum):
    """教学单元状态。"""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    MERGED = "merged"
    PENDING = "pending"


class AnchorType(str, Enum):
    """分类锚点类型。"""

    TEACHER_DEFINED = "teacher_defined"
    SYLLABUS = "syllabus"
    TEXTBOOK_TOC = "textbook_toc"
    GRAPH_DISCOVERED = "graph_discovered"
    SYSTEM = "system"


class AnchorStatus(str, Enum):
    """锚点状态。"""

    ACTIVE = "active"
    DEPRECATED = "deprecated"


class TreeVersionStatus(str, Enum):
    """树/DAG/快照版本状态。"""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class ThemeTreeNodeType(str, Enum):
    """主题树节点类型。THEME 对应知识图谱中 Topic 级别的主题分组，
    避免与 KGNodeType.TOPIC 混淆。"""

    CHAPTER = "chapter"
    SECTION = "section"
    THEME = "theme"
    UNIT_BUCKET = "unit_bucket"
    UNCATEGORIZED = "uncategorized"


class UnitTreeMembershipRole(str, Enum):
    """教学单元在主题树中的归属角色。"""

    PRIMARY = "primary"
    SECONDARY = "secondary"
    CROSS_LINK = "cross_link"


class MembershipSource(str, Enum):
    """归属来源。"""

    AUTO = "auto"
    HUMAN_FIXED = "human_fixed"


class DependencyType(str, Enum):
    """单元依赖类型。"""

    PREREQUISITE = "prerequisite"
    COREQUISITE = "corequisite"


class DigestJobStatus(str, Enum):
    """增量构建任务状态。"""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class IngestStatus(str, Enum):
    """Ingest 流水线状态。"""

    PENDING = "pending"
    CLASSIFYING = "classifying"
    PARSING = "parsing"
    VALIDATING = "validating"
    READY_FOR_DIGEST = "ready_for_digest"
    RETRY_PENDING = "retry_pending"
    FAILED = "failed"
