"""Validate one `.atqskill` package without installing or executing it."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.workflows.support.question_type_packages import validate_atqskill  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 AITeachMe `.atqskill` 题型包。")
    parser.add_argument("package", type=Path, help="待校验的 .atqskill 文件")
    parser.add_argument("--show-compiled", action="store_true", help="输出完整编译定义（包含提示词）")
    args = parser.parse_args()

    result = validate_atqskill(args.package)
    excluded = set() if args.show_compiled else {"compiled_definition"}
    print(json.dumps(result.model_dump(mode="json", exclude=excluded), ensure_ascii=False, indent=2))
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
