"""Build deterministic `.atqskill` files from the repository examples."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.workflows.support.question_type_packages import (  # noqa: E402
    build_atqskill_archive,
    validate_atqskill,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="构建仓库中的示例题型包。")
    parser.add_argument(
        "--source-root",
        type=Path,
        default=REPOSITORY_ROOT / "examples" / "question-type-skills",
    )
    parser.add_argument("--output", type=Path, required=True, help="生成包的目标目录")
    args = parser.parse_args()

    output_root = args.output.resolve()
    built: list[dict[str, str]] = []
    seen_filenames: set[str] = set()
    for index, source_dir in enumerate(
        sorted(path for path in args.source_root.resolve().iterdir() if path.is_dir()),
        start=1,
    ):
        skill_path = source_dir / "SKILL.md"
        if not skill_path.is_file():
            continue
        staging_path = output_root / f".atqskill-build-{index}.atqskill"
        build_atqskill_archive(source_dir, staging_path)
        result = validate_atqskill(staging_path)
        if not result.valid:
            staging_path.unlink(missing_ok=True)
            print(
                json.dumps(
                    result.model_dump(mode="json", exclude={"compiled_definition"}),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1
        assert result.preview is not None
        filename = f"{result.preview.package_key}-{result.preview.version}.atqskill"
        if filename in seen_filenames:
            staging_path.unlink(missing_ok=True)
            raise RuntimeError(f"示例包输出文件名冲突：{filename}")
        seen_filenames.add(filename)
        target = output_root / filename
        if target.is_symlink():
            staging_path.unlink(missing_ok=True)
            raise RuntimeError(f"拒绝覆盖符号链接输出：{target}")
        staging_path.replace(target)
        built.append({"package": str(target), "sha256": result.package_hash})

    print(json.dumps({"built": built}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
