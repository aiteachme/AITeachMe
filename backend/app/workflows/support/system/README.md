# System Support

`workflows/support/system/` is the canonical home for system-level API use cases that do not belong to a long-running engine workflow.

## Responsibilities

- Build runtime initialization payloads for the frontend.
- Combine environment/runtime infra helpers with API-facing schemas.
- Keep system business decisions out of `api/` and retired `app.services`.

## Files

- `queries.py` contains read-oriented use cases.
- `commands.py` may be added later if system write operations appear.
