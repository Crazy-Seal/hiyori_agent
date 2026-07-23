"""MCP 连接层与 Agent 适配层共享的基础定义。"""

from app.mcp.identity import server_identity_fingerprint, tool_contract_fingerprint
from app.mcp.types import MCPToolDescriptor

__all__ = [
    "MCPToolDescriptor",
    "server_identity_fingerprint",
    "tool_contract_fingerprint",
]
