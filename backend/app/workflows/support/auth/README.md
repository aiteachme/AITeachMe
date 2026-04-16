# Auth Support

`workflows/support/auth/` is the canonical home for authentication use cases.

## Responsibilities

- Create and resolve guest users.
- Register and login email/password users.
- Issue and decode access/guest tokens.
- Send email verification codes.
- Build API-facing auth session payloads.

## Notes

- This is a support module, not a LangGraph lane.
- API routes and dependencies import public functions from `app.workflows.support.auth`.
- `identity.py`, `sessions.py`, and `smtp.py` are the canonical use-case entrypoints.
