# Shared Layer

`app/shared` is the stable foundation layer for module-level code.

## Structure

- `kernel/`: pure domain/kernel primitives (time, ids, base events, base exceptions entrypoint)
- `infra/`: infrastructure entrypoints (config, db, logging, llm, embedding, cache)

## Current migration mode

This is a compatibility-first phase:

- `app/shared/*` is introduced as the new canonical import path.
- Most implementations still proxy existing `app/infra/*` and `app/utils/*`.
- Existing imports in legacy modules continue to work.

## Dependency rule

- Business modules should prefer importing shared foundations from `app.shared.*`.
- Cross-module business logic should not import other modules' infrastructure directly.

