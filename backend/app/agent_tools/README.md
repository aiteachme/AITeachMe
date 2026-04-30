# Agent Tools

`app.agent_tools` is the project-owned entrypoint for tools that an LLM may
call. Files in this package adapt model-visible tool calls to existing
workflows and shared infrastructure.

Directory rules:

- `global_scope/` contains tools that are not bound to one course, such as
  user confirmation, course management, skill management, planning state, and
  user memory writes.
- `course_scope/` contains tools that operate on the active course.
- `query_scope/` contains read/query tools such as knowledge search, web
  search, and memory recall.
- `authoring_scope/` is reserved for content-analysis and authoring tools.

Keep real business logic in `workflows/` or `shared/infra/**`. Tool files in
this package should define the LLM-facing name, description, schema, risk
metadata, hidden context arguments, and the call into the underlying
implementation.
