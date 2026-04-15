from __future__ import annotations

import ast
from pathlib import Path


def _iter_import_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    modules: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.append(node.module)

    return modules


def test_shared_infra_does_not_import_teaching_or_services() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    infra_root = backend_root / "app" / "shared" / "infra"

    violations: list[str] = []
    for path in infra_root.rglob("*.py"):
        for module in _iter_import_modules(path):
            if module.startswith("app.teaching") or module.startswith("app.services"):
                violations.append(f"{path.relative_to(backend_root)} -> {module}")

    assert violations == [], "shared.infra 出现了反向依赖:\n" + "\n".join(violations)


def test_workflows_do_not_import_retired_business_layers() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    workflows_root = backend_root / "app" / "workflows"

    violations: list[str] = []
    for path in workflows_root.rglob("*.py"):
        for module in _iter_import_modules(path):
            if module.startswith("app.teaching") or module.startswith("app.services"):
                violations.append(f"{path.relative_to(backend_root)} -> {module}")

    assert violations == [], "workflows 出现了旧业务层反向依赖:\n" + "\n".join(violations)


def test_build_planner_service_uses_planner_package_public_entry() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    target = backend_root / "app" / "services" / "knowledge_docs" / "build_planner_service.py"
    imports = set(_iter_import_modules(target))

    forbidden = {
        "app.workflows.digest.planner.contracts",
        "app.workflows.digest.planner.runner",
        "app.workflows.digest.planner.internal",
    }

    assert imports.isdisjoint(forbidden), (
        "build_planner_service 仍直接依赖 planner 内部模块: "
        + ", ".join(sorted(imports & forbidden))
    )


def test_subject_package_re_exports_subject_vector_helpers() -> None:
    from app.shared.infra.subject import (
        build_subject_vector_table_name,
        get_subject_vector_status_by_slug,
        should_generate_subject_embeddings,
    )

    assert build_subject_vector_table_name("subj-demo") == "chunk_embeddings_subj_demo"
    assert callable(get_subject_vector_status_by_slug)
    assert callable(should_generate_subject_embeddings)


def test_context_window_module_exports_budget_helpers() -> None:
    from app.shared.infra.llm_support.context_window import (
        ContextWindowManager,
        TokenBudget,
    )

    assert TokenBudget().total == 4000
    assert callable(ContextWindowManager.estimate_tokens)


def test_search_package_does_not_re_export_embedding_adapter() -> None:
    import app.shared.infra.embedding as embedding
    import app.shared.infra.search as search

    assert hasattr(embedding, "ATMEmbedding")
    assert not hasattr(search, "ATMEmbedding")
