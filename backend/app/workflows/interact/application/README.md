# Interact Application

`workflows/interact/application/` is the canonical home for API-facing Interact use cases.

## Responsibilities

- List, create, and delete chat sessions.
- List and clear chat history.
- Coordinate chat SSE streaming and persistence around the Interact workflow.

Graph internals remain in `interact/chat/` and compatibility root modules.
