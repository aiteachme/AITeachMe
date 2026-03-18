"""知识图谱工具函数：名称规范化、成员签名计算。"""

from __future__ import annotations

import hashlib
import re
import unicodedata


def normalize_name(name: str) -> str:
    """NFKC 归一化 + 去空格/标点 + 小写。

    Property 5 保证幂等性：normalize_name(normalize_name(x)) == normalize_name(x)
    """
    text = name.strip().lower()
    text = unicodedata.normalize("NFKC", text)
    # 去除空白、连字符、下划线
    text = re.sub(r"[\s\-_]+", "", text)
    # 仅保留 word 字符和中文
    text = re.sub(r"[^\w\u4e00-\u9fff]", "", text)
    return text


def compute_member_signature(core_node_ids: list[int]) -> str:
    """排序后 core node ids 的 SHA-256 hash，用于教学单元稳定身份定位。"""
    sorted_ids = sorted(core_node_ids)
    payload = ",".join(str(nid) for nid in sorted_ids)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
