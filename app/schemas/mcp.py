from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator


SERVER_ID_PATTERN = r"^[A-Za-z0-9_-]{1,32}$"


class MCPToolPolicy(str, Enum):
    """定义模型调用 MCP 工具时采用的授权策略。"""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class MCPServerPolicy(BaseModel):
    """描述单个模型对一个 MCP Server 的使用权限。"""

    enabled: bool = False
    tools: dict[str, MCPToolPolicy] = Field(default_factory=dict)
    identity_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("tools")
    @classmethod
    def validate_tool_names(cls, value: dict[str, MCPToolPolicy]) -> dict[str, MCPToolPolicy]:
        """校验工具权限映射中的名称均非空白。

        Args:
            value: 工具名称到授权策略的映射。

        Returns:
            校验通过的原映射。

        Raises:
            ValueError: 任一工具名称为空白。
        """
        if any(not name.strip() for name in value):
            raise ValueError("MCP 工具名称不能为空")
        return value


class MCPModelSettings(BaseModel):
    """保存单个模型的 MCP Server 权限集合。"""

    servers: dict[str, MCPServerPolicy] = Field(default_factory=dict)

    @field_validator("servers")
    @classmethod
    def validate_server_ids(cls, value: dict[str, MCPServerPolicy]) -> dict[str, MCPServerPolicy]:
        """校验模型权限中引用的 MCP Server ID。

        Args:
            value: Server ID 到模型级权限的映射。

        Returns:
            校验通过的原映射。

        Raises:
            ValueError: 任一 Server ID 不符合命名规则。
        """
        import re

        if any(re.fullmatch(SERVER_ID_PATTERN, server_id) is None for server_id in value):
            raise ValueError("MCP server_id 只能包含字母、数字、下划线和连字符，最长 32 位")
        return value


class MCPServerConfigBase(BaseModel):
    """定义所有 MCP Server 配置共享的字段。"""

    id: str = Field(pattern=SERVER_ID_PATTERN)
    name: str = Field(min_length=1, max_length=100)
    enabled: bool = False
    connect_timeout_seconds: float = Field(default=15, gt=0, le=300)
    call_timeout_seconds: float = Field(default=60, gt=0, le=3600)


class StdioMCPServerConfig(MCPServerConfigBase):
    """定义通过本地标准输入输出连接的 MCP Server。"""

    transport: Literal["stdio"] = "stdio"
    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)

    @field_validator("env")
    @classmethod
    def validate_env(cls, value: dict[str, str]) -> dict[str, str]:
        """禁止 MCP 子进程覆盖桌面后端运行控制变量。

        Args:
            value: 用户为该 Server 显式配置的环境变量。

        Returns:
            校验通过的环境变量映射。

        Raises:
            ValueError: 配置中包含禁止传递的运行控制变量。
        """
        forbidden = {"AYAYA_API_TOKEN", "AYAYA_PARENT_PID"}
        configured = {key.upper() for key in value}
        invalid = sorted(configured & forbidden)
        if invalid:
            raise ValueError(
                f"MCP Server env 不允许配置应用运行控制变量: {', '.join(invalid)}"
            )
        return value


class StreamableHttpMCPServerConfig(MCPServerConfigBase):
    """定义通过 Streamable HTTP 连接的 MCP Server。"""

    transport: Literal["streamable_http"] = "streamable_http"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        """校验并规范化 Streamable HTTP Endpoint。

        Args:
            value: 用户提供的 Endpoint URL。

        Returns:
            去除首尾空白后的 URL。

        Raises:
            ValueError: URL 非 HTTP(S) 地址或包含用户凭据。
        """
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("MCP URL 必须是有效的 HTTP 或 HTTPS 地址")
        if parsed.username or parsed.password:
            raise ValueError("MCP URL 不允许包含用户信息")
        return value.strip()


MCPServerConfig = Annotated[
    StdioMCPServerConfig | StreamableHttpMCPServerConfig,
    Field(discriminator="transport"),
]


class MCPServersConfig(BaseModel):
    """表示本地配置中的全部 MCP Server。"""

    servers: list[MCPServerConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "MCPServersConfig":
        """校验 MCP Server ID 在配置中唯一。

        Returns:
            校验通过的当前配置对象。

        Raises:
            ValueError: 配置中存在重复的 Server ID。
        """
        ids = [server.id for server in self.servers]
        if len(ids) != len(set(ids)):
            raise ValueError("MCP server_id 不能重复")
        return self
