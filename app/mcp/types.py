from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MCPToolDescriptor:
    """描述 MCP Server 暴露的单个工具契约。

    Attributes:
        name: MCP Server 中的原始工具名称。
        description: 提供给模型的工具说明。
        input_schema: 工具参数的 JSON Schema。
        annotations: MCP 协议附带的工具注解。
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    annotations: dict[str, Any] = field(default_factory=dict)
