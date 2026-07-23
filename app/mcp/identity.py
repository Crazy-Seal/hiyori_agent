from __future__ import annotations

import hashlib
import json
from typing import Any

from app.mcp.types import MCPToolDescriptor
from app.schemas.mcp import (
    MCPServerConfig,
    StdioMCPServerConfig,
    StreamableHttpMCPServerConfig,
)


def _stable_hash(value: dict[str, Any]) -> str:
    """为字典内容生成稳定的 SHA-256 摘要。

    Args:
        value: 需要序列化并计算摘要的字典。

    Returns:
        与字典键顺序无关的十六进制摘要。
    """
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def server_identity_fingerprint(config: MCPServerConfig) -> str:
    """计算 MCP 服务实现身份。

    显示名称、启用状态和超时等运行参数不属于服务身份。

    Args:
        config: 待计算身份的 MCP Server 配置。

    Returns:
        服务身份的十六进制摘要。

    Raises:
        TypeError: 配置不是受支持的 MCP Server 类型。
    """
    if isinstance(config, StdioMCPServerConfig):
        return _stable_hash({
            "transport": config.transport,
            "command": config.command,
            "args": config.args,
            "cwd": config.cwd,
            "env": config.env,
        })
    if isinstance(config, StreamableHttpMCPServerConfig):
        return _stable_hash({
            "transport": config.transport,
            "url": config.url,
            "headers": config.headers,
        })
    raise TypeError(f"不支持的 MCP 配置类型: {type(config)!r}")


def tool_contract_fingerprint(tool: MCPToolDescriptor) -> str:
    """计算用户实际看到并批准的工具契约指纹。

    Args:
        tool: MCP 工具描述符。

    Returns:
        工具名称、说明、参数结构和注解的十六进制摘要。
    """
    return _stable_hash({
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema,
        "annotations": tool.annotations,
    })
