from pathlib import Path

import pytest

from app.agent.agent import Agent, AgentConfig
from app.agent.context import BaseTool, ToolContext, ToolResult
from app.agent.context_strategy import ContextStrategyConfig
from app.mcp.identity import server_identity_fingerprint
from app.mcp.types import MCPToolDescriptor
from app.schemas.chat_settings import ChatSettings
from app.schemas.mcp import (
    MCPModelSettings,
    MCPServerPolicy,
    MCPServersConfig,
    MCPToolPolicy,
    StdioMCPServerConfig,
)
from app.services.mcp_connection_manager import MCPConnectionError
from app.services.mcp_policy_resolver import MCPPolicyResolver


def _chat_settings(**overrides) -> ChatSettings:
    values = {
        "session_id": "session-a",
        "model_name": "model",
        "openai_api_key": "key",
        "openai_base_url": "http://127.0.0.1:1/v1",
        "temperature": 0.1,
        "system_prompt": "prompt",
        "tools_list": [],
        "context_strategy": ContextStrategyConfig(),
    }
    values.update(overrides)
    return ChatSettings(**values)


def test_policy_resolver_reads_latest_policy_and_defaults_new_tools_to_ask() -> None:
    server = StdioMCPServerConfig(id="filesystem", name="Filesystem", command="python")
    settings = _chat_settings(
        mcp=MCPModelSettings(
            servers={
                "filesystem": MCPServerPolicy(
                    enabled=True,
                    identity_fingerprint=server_identity_fingerprint(server),
                    tools={
                        "read_file": MCPToolPolicy.ALLOW,
                        "delete_file": MCPToolPolicy.DENY,
                    },
                )
            }
        )
    )
    resolver = MCPPolicyResolver(lambda _session_id: settings)

    assert resolver.get_policy("session-a", "filesystem", "read_file") == MCPToolPolicy.ALLOW
    assert resolver.get_policy("session-a", "filesystem", "delete_file") == MCPToolPolicy.DENY
    assert resolver.get_policy("session-a", "filesystem", "new_tool") == MCPToolPolicy.ASK
    assert resolver.get_bound_identity("session-a", "filesystem") == server_identity_fingerprint(server)


@pytest.mark.parametrize("mode", ["missing", "disabled", "error"])
def test_policy_resolver_fails_closed(mode: str) -> None:
    if mode == "error":
        def loader(_session_id: str) -> ChatSettings:
            raise RuntimeError("配置读取失败")
    else:
        settings = _chat_settings(
            mcp=MCPModelSettings(
                servers={
                    "filesystem": MCPServerPolicy(enabled=mode != "disabled")
                }
                if mode != "missing"
                else {}
            )
        )
        loader = lambda _session_id: settings

    resolver = MCPPolicyResolver(loader)

    assert resolver.get_policy("session-a", "filesystem", "read_file") == MCPToolPolicy.DENY
    assert resolver.get_bound_identity("session-a", "filesystem") is None


class _ExistingTool(BaseTool):
    name = "mcp__filesystem__read_file"
    description = "existing"
    parameters_schema = {"type": "object", "properties": {}}

    async def execute(self, args: dict, context: ToolContext) -> ToolResult:
        return ToolResult.success("ok")


class _Manager:
    def __init__(self) -> None:
        self.configs = {
            "filesystem": StdioMCPServerConfig(
                id="filesystem", name="Filesystem", enabled=True, command="python"
            ),
            "broken": StdioMCPServerConfig(
                id="broken", name="Broken", enabled=True, command="python"
            ),
            "disabled": StdioMCPServerConfig(
                id="disabled", name="Disabled", enabled=False, command="python"
            ),
        }
        self.connected: list[str] = []

    def get_server_config(self, server_id: str):
        if server_id not in self.configs:
            raise MCPConnectionError(f"MCP Server '{server_id}' 不存在")
        return self.configs[server_id]

    async def connect(self, server_id: str) -> list[MCPToolDescriptor]:
        self.connected.append(server_id)
        if server_id == "broken":
            raise MCPConnectionError("连接失败")
        return [
            MCPToolDescriptor("read_file", "读取", {"type": "object"}, None),
            MCPToolDescriptor("write_file", "写入", {"type": "object"}, None),
            MCPToolDescriptor("delete_file", "删除", {"type": "object"}, None),
        ]


@pytest.mark.asyncio
async def test_agent_assembles_tools_and_isolates_server_failures(tmp_path: Path) -> None:
    manager = _Manager()
    settings = _chat_settings(
        mcp=MCPModelSettings(
            servers={
                "filesystem": MCPServerPolicy(
                    enabled=True,
                    tools={
                        "read_file": MCPToolPolicy.ALLOW,
                        "write_file": MCPToolPolicy.ASK,
                        "delete_file": MCPToolPolicy.DENY,
                    },
                ),
                "broken": MCPServerPolicy(enabled=True),
                "disabled": MCPServerPolicy(enabled=True),
            }
        )
    )
    resolver = MCPPolicyResolver(lambda _session_id: settings)
    agent = Agent(
        AgentConfig(
            session_id=settings.session_id,
            model_name=settings.model_name,
            api_key=settings.openai_api_key,
            context_strategy=settings.context_strategy,
            mcp=settings.mcp,
        ),
        db_path=str(tmp_path / "state.sqlite3"),
        mcp_connection_manager=manager,
        mcp_policy_resolver=resolver,
    )
    agent.tool_manager.register(_ExistingTool())

    await agent.initialize()

    assert manager.connected == ["filesystem", "broken"]
    assert agent.tool_manager.get("mcp__filesystem__read_file").description == "existing"
    assert agent.tool_manager.has("mcp__filesystem__write_file")
    assert not agent.tool_manager.has("mcp__filesystem__delete_file")
    assert agent.tool_manager.get("mcp__filesystem__write_file").is_resumable is True
    await agent.close()


def test_connection_manager_public_surface_has_no_session_policy_methods() -> None:
    from app.services.mcp_connection_manager import MCPConnectionManager

    assert not hasattr(MCPConnectionManager, "create_tool_adapters")
    assert not hasattr(MCPConnectionManager, "get_current_policy")
    assert not hasattr(MCPConnectionManager, "validate_policy_identity")
