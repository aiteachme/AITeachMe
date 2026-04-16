# System Support

`workflows/support/system/` is the canonical home for system-level API use cases that do not belong to a long-running engine workflow.

## Responsibilities

- Build runtime initialization payloads for the frontend.
- Combine environment/runtime infra helpers with API-facing schemas.
- Keep system business decisions out of `api/` and retired `app.services`.

## Files

- `init.py` contains the frontend runtime init entrypoint.
- `settings.py` contains settings overview and shared system data builders.
