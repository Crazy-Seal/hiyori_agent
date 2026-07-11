from typing import Annotated, Literal

from app.agent.tools.decorator import tool


def test_tool_schema_includes_signature_defaults() -> None:
    @tool
    async def sample_tool(
        required_text: Annotated[str, "required text"],
        mode: Annotated[Literal["fast", "slow"], "mode"] = "fast",
        count: Annotated[int, "count"] = 3,
        enabled: Annotated[bool, "enabled"] = False,
        note: Annotated[str, "note"] = "",
    ) -> str:
        return required_text

    schema = sample_tool.parameters_schema

    assert schema["required"] == ["required_text"]
    assert "default" not in schema["properties"]["required_text"]
    assert schema["properties"]["mode"]["default"] == "fast"
    assert schema["properties"]["count"]["default"] == 3
    assert schema["properties"]["enabled"]["default"] is False
    assert schema["properties"]["note"]["default"] == ""


def test_explicit_parameters_schema_is_not_modified() -> None:
    explicit_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "name",
            },
        },
    }

    @tool(parameters_schema=explicit_schema)
    async def explicit_schema_tool(name: Annotated[str, "name"] = "demo") -> str:
        return name

    assert explicit_schema_tool.parameters_schema is explicit_schema
    assert "default" not in explicit_schema_tool.parameters_schema["properties"]["name"]
