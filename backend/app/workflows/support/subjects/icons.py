"""Subject icon selection helpers for the subjects support use cases.

This module stores only stable icon keys. It does not generate images and does
not depend on frontend code; the React app maps these keys to its icon library.
"""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Mapping
from typing import Any

import structlog

from app.models import Subject
from app.schemas.llm import ChatMessage
from app.shared.infra.database import managed_session
from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.llm_support.routing import LLMCallPurpose

logger = structlog.get_logger(__name__)

SUBJECT_ICON_SETTINGS_KEY = "icon_key"

SUBJECT_ICON_OPTIONS: tuple[str, ...] = (
    "book-open",
    "book-marked",
    "book-text",
    "notebook-tabs",
    "notebook-pen",
    "library",
    "newspaper",
    "graduation-cap",
    "school",
    "backpack",
    "calculator",
    "sigma",
    "ruler",
    "compass",
    "square-function",
    "infinity",
    "flask-conical",
    "test-tube",
    "beaker",
    "atom",
    "magnet",
    "circuit-board",
    "microscope",
    "dna",
    "stethoscope",
    "pill",
    "heart-pulse",
    "brain",
    "scan-heart",
    "code",
    "braces",
    "terminal",
    "binary",
    "cpu",
    "database",
    "server",
    "network",
    "router",
    "shield-check",
    "key-round",
    "lock-keyhole",
    "bot",
    "workflow",
    "git-branch",
    "languages",
    "speech",
    "message-circle",
    "pen-tool",
    "pencil",
    "feather",
    "scroll-text",
    "file-text",
    "file-question",
    "files",
    "clipboard-check",
    "badge-check",
    "medal",
    "trophy",
    "landmark",
    "scale",
    "gavel",
    "scroll",
    "vote",
    "globe",
    "earth",
    "map",
    "map-pinned",
    "route",
    "land-plot",
    "mountain",
    "palette",
    "brush",
    "paintbrush",
    "shapes",
    "drafting-compass",
    "music",
    "piano",
    "audio-lines",
    "camera",
    "film",
    "video",
    "briefcase-business",
    "building-2",
    "factory",
    "chart-line",
    "chart-pie",
    "chart-bar",
    "wallet",
    "banknote",
    "hand-coins",
    "wrench",
    "hammer",
    "cog",
    "hard-hat",
    "telescope",
    "rocket",
    "satellite",
    "leaf",
    "sprout",
    "flower-2",
)

DEFAULT_SUBJECT_ICON_KEY = "book-open"
SUBJECT_ICON_OPTION_SET = frozenset(SUBJECT_ICON_OPTIONS)
_ICON_KEY_RE = re.compile(r"[a-z][a-z0-9-]*")
_KEYWORD_ICON_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("中考", "高考", "小学", "初中", "高中", "课堂", "school"), "school"),
    (("大学", "本科", "研究生", "公开课", "课程", "学位"), "graduation-cap"),
    (("笔记", "错题", "复习", "讲义", "课堂笔记"), "notebook-tabs"),
    (("python", "java", "c++", "javascript", "typescript", "编程", "程序", "代码", "算法", "计算机", "软件"), "code"),
    (("数据库", "sql", "mysql", "postgres", "数据仓库", "数据工程"), "database"),
    (("网络", "通信", "tcp", "http", "互联网", "network"), "network"),
    (("安全", "密码", "攻防", "隐私", "合规", "security"), "shield-check"),
    (("组成原理", "操作系统", "芯片", "硬件", "cpu"), "cpu"),
    (("嵌入式", "单片机", "电路板", "自动化"), "circuit-board"),
    (("高数", "高等数学", "线性代数", "概率", "统计", "微积分", "math", "calculus"), "sigma"),
    (("数学", "计算", "会计"), "calculator"),
    (("化学", "实验", "材料", "药学", "chem"), "flask-conical"),
    (("物理", "电路", "电子", "力学", "physics"), "atom"),
    (("遗传", "基因", "分子生物", "dna"), "dna"),
    (("临床", "护理", "诊断", "解剖", "医学", "medical"), "stethoscope"),
    (("药学", "药理", "医药", "执业药师"), "pill"),
    (("生物", "生命", "biology"), "microscope"),
    (("健康", "急救", "运动医学"), "heart-pulse"),
    (("英语", "日语", "韩语", "法语", "德语", "语言", "翻译", "english", "language"), "languages"),
    (("写作", "论文", "文案", "编辑", "作文"), "pen-tool"),
    (("心理", "认知", "哲学", "逻辑", "思维"), "brain"),
    (("金融", "经济", "投资", "数据分析", "财务", "finance", "economics"), "chart-line"),
    (("管理", "商业", "运营", "职场", "考证", "公务员", "business", "management"), "briefcase-business"),
    (("考试", "题库", "真题", "刷题", "测评", "习题"), "file-question"),
    (("认证", "资格证", "证书"), "badge-check"),
    (("法律", "法学", "司法", "law"), "scale"),
    (("历史", "政治", "公共管理", "history"), "landmark"),
    (("地球", "环境", "生态", "气候", "earth"), "earth"),
    (("地图", "区域", "旅游地理"), "map"),
    (("地理", "国际", "世界", "geography"), "globe"),
    (("艺术", "设计", "美术", "创意", "art", "design"), "palette"),
    (("建筑", "制图", "产品设计", "几何绘图"), "drafting-compass"),
    (("土木", "施工", "制造", "机械", "维修"), "wrench"),
    (("企业", "行政", "房地产", "城市规划"), "building-2"),
    (("天文", "宇宙", "前沿研究"), "telescope"),
    (("航天", "创业", "项目", "竞赛"), "rocket"),
    (("农业", "植物", "可持续"), "leaf"),
    (("音乐", "乐理", "声乐", "music"), "music"),
    (("证书", "政策", "合同", "文档", "资料"), "file-text"),
)


def _normalize_icon_text(value: object | None) -> str:
    return str(value or "").strip().strip("`'\"").lower()


def normalize_subject_icon_candidates(value: object | None) -> list[str]:
    cleaned = _normalize_icon_text(value)
    raw_candidates = (cleaned,) if cleaned in SUBJECT_ICON_OPTION_SET else _ICON_KEY_RE.findall(cleaned)
    return list(
        dict.fromkeys(
            candidate
            for candidate in raw_candidates
            if candidate in SUBJECT_ICON_OPTION_SET
        )
    )


def normalize_subject_icon_key(value: object | None) -> str | None:
    return next(iter(normalize_subject_icon_candidates(value)), None)


def select_subject_icon_candidate(value: object, *, fallback: str) -> str:
    normalized_fallback = normalize_subject_icon_key(fallback) or DEFAULT_SUBJECT_ICON_KEY
    try:
        candidates = normalize_subject_icon_candidates(value)
        return secrets.choice(candidates) if candidates else normalized_fallback
    except Exception as exc:
        logger.warning(
            "subject_icon_selection_candidate_failed",
            error=str(exc),
            fallback=normalized_fallback,
        )
        return normalized_fallback


def infer_subject_icon_key(subject_name: str | None) -> str:
    text = str(subject_name or "").strip().casefold()
    for keywords, icon_key in _KEYWORD_ICON_RULES:
        if any(keyword.casefold() in text for keyword in keywords):
            return icon_key
    return DEFAULT_SUBJECT_ICON_KEY


def get_subject_icon_key(subject: Subject) -> str:
    payload = _read_settings(subject)
    icon_key = normalize_subject_icon_key(payload.get(SUBJECT_ICON_SETTINGS_KEY))
    return icon_key or infer_subject_icon_key(subject.name)


def set_subject_icon_key(subject: Subject, icon_key: str | None) -> None:
    normalized = normalize_subject_icon_key(icon_key) or infer_subject_icon_key(subject.name)
    payload = _read_settings(subject)
    payload[SUBJECT_ICON_SETTINGS_KEY] = normalized
    subject.settings_json = json.dumps(payload, ensure_ascii=False)


def _merge_icon_completion_kwargs(
    overrides: Mapping[str, object] | None,
) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "call_purpose": LLMCallPurpose.CLASSIFY,
        "model": "light",
        "max_tokens": 20,
        "temperature": 0,
        "extra_metadata": {"substep": "select_subject_icon"},
    }
    if not overrides:
        return kwargs

    incoming = dict(overrides)
    incoming_metadata = incoming.pop("extra_metadata", {}) or {}
    metadata = dict(kwargs.get("extra_metadata") or {})
    if isinstance(incoming_metadata, Mapping):
        metadata.update(incoming_metadata)
    kwargs.update(incoming)
    kwargs["extra_metadata"] = metadata
    return kwargs


async def choose_subject_icon_key(
    subject_name: str,
    *,
    hints: list[str] | None = None,
    completion_kwargs: Mapping[str, object] | None = None,
) -> str:
    fallback = infer_subject_icon_key(subject_name)
    name = " ".join(str(subject_name or "").split()).strip()
    if not name:
        return fallback

    options_text = ",".join(SUBJECT_ICON_OPTIONS)
    hint_text = "\n".join(f"- {item}" for item in list(hints or [])[:8] if str(item).strip())
    user_content = (
        "请为这个学习学科选择 1-4 个合适的图标 key。\n"
        "只能从候选列表中选择；多个 key 用英文逗号分隔，不要解释。\n"
        "系统会从这些候选中随机挑一个作为最终图标。\n\n"
        f"学科名称：{name}\n"
        f"线索：\n{hint_text or '- 无'}\n\n"
        f"候选图标 key（英文逗号分隔）：{options_text}"
    )
    messages: list[ChatMessage] = [
        {
            "role": "system",
            "content": "你是学习产品里的学科图标分类器，只能输出候选图标 key。",
        },
        {"role": "user", "content": user_content},
    ]

    try:
        result = await acompletion_with_fallback(
            messages,
            **_merge_icon_completion_kwargs(completion_kwargs),
        )
    except Exception as exc:
        logger.warning("subject_icon_selection_failed", subject_name=name, error=str(exc))
        return fallback

    return select_subject_icon_candidate(result, fallback=fallback)


def schedule_subject_icon_refinement(
    background_task_registry: Any | None,
    *,
    subject_id: str,
    owner_user_id: str,
    subject_name: str,
) -> None:
    """Refine one subject icon in the background without blocking API responses."""

    name = " ".join(str(subject_name or "").split()).strip()
    if background_task_registry is None or not name:
        return

    background_task_registry.spawn(
        _refine_subject_icon_key_background(
            subject_id=subject_id,
            owner_user_id=owner_user_id,
            subject_name=name,
        ),
        kind="subjects.icon_refine",
        subject_id=subject_id,
        name=f"subjects.icon_refine:{subject_id}",
    )


async def _refine_subject_icon_key_background(
    *,
    subject_id: str,
    owner_user_id: str,
    subject_name: str,
) -> None:
    icon_key = await choose_subject_icon_key(subject_name)
    with managed_session() as session:
        subject = session.get(Subject, subject_id)
        if subject is None or subject.user_id != owner_user_id:
            return
        if " ".join(str(subject.name or "").split()).strip() != subject_name:
            return
        set_subject_icon_key(subject, icon_key)
        session.add(subject)


def _read_settings(subject: Subject) -> dict[str, object]:
    raw_value = (subject.settings_json or "").strip()
    if not raw_value:
        return {}
    try:
        decoded = json.loads(raw_value)
    except Exception:
        return {}
    return decoded if isinstance(decoded, dict) else {}


__all__ = [
    "DEFAULT_SUBJECT_ICON_KEY",
    "SUBJECT_ICON_OPTIONS",
    "choose_subject_icon_key",
    "get_subject_icon_key",
    "infer_subject_icon_key",
    "normalize_subject_icon_candidates",
    "normalize_subject_icon_key",
    "schedule_subject_icon_refinement",
    "select_subject_icon_candidate",
    "set_subject_icon_key",
]
