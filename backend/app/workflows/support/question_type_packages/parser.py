"""Parse restricted `SKILL.md` frontmatter and package JSON documents.

This parser rejects YAML aliases, tags, merge keys and duplicate keys before
schema validation. It does not interpret the Markdown body as executable input.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

import yaml
from yaml.constructor import ConstructorError
from yaml.tokens import AliasToken, AnchorToken, DirectiveToken, TagToken

from app.workflows.support.question_type_packages.contracts import AtqSkillPackageError

_FRONTMATTER_BOUNDARY = "---"
_MERGE_KEY_RE = re.compile(r"(?m)^\s*<<\s*:")
_MAX_YAML_DEPTH = 12
_MAX_YAML_NODES = 512


def _reject_json_constant(value: str) -> None:
    raise ValueError(value)


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """SafeLoader variant that fails instead of silently overwriting keys."""


def _construct_unique_mapping(loader: _UniqueKeySafeLoader, node: yaml.MappingNode, deep: bool = False):
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def decode_utf8(content: bytes, *, path: str) -> str:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AtqSkillPackageError("TEXT_ENCODING_INVALID", path, "文本文件必须使用 UTF-8 编码。") from exc
    if text.startswith("\ufeff"):
        raise AtqSkillPackageError("TEXT_ENCODING_INVALID", path, "文本文件不能包含 UTF-8 BOM。")
    if any(
        (ord(character) < 32 and character not in {"\t", "\n", "\r"})
        or ord(character) == 127
        for character in text
    ):
        raise AtqSkillPackageError("TEXT_CONTENT_INVALID", path, "文本文件不能包含控制字符。")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _validate_json_compatible(
    value: Any,
    *,
    path: str,
    code: str = "FRONTMATTER_INVALID",
    depth: int = 0,
    counter: list[int] | None = None,
) -> None:
    if counter is None:
        counter = [0]
    counter[0] += 1
    if counter[0] > _MAX_YAML_NODES or depth > _MAX_YAML_DEPTH:
        raise AtqSkillPackageError(code, path, "文档结构过深或节点过多。")
    if isinstance(value, float) and not math.isfinite(value):
        raise AtqSkillPackageError(code, path, "文档不能包含 NaN 或无穷大。")
    if isinstance(value, str) and any(
        ord(character) < 32 and character not in {"\t", "\n", "\r"}
        for character in value
    ):
        raise AtqSkillPackageError(code, path, "文档字符串不能包含控制字符。")
    if value is None or isinstance(value, (str, int, float, bool)):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_compatible(
                item,
                path=f"{path}[{index}]",
                code=code,
                depth=depth + 1,
                counter=counter,
            )
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise AtqSkillPackageError(code, path, "文档的对象键必须是字符串。")
            _validate_json_compatible(
                item,
                path=f"{path}.{key}",
                code=code,
                depth=depth + 1,
                counter=counter,
            )
        return
    raise AtqSkillPackageError(code, path, "文档只能包含 JSON 兼容值。")


def _construct_unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_skill_markdown(content: bytes) -> tuple[dict[str, Any], str]:
    text = decode_utf8(content, path="SKILL.md")
    lines = text.splitlines()
    if not lines or lines[0] != _FRONTMATTER_BOUNDARY:
        raise AtqSkillPackageError("FRONTMATTER_INVALID", "SKILL.md", "`SKILL.md` 必须以 YAML Frontmatter 开始。")
    try:
        closing_index = lines.index(_FRONTMATTER_BOUNDARY, 1)
    except ValueError as exc:
        raise AtqSkillPackageError("FRONTMATTER_INVALID", "SKILL.md", "`SKILL.md` 缺少 Frontmatter 结束边界。") from exc
    frontmatter_text = "\n".join(lines[1:closing_index])
    if not frontmatter_text.strip():
        raise AtqSkillPackageError("FRONTMATTER_INVALID", "SKILL.md", "Frontmatter 不能为空。")
    if _MERGE_KEY_RE.search(frontmatter_text):
        raise AtqSkillPackageError("FRONTMATTER_INVALID", "SKILL.md", "Frontmatter 不允许 YAML merge key。")
    try:
        for token in yaml.scan(frontmatter_text):
            if isinstance(token, (AliasToken, AnchorToken, DirectiveToken, TagToken)):
                raise AtqSkillPackageError(
                    "FRONTMATTER_INVALID",
                    "SKILL.md",
                    "Frontmatter 不允许 YAML directive、tag、anchor 或 alias。",
                )
        manifest = yaml.load(frontmatter_text, Loader=_UniqueKeySafeLoader)
    except AtqSkillPackageError:
        raise
    except (OverflowError, RecursionError, ValueError, yaml.YAMLError, ConstructorError) as exc:
        raise AtqSkillPackageError("FRONTMATTER_INVALID", "SKILL.md", "Frontmatter 不是有效的受限 YAML。") from exc
    if not isinstance(manifest, dict):
        raise AtqSkillPackageError("FRONTMATTER_INVALID", "SKILL.md", "Frontmatter 顶层必须是对象。")
    _validate_json_compatible(manifest, path="$manifest")
    body = "\n".join(lines[closing_index + 1 :]).strip()
    return manifest, body


def parse_json_document(content: bytes, *, path: str) -> dict[str, Any]:
    text = decode_utf8(content, path=path)
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_construct_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise AtqSkillPackageError("JSON_INVALID", path, "JSON 文件格式无效。") from exc
    if not isinstance(payload, dict):
        raise AtqSkillPackageError("JSON_INVALID", path, "JSON 顶层必须是对象。")
    _validate_json_compatible(payload, path=path, code="JSON_INVALID")
    return payload


__all__ = ["decode_utf8", "parse_json_document", "parse_skill_markdown"]
