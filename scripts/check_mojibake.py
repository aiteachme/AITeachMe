#!/usr/bin/env python3
"""Scan a directory tree for likely mojibake and encoding issues.

Examples:
  python scripts/check_mojibake.py
  python scripts/check_mojibake.py docs
  python scripts/check_mojibake.py --verbose

Behavior:
  - Recursively scans files under the target path.
  - Skips common dependency, VCS, cache, and build directories.
  - Ignores likely binary files.
  - Reports files with decode failures, replacement characters, or strong
    mojibake signals such as "锟斤拷" and common UTF-8-vs-Latin-1 corruption.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
import re


IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    "coverage",
    ".next",
    ".nuxt",
    ".idea",
    ".vscode",
    ".pytest_cache",
    "data",
}

IGNORED_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
    ".tar",
    ".7z",
    ".rar",
    ".mp3",
    ".mp4",
    ".avi",
    ".mov",
    ".wav",
    ".ogg",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".eot",
    ".so",
    ".dll",
    ".exe",
    ".class",
    ".jar",
    ".pyc",
    ".pyd",
    ".sqlite",
    ".db",
    ".bin",
    ".lock",
}

COMMON_ENCODINGS = ("utf-8", "utf-8-sig", "gb18030", "utf-16", "utf-16-le", "utf-16-be")
COMMON_MOJIBAKE_SNIPPETS = (
    "锟斤拷",
    "烫烫烫",
    "Ã",
    "Â",
    "â€",
    "â€™",
    "â€œ",
    "â€",
    "ðŸ",
)
LATIN_MOJIBAKE_RE = re.compile(r"(?:Ã.|Â.|â..|ð.)")
SELF_PATH = Path(__file__).resolve()


@dataclass
class Finding:
    path: Path
    reason: str
    detail: str


def safe_print(message: str, *, stream: object = sys.stdout) -> None:
    target = stream
    encoding = getattr(target, "encoding", None) or "utf-8"
    try:
        print(message, file=target)
    except UnicodeEncodeError:
        data = message.encode(encoding, errors="backslashreplace")
        text = data.decode(encoding, errors="strict")
        print(text, file=target)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check all text files under a path for likely mojibake or encoding corruption."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Root path to scan (default: current directory).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print skipped binary files and clean text encoding choices.",
    )
    return parser.parse_args()


def should_skip(path: Path) -> bool:
    return any(part in IGNORED_DIRS for part in path.parts)


def is_likely_binary(data: bytes) -> bool:
    if not data:
        return False
    if b"\x00" in data:
        return True
    sample = data[:4096]
    control_count = sum(
        1
        for byte in sample
        if byte < 32 and byte not in (9, 10, 13, 12)
    )
    return control_count / max(len(sample), 1) > 0.30


def decode_text(data: bytes) -> tuple[str | None, str | None]:
    for encoding in COMMON_ENCODINGS:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return None, None


def suspicious_from_roundtrip(text: str) -> str | None:
    try:
        repaired = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None

    if repaired == text:
        return None

    text_hits = sum(token in text for token in COMMON_MOJIBAKE_SNIPPETS) + len(LATIN_MOJIBAKE_RE.findall(text))
    repaired_hits = sum(token in repaired for token in COMMON_MOJIBAKE_SNIPPETS) + len(LATIN_MOJIBAKE_RE.findall(repaired))
    if text_hits > repaired_hits:
        preview = repaired.replace("\n", " ")[:80]
        return f"looks like UTF-8 text was misread as Latin-1/CP1252; possible repair: {preview!r}"
    return None


def count_private_use_chars(text: str) -> int:
    return sum(1 for ch in text if 0xE000 <= ord(ch) <= 0xF8FF)


def inspect_text(path: Path, text: str, encoding: str) -> list[Finding]:
    findings: list[Finding] = []

    if "\ufffd" in text:
        findings.append(Finding(path, "replacement character found", "contains '�'"))

    bad_snippets = [snippet for snippet in COMMON_MOJIBAKE_SNIPPETS if snippet in text]
    if bad_snippets:
        findings.append(
            Finding(
                path,
                "common mojibake markers found",
                ", ".join(repr(item) for item in bad_snippets[:5]),
            )
        )

    roundtrip_hint = suspicious_from_roundtrip(text)
    if roundtrip_hint:
        findings.append(Finding(path, "suspicious mojibake roundtrip", roundtrip_hint))

    private_use_count = count_private_use_chars(text)
    if private_use_count >= 3:
        findings.append(
            Finding(
                path,
                "suspicious private-use characters found",
                f"contains {private_use_count} chars in U+E000-U+F8FF; often a sign of CJK mojibake",
            )
        )

    if encoding.startswith("utf-16") and "\x00" not in text and len(text.strip()) == 0:
        findings.append(Finding(path, "suspicious UTF-16 decode", f"decoded as {encoding} but content looks empty"))

    return findings


def scan_file(path: Path, verbose: bool) -> list[Finding]:
    if path.suffix.lower() in IGNORED_SUFFIXES:
        if verbose:
            print(f"[SKIP-SUFFIX] {path}")
        return []

    try:
        data = path.read_bytes()
    except OSError as exc:
        return [Finding(path, "read failed", str(exc))]

    if is_likely_binary(data):
        if verbose:
            print(f"[SKIP-BINARY] {path}")
        return []

    text, encoding = decode_text(data)
    if text is None or encoding is None:
        return [Finding(path, "decode failed", "unable to decode with utf-8/gb18030/utf-16 family")]

    if verbose:
        print(f"[OK:{encoding}] {path}")
    return inspect_text(path, text, encoding)


def iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if path.resolve() == SELF_PATH:
            continue
        if should_skip(path.relative_to(root)):
            continue
        files.append(path)
    return files


def main() -> int:
    args = parse_args()
    root = Path(args.path).resolve()

    if not root.exists():
        safe_print(f"Path does not exist: {root}", stream=sys.stderr)
        return 2
    if not root.is_dir():
        safe_print(f"Path is not a directory: {root}", stream=sys.stderr)
        return 2

    files = iter_files(root)
    findings: list[Finding] = []

    for path in files:
        findings.extend(scan_file(path, verbose=args.verbose))

    if not findings:
        safe_print(f"Checked {len(files)} files under {root}. No obvious mojibake found.")
        return 0

    safe_print(f"Checked {len(files)} files under {root}. Found {len(findings)} possible issue(s):")
    for finding in findings:
        safe_print(f"- {finding.path}: {finding.reason} ({finding.detail})")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
