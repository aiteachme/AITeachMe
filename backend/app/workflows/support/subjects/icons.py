"""Subject icon selection helpers for the subjects support use cases.

This module stores only stable icon keys. It does not generate images and does
not depend on frontend code; the React app maps these keys to its icon library.
"""

from __future__ import annotations

import json
import re

import structlog

from app.models import Subject
from app.schemas.llm import ChatMessage
from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.llm_support.routing import LLMCallPurpose

logger = structlog.get_logger(__name__)

SUBJECT_ICON_SETTINGS_KEY = "icon_key"

SUBJECT_ICON_OPTIONS: dict[str, str] = {
    "book-open": "通用课程、教材、阅读、文学、语文",
    "calculator": "数学、计算、会计、基础理科",
    "sigma": "高等数学、统计、概率、抽象数学",
    "flask-conical": "化学、实验、材料、药学",
    "atom": "物理、工程、电子、电路",
    "microscope": "生物、医学、生命科学",
    "code": "编程、计算机、算法、软件工程",
    "languages": "外语、翻译、写作、语言学习",
    "brain": "心理学、认知、哲学、思维训练",
    "briefcase-business": "管理、商业、职业考试、职场技能",
    "chart-line": "经济、金融、数据分析、统计应用",
    "landmark": "历史、政治、法律、公共管理",
    "globe": "地理、国际关系、世界知识",
    "palette": "艺术、设计、美术、创意",
    "music": "音乐、声乐、乐理",
    "file-text": "证书备考、政策文本、文档型资料",
}

_ICON_KEY_RE = re.compile(r"[a-z][a-z0-9-]*")
_KEYWORD_ICON_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("python", "java", "c++", "javascript", "typescript", "编程", "程序", "代码", "算法", "计算机", "软件"), "code"),
    (("高数", "高等数学", "线性代数", "概率", "统计", "微积分", "math", "calculus"), "sigma"),
    (("数学", "计算", "会计"), "calculator"),
    (("化学", "实验", "材料", "药学", "chem"), "flask-conical"),
    (("物理", "电路", "电子", "力学", "physics"), "atom"),
    (("生物", "医学", "医药", "生命", "解剖", "biology", "medical"), "microscope"),
    (("英语", "日语", "韩语", "法语", "德语", "语言", "翻译", "写作", "english", "language"), "languages"),
    (("心理", "认知", "哲学", "逻辑", "思维"), "brain"),
    (("金融", "经济", "投资", "数据分析", "财务", "finance", "economics"), "chart-line"),
    (("管理", "商业", "运营", "职场", "考证", "公务员", "business", "management"), "briefcase-business"),
    (("历史", "政治", "法律", "法学", "公共管理", "history", "law"), "landmark"),
    (("地理", "国际", "世界", "geography"), "globe"),
    (("艺术", "设计", "美术", "创意", "art", "design"), "palette"),
    (("音乐", "乐理", "声乐", "music"), "music"),
    (("证书", "政策", "合同", "文档", "资料"), "file-text"),
)


def normalize_subject_icon_key(value: str | None) -> str | None:
    cleaned = str(value or "").strip().strip("`'\"").lower()
    if cleaned in SUBJECT_ICON_OPTIONS:
        return cleaned

    for candidate in _ICON_KEY_RE.findall(cleaned):
        if candidate in SUBJECT_ICON_OPTIONS:
            return candidate
    return None


def infer_subject_icon_key(subject_name: str | None) -> str:
    text = str(subject_name or "").strip().casefold()
    for keywords, icon_key in _KEYWORD_ICON_RULES:
        if any(keyword.casefold() in text for keyword in keywords):
            return icon_key
    return "book-open"


def get_subject_icon_key(subject: Subject) -> str:
    payload = _read_settings(subject)
    icon_key = normalize_subject_icon_key(payload.get(SUBJECT_ICON_SETTINGS_KEY))
    return icon_key or infer_subject_icon_key(subject.name)


def set_subject_icon_key(subject: Subject, icon_key: str | None) -> None:
    normalized = normalize_subject_icon_key(icon_key) or infer_subject_icon_key(subject.name)
    payload = _read_settings(subject)
    payload[SUBJECT_ICON_SETTINGS_KEY] = normalized
    subject.settings_json = json.dumps(payload, ensure_ascii=False)


async def choose_subject_icon_key(subject_name: str, *, hints: list[str] | None = None) -> str:
    fallback = infer_subject_icon_key(subject_name)
    name = " ".join(str(subject_name or "").split()).strip()
    if not name:
        return fallback

    options_text = "\n".join(
        f"- {key}: {description}" for key, description in SUBJECT_ICON_OPTIONS.items()
    )
    hint_text = "\n".join(f"- {item}" for item in list(hints or [])[:8] if str(item).strip())
    user_content = (
        "请为这个学习学科选择一个最合适的图标 key。\n"
        "只能从候选列表中选择，输出必须只有一个 key，不要解释。\n\n"
        f"学科名称：{name}\n"
        f"线索：\n{hint_text or '- 无'}\n\n"
        f"候选图标：\n{options_text}"
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
            call_purpose=LLMCallPurpose.CLASSIFY,
            model="light",
            max_tokens=20,
            temperature=0,
            extra_metadata={"substep": "select_subject_icon"},
        )
    except Exception as exc:
        logger.warning("subject_icon_selection_failed", subject_name=name, error=str(exc))
        return fallback

    return normalize_subject_icon_key(str(result)) or fallback


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
    "SUBJECT_ICON_OPTIONS",
    "choose_subject_icon_key",
    "get_subject_icon_key",
    "infer_subject_icon_key",
    "normalize_subject_icon_key",
    "set_subject_icon_key",
]
