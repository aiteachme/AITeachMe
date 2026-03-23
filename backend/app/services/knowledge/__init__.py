"""Knowledge service package.

Keep this package initializer intentionally lightweight.

Importing submodules here caused eager side effects during package loading:
`docgen_store` import -> package `__init__` -> `digest_service` ->
`app.workflows.digest` -> workflow graph/runtime imports -> circular import.

Callers should import the concrete service modules they need, for example:
`from app.services.knowledge.digest_service import trigger_docgen_build`.
"""

__all__: list[str] = []
