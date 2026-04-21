"""Generate offline Alembic SQL and reject dangerous production DDL."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]

_DANGEROUS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("DROP SCHEMA", re.compile(r"\bDROP\s+SCHEMA\b", re.IGNORECASE)),
    ("DROP TABLE", re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE)),
    ("TRUNCATE", re.compile(r"\bTRUNCATE\b", re.IGNORECASE)),
    ("DROP COLUMN", re.compile(r"\bDROP\s+COLUMN\b", re.IGNORECASE)),
    ("ALTER TYPE", re.compile(r"\bALTER\s+TYPE\b", re.IGNORECASE)),
)
_ALLOW_MARKER = "atm-allow-destructive-ddl"


def generate_upgrade_sql() -> str:
    env = os.environ.copy()
    env.setdefault("APP_MODE", "cloud")
    env.setdefault(
        "DATABASE_URL",
        "postgresql+psycopg://user:pass@localhost:5432/aiteachme",
    )
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=BACKEND_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "failed to generate Alembic offline SQL\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return completed.stdout


def find_dangerous_sql(sql_text: str) -> list[str]:
    findings: list[str] = []
    for line_number, line in enumerate(sql_text.splitlines(), start=1):
        if _ALLOW_MARKER in line:
            continue
        for label, pattern in _DANGEROUS_PATTERNS:
            if pattern.search(line):
                findings.append(f"line {line_number}: {label}: {line.strip()}")
    return findings


def main() -> int:
    try:
        sql_text = generate_upgrade_sql()
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1

    findings = find_dangerous_sql(sql_text)
    if findings:
        print("dangerous Alembic upgrade SQL detected:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        print(
            "If this DDL is intentional, add a reviewed migration-specific "
            f"`{_ALLOW_MARKER}` marker and update this guard.",
            file=sys.stderr,
        )
        return 1

    print("Alembic upgrade SQL passed safety checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
