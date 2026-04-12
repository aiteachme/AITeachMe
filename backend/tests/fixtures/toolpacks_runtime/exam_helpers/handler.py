from app.shared.infra.tools.definition import ToolDefinition


def register_toolpack():
    return [
        ToolDefinition(
            name="summarize_question",
            description="toolpack tool",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            handler=lambda query: query,
            tags=["toolpack"],
        )
    ]
