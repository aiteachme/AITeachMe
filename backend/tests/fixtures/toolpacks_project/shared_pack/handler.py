from app.shared.infra.tools.definition import ToolDefinition


def register_toolpack():
    return [
        ToolDefinition(
            name="demo_tool",
            description="project",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            handler=lambda query: query,
            tags=["toolpack"],
        )
    ]
