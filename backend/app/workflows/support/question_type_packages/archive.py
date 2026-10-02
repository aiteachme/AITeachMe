"""Safe ZIP reading and deterministic building for `.atqskill` packages.

Validation reads members into bounded memory and never extracts uploaded paths.
The deterministic builder is used by examples and tests, not by HTTP upload code.
"""

from __future__ import annotations

import hashlib
import re
import stat
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Mapping

from app.workflows.support.question_type_packages.contracts import (
    ATQSKILL_SUFFIX,
    AtqSkillPackageError,
    MAX_COMPRESSION_RATIO,
    MAX_DIRECTORY_DEPTH,
    MAX_MEMBER_BYTES,
    MAX_PACKAGE_BYTES,
    MAX_PACKAGE_FILES,
    MAX_PATH_CHARS,
    MAX_UNCOMPRESSED_BYTES,
)

_CHUNK_BYTES = 64 * 1024
_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:")
_PROMPT_PATH_RE = re.compile(r"^prompts/[a-z0-9][a-z0-9_-]{0,63}\.md$")
_REFERENCE_PATH_RE = re.compile(r"^references/[a-z0-9][a-z0-9_-]{0,63}\.json$")
_TOOL_PATH_RE = re.compile(r"^tools/[a-z0-9][a-z0-9_-]{0,63}\.json$")
_DIRECTORY_SEGMENT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_ASSET_PATH_RE = re.compile(
    r"^assets/(?:[a-z0-9][a-z0-9_-]{0,63}/){0,4}"
    r"[a-z0-9][a-z0-9_.-]{0,100}\.(?:png|jpe?g|webp)$"
)
_NESTED_ARCHIVE_SUFFIXES = {".zip", ".atqskill", ".tar", ".gz", ".7z", ".rar"}
_WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


@dataclass(frozen=True)
class AtqSkillArchive:
    """Bounded in-memory view of a validated archive container."""

    package_path: Path
    files: Mapping[str, bytes]
    package_sha256: str
    file_sha256: Mapping[str, str]


def _is_allowed_package_file(path: str) -> bool:
    return (
        path == "SKILL.md"
        or bool(_PROMPT_PATH_RE.fullmatch(path))
        or bool(_REFERENCE_PATH_RE.fullmatch(path))
        or bool(_TOOL_PATH_RE.fullmatch(path))
        or bool(_ASSET_PATH_RE.fullmatch(path))
    )


def _validate_member_path(raw_name: str, *, is_directory: bool = False) -> str:
    if not raw_name or "\x00" in raw_name or any(ord(char) < 32 or ord(char) == 127 for char in raw_name):
        raise AtqSkillPackageError("ARCHIVE_PATH_INVALID", raw_name or "$archive", "压缩包包含空路径或控制字符。")
    if "\\" in raw_name or "//" in raw_name or raw_name.startswith("/") or _DRIVE_PATH_RE.match(raw_name):
        raise AtqSkillPackageError("ARCHIVE_PATH_INVALID", raw_name, "压缩包路径必须是使用 `/` 的相对路径。")
    normalized_name = unicodedata.normalize("NFC", raw_name)
    if normalized_name != raw_name:
        raise AtqSkillPackageError("ARCHIVE_PATH_INVALID", raw_name, "压缩包路径必须使用 Unicode NFC 规范形式。")
    trimmed_name = raw_name[:-1] if is_directory and raw_name.endswith("/") else raw_name
    path = PurePosixPath(trimmed_name)
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise AtqSkillPackageError("ARCHIVE_PATH_INVALID", raw_name, "压缩包路径不能包含空段、`.` 或 `..`。")
    if len(trimmed_name) > MAX_PATH_CHARS or len(path.parts) - 1 > MAX_DIRECTORY_DEPTH:
        raise AtqSkillPackageError("ARCHIVE_PATH_INVALID", raw_name, "压缩包路径过长或目录层级过深。")
    for part in path.parts:
        stem = part.split(".", 1)[0].casefold()
        if stem in _WINDOWS_RESERVED_NAMES or part.endswith((" ", ".")):
            raise AtqSkillPackageError("ARCHIVE_PATH_INVALID", raw_name, "压缩包路径包含 Windows 保留名称。")
    if is_directory:
        if path.parts[0] not in {"prompts", "references", "tools", "assets"}:
            raise AtqSkillPackageError("ARCHIVE_PATH_INVALID", raw_name, "压缩包包含未声明的根目录。")
        if path.parts[0] != "assets" and len(path.parts) != 1:
            raise AtqSkillPackageError("ARCHIVE_PATH_INVALID", raw_name, "prompts、references 和 tools 不支持子目录。")
        if path.parts[0] == "assets" and any(
            not _DIRECTORY_SEGMENT_RE.fullmatch(part) for part in path.parts[1:]
        ):
            raise AtqSkillPackageError("ARCHIVE_PATH_INVALID", raw_name, "资源目录名必须使用小写 ASCII 字符。")
        return trimmed_name
    if Path(trimmed_name).suffix.casefold() in _NESTED_ARCHIVE_SUFFIXES:
        raise AtqSkillPackageError("UNSUPPORTED_FILE", raw_name, "题型包不能包含嵌套压缩包。")
    if not _is_allowed_package_file(trimmed_name):
        raise AtqSkillPackageError("UNSUPPORTED_FILE", raw_name, "题型包包含 V1 不支持的文件路径或类型。")
    return trimmed_name


def _canonical_content(path: str, content: bytes) -> bytes:
    if Path(path).suffix.casefold() not in {".md", ".json"}:
        return content
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return content
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _package_hash(files: Mapping[str, bytes]) -> tuple[str, dict[str, str]]:
    digest = hashlib.sha256()
    file_hashes: dict[str, str] = {}
    for path in sorted(files):
        canonical = _canonical_content(path, files[path])
        content_hash = hashlib.sha256(canonical).hexdigest()
        file_hashes[path] = content_hash
        path_bytes = path.encode("utf-8")
        digest.update(len(path_bytes).to_bytes(4, "big"))
        digest.update(path_bytes)
        digest.update(len(canonical).to_bytes(8, "big"))
        digest.update(canonical)
    return digest.hexdigest(), file_hashes


def read_atqskill_archive(package_path: str | Path) -> AtqSkillArchive:
    """Read one package after enforcing archive and member limits."""

    path = Path(package_path)
    if path.suffix.casefold() != ATQSKILL_SUFFIX:
        raise AtqSkillPackageError("UNSUPPORTED_FILE", str(path), f"题型包必须使用 `{ATQSKILL_SUFFIX}` 扩展名。")
    if not path.is_file() or path.is_symlink():
        raise AtqSkillPackageError("PACKAGE_NOT_FOUND", str(path), "题型包文件不存在。")
    if path.stat().st_size > MAX_PACKAGE_BYTES:
        raise AtqSkillPackageError("PACKAGE_TOO_LARGE", str(path), "压缩包不能超过 8 MB。")
    if not zipfile.is_zipfile(path):
        raise AtqSkillPackageError("ARCHIVE_INVALID", str(path), "文件不是有效的 ZIP 题型包。")

    files: dict[str, bytes] = {}
    seen_casefolded: set[str] = set()
    declared_uncompressed = 0
    try:
        with zipfile.ZipFile(path, "r") as archive:
            members = archive.infolist()
            if len(members) > MAX_PACKAGE_FILES:
                raise AtqSkillPackageError(
                    "PACKAGE_FILE_LIMIT_EXCEEDED",
                    "$archive",
                    f"题型包最多包含 {MAX_PACKAGE_FILES} 个文件。",
                )
            for member in members:
                member_path = _validate_member_path(member.filename, is_directory=member.is_dir())
                folded = member_path.casefold()
                if folded in seen_casefolded:
                    raise AtqSkillPackageError("DUPLICATE_PACKAGE_PATH", member.filename, "题型包包含重复或大小写冲突路径。")
                seen_casefolded.add(folded)
                if member.flag_bits & 0x1:
                    raise AtqSkillPackageError("ARCHIVE_ENCRYPTED", member.filename, "题型包不能包含加密文件。")
                unix_mode = member.external_attr >> 16
                file_type = stat.S_IFMT(unix_mode)
                if member.is_dir():
                    if file_type and file_type != stat.S_IFDIR:
                        raise AtqSkillPackageError("ARCHIVE_LINK_UNSUPPORTED", member.filename, "题型包不能包含符号链接或特殊文件。")
                    continue
                if file_type and file_type != stat.S_IFREG:
                    raise AtqSkillPackageError("ARCHIVE_LINK_UNSUPPORTED", member.filename, "题型包不能包含符号链接或特殊文件。")
                if member.file_size > MAX_MEMBER_BYTES:
                    raise AtqSkillPackageError("PACKAGE_MEMBER_TOO_LARGE", member.filename, "题型包单文件不能超过 4 MB。")
                declared_uncompressed += member.file_size
                if declared_uncompressed > MAX_UNCOMPRESSED_BYTES:
                    raise AtqSkillPackageError("PACKAGE_TOO_LARGE", "$archive", "题型包解压后不能超过 24 MB。")
                if (
                    member.file_size > 1024
                    and (member.compress_size == 0 or member.file_size / member.compress_size > MAX_COMPRESSION_RATIO)
                ):
                    raise AtqSkillPackageError("ARCHIVE_COMPRESSION_RATIO_INVALID", member.filename, "题型包文件压缩比异常。")

                chunks: list[bytes] = []
                actual_size = 0
                with archive.open(member, "r") as source:
                    while True:
                        chunk = source.read(_CHUNK_BYTES)
                        if not chunk:
                            break
                        actual_size += len(chunk)
                        if actual_size > MAX_MEMBER_BYTES:
                            raise AtqSkillPackageError("PACKAGE_MEMBER_TOO_LARGE", member.filename, "题型包单文件不能超过 4 MB。")
                        chunks.append(chunk)
                if actual_size != member.file_size:
                    raise AtqSkillPackageError("ARCHIVE_INVALID", member.filename, "压缩包成员长度与目录记录不一致。")
                files[member_path] = b"".join(chunks)
    except AtqSkillPackageError:
        raise
    except (NotImplementedError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise AtqSkillPackageError("ARCHIVE_INVALID", str(path), "题型包读取失败或已损坏。") from exc

    if "SKILL.md" not in files:
        raise AtqSkillPackageError("MANIFEST_MISSING", "SKILL.md", "题型包根目录缺少 `SKILL.md`。")
    package_sha256, file_sha256 = _package_hash(files)
    return AtqSkillArchive(
        package_path=path.resolve(),
        files=MappingProxyType(files),
        package_sha256=package_sha256,
        file_sha256=MappingProxyType(file_sha256),
    )


def build_atqskill_archive(source_dir: str | Path, target_path: str | Path) -> Path:
    """Build a deterministic package from a source directory."""

    source_input = Path(source_dir)
    target_input = Path(target_path)
    if source_input.is_symlink():
        raise AtqSkillPackageError("PACKAGE_SOURCE_INVALID", str(source_input), "示例包源目录不能是符号链接。")
    if target_input.is_symlink():
        raise AtqSkillPackageError("PACKAGE_TARGET_INVALID", str(target_input), "输出文件不能是符号链接。")
    source = source_input.resolve()
    target = target_input.resolve()
    if not source.is_dir():
        raise AtqSkillPackageError("PACKAGE_SOURCE_INVALID", str(source), "示例包源目录不存在或为符号链接。")
    if target.suffix.casefold() != ATQSKILL_SUFFIX:
        raise AtqSkillPackageError("UNSUPPORTED_FILE", str(target), f"输出文件必须使用 `{ATQSKILL_SUFFIX}` 扩展名。")
    try:
        target.relative_to(source)
    except ValueError:
        pass
    else:
        raise AtqSkillPackageError("PACKAGE_TARGET_INVALID", str(target), "输出文件不能位于题型包源目录内。")
    source_files: list[tuple[str, bytes]] = []
    total_bytes = 0
    for candidate in source.rglob("*"):
        if candidate.is_symlink():
            raise AtqSkillPackageError("ARCHIVE_LINK_UNSUPPORTED", str(candidate), "源目录不能包含符号链接。")
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(source).as_posix()
        _validate_member_path(relative)
        content = candidate.read_bytes()
        size_bytes = len(content)
        if size_bytes > MAX_MEMBER_BYTES:
            raise AtqSkillPackageError("PACKAGE_MEMBER_TOO_LARGE", relative, "题型包单文件不能超过 4 MB。")
        total_bytes += size_bytes
        if total_bytes > MAX_UNCOMPRESSED_BYTES:
            raise AtqSkillPackageError("PACKAGE_TOO_LARGE", str(source), "题型包解压后不能超过 24 MB。")
        source_files.append((relative, content))
    if len(source_files) > MAX_PACKAGE_FILES:
        raise AtqSkillPackageError("PACKAGE_FILE_LIMIT_EXCEEDED", str(source), "源目录文件数量超过限制。")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, content in sorted(source_files):
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content, compresslevel=9)
    return target


__all__ = ["AtqSkillArchive", "build_atqskill_archive", "read_atqskill_archive"]
