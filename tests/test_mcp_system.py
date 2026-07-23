from pathlib import Path
from contextlib import asynccontextmanager
from types import SimpleNamespace

import anyio
import httpx
import pytest
from mcp.shared.exceptions import McpError
from mcp.types import CONNECTION_CLOSED, INVALID_PARAMS, ErrorData
from pydantic import BaseModel, ValidationError

from app.agent.context_strategy import ContextStrategyConfig
from app.agent.agent import Agent, AgentConfig
from app.agent.context import BaseTool, ToolContext, ToolResult
from app.agent.core.event_router import AgentEvent, EventType
from app.agent.state import AgentState
from app.agent.mcp.adapter import MCPToolAdapter, build_exposed_tool_name
from app.mcp.identity import server_identity_fingerprint, tool_contract_fingerprint
from app.mcp.types import MCPToolDescriptor
from app.crud.mcp_settings_dao import MCPSettingsDao
from app.crud.chat_settings_dao import ChatSettingsDao
from app.services.mcp_connection_manager import (
    MCPConnectionError,
    MCPConnectionManager,
    MCPServerDisabledError,
)
from app.services.mcp_service import MCPService
from app.services.chat_settings_service import ChatSettingsService
from app.services.settings_mutation import SettingsMutationCoordinator
from app.services.agent_service import AgentService
from app.schemas.chat_settings import ChatSettings
from app.schemas.mcp import (
    MCPModelSettings,
    MCPServerPolicy,
    MCPServersConfig,
    MCPToolPolicy,
    StdioMCPServerConfig,
    StreamableHttpMCPServerConfig,
)


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


def test_mcp_server_config_supports_stdio_and_streamable_http() -> None:
    config = MCPServersConfig(
        servers=[
            {
                "id": "filesystem",
                "name": "Filesystem",
                "enabled": True,
                "transport": "stdio",
                "command": "npx",
                "args": ["-y", "server-filesystem"],
                "cwd": "E:/workspace",
                "env": {"TOKEN": "plain-secret"},
            },
            {
                "id": "remote-search",
                "name": "Remote Search",
                "enabled": True,
                "transport": "streamable_http",
                "url": "https://example.com/mcp",
                "headers": {"Authorization": "Bearer plain-secret"},
            },
        ]
    )

    assert isinstance(config.servers[0], StdioMCPServerConfig)
    assert isinstance(config.servers[1], StreamableHttpMCPServerConfig)
    assert config.servers[0].connect_timeout_seconds == 15
    assert config.servers[1].call_timeout_seconds == 60


@pytest.mark.parametrize("server_id", ["", "contains space", "a" * 33])
def test_mcp_server_id_is_stable_model_tool_name_component(server_id: str) -> None:
    with pytest.raises(ValidationError):
        StdioMCPServerConfig(
            id=server_id,
            name="Invalid",
            transport="stdio",
            command="python",
        )


def test_mcp_settings_dao_round_trips_plaintext_credentials(tmp_path: Path) -> None:
    config_file = tmp_path / "config" / "mcp_servers.yaml"
    dao = MCPSettingsDao(config_file=config_file)
    saved = MCPServersConfig(
        servers=[
            StdioMCPServerConfig(
                id="github",
                name="GitHub",
                transport="stdio",
                command="npx",
                env={"GITHUB_TOKEN": "plain-secret"},
            )
        ]
    )

    dao.save(saved)
    loaded = MCPSettingsDao(config_file=config_file).load()

    assert loaded == saved
    assert "plain-secret" in config_file.read_text(encoding="utf-8")
    assert not config_file.with_suffix(".yaml.tmp").exists()


def test_mcp_error_sanitization_removes_headers_and_url_query() -> None:
    config = StreamableHttpMCPServerConfig(
        id="remote",
        name="Remote",
        url="http://example.test/mcp?token=query-secret",
        headers={"Authorization": "Bearer header-secret"},
    )
    sanitized = MCPConnectionManager._sanitize_error(
        config,
        RuntimeError(
            "failed http://example.test/mcp?token=query-secret with Bearer header-secret"
        ),
    )

    assert "query-secret" not in sanitized
    assert "header-secret" not in sanitized
    assert "http://example.test/mcp" in sanitized


def test_chat_settings_defaults_to_no_mcp_access() -> None:
    settings = _chat_settings()

    assert settings.mcp == MCPModelSettings()
    assert settings.mcp.servers == {}


def test_legacy_chat_settings_yaml_without_mcp_remains_compatible(tmp_path: Path) -> None:
    config_file = tmp_path / "chat_settings.yaml"
    settings = _chat_settings().model_dump(mode="json")
    settings.pop("mcp")
    import yaml

    config_file.write_text(
        yaml.safe_dump({"chat_models": [settings]}, allow_unicode=True),
        encoding="utf-8",
    )

    loaded = ChatSettingsDao(config_file).get_chat_settings("session-a")

    assert loaded.mcp.servers == {}


def test_chat_settings_round_trips_per_model_mcp_policies() -> None:
    settings = _chat_settings(
        mcp={
            "servers": {
                "filesystem": {
                    "enabled": True,
                    "tools": {
                        "read_file": "allow",
                        "write_file": "ask",
                        "delete_file": "deny",
                    },
                }
            }
        }
    )

    policy = settings.mcp.servers["filesystem"]
    assert policy == MCPServerPolicy(
        enabled=True,
        tools={
            "read_file": MCPToolPolicy.ALLOW,
            "write_file": MCPToolPolicy.ASK,
            "delete_file": MCPToolPolicy.DENY,
        },
    )
    assert ChatSettings.model_validate(settings.model_dump()).mcp == settings.mcp


def test_mcp_tool_alias_is_namespaced_stable_and_model_safe() -> None:
    short = build_exposed_tool_name("filesystem", "read_file")
    long = build_exposed_tool_name("remote", "包含空格/" + "x" * 100)

    assert short == "mcp__filesystem__read_file"
    assert len(long) <= 64
    assert long == build_exposed_tool_name("remote", "包含空格/" + "x" * 100)
    assert all(character.isalnum() or character in "_-" for character in long)


class _FakeSession:
    def __init__(self) -> None:
        self.initialize_count = 0
        self.calls: list[tuple[str, dict]] = []

    async def initialize(self):
        self.initialize_count += 1
        return SimpleNamespace(instructions="仅用于诊断")

    async def list_tools(self):
        return SimpleNamespace(
            tools=[
                SimpleNamespace(
                    name="read_file",
                    description="读取文件",
                    inputSchema={"type": "object", "properties": {"path": {"type": "string"}}},
                    annotations=None,
                ),
                SimpleNamespace(
                    name="write_file",
                    description="写入文件",
                    inputSchema={"type": "object", "properties": {}},
                    annotations=None,
                ),
                SimpleNamespace(
                    name="new_tool",
                    description="新增工具",
                    inputSchema={"type": "object", "properties": {}},
                    annotations=None,
                ),
            ]
        )

    async def call_tool(self, name: str, arguments: dict):
        self.calls.append((name, arguments))
        return SimpleNamespace(
            isError=False,
            structuredContent={"ok": True},
            content=[
                SimpleNamespace(type="text", text="完成"),
                SimpleNamespace(type="image", data="iVBORw0KGgo=", mimeType="image/png"),
            ],
        )


@pytest.mark.asyncio
async def test_connection_manager_reuses_connection_and_returns_raw_tool_catalog() -> None:
    session = _FakeSession()
    closed = 0

    @asynccontextmanager
    async def session_factory(_config):
        nonlocal closed
        try:
            yield session
        finally:
            closed += 1

    config = MCPServersConfig(
        servers=[
            StdioMCPServerConfig(
                id="filesystem",
                name="Filesystem",
                enabled=True,
                transport="stdio",
                command="python",
            )
        ]
    )
    manager = MCPConnectionManager(lambda: config, session_factory=session_factory)
    first = await manager.connect("filesystem")
    second = await manager.connect("filesystem")

    assert [tool.name for tool in first] == ["read_file", "write_file", "new_tool"]
    assert [tool.name for tool in second] == ["read_file", "write_file", "new_tool"]
    assert session.initialize_count == 1
    await manager.close()
    assert closed == 1


@pytest.mark.asyncio
async def test_connection_manager_allows_concurrent_calls_per_server() -> None:
    import asyncio

    class _SerialSession(_FakeSession):
        active = 0
        max_active = 0

        async def call_tool(self, name: str, arguments: dict):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            try:
                await asyncio.sleep(0.01)
                return await super().call_tool(name, arguments)
            finally:
                self.active -= 1

    session = _SerialSession()

    @asynccontextmanager
    async def session_factory(_config):
        yield session

    config = MCPServersConfig(servers=[StdioMCPServerConfig(
        id="serial", name="Serial", enabled=True, command="python"
    )])
    manager = MCPConnectionManager(lambda: config, session_factory=session_factory)
    await manager.connect("serial")

    await asyncio.gather(
        manager.call_tool("serial", "read_file", {"index": 1}),
        manager.call_tool("serial", "read_file", {"index": 2}),
    )

    assert session.max_active == 2
    await manager.close()


@pytest.mark.asyncio
async def test_unknown_call_error_keeps_generation_for_next_call() -> None:
    close_order: list[int] = []
    session = _FakeSession()
    original_call = session.call_tool
    failed = False

    async def fail_once(name: str, arguments: dict):
        nonlocal failed
        if not failed:
            failed = True
            session.calls.append((name, arguments))
            raise RuntimeError("unknown call failure with plain-secret")
        return await original_call(name, arguments)

    session.call_tool = fail_once
    created = 0

    @asynccontextmanager
    async def session_factory(_config):
        nonlocal created
        current = created
        created += 1
        try:
            yield session
        finally:
            close_order.append(current)

    config = MCPServersConfig(servers=[StdioMCPServerConfig(
        id="lifecycle",
        name="Lifecycle",
        enabled=True,
        command="python",
        env={"TOKEN": "plain-secret"},
    )])
    manager = MCPConnectionManager(lambda: config, session_factory=session_factory)

    with pytest.raises(Exception, match="未自动重试") as error:
        await manager.call_tool("lifecycle", "read_file", {})
    assert "plain-secret" not in str(error.value)
    assert close_order == []
    assert manager.get_status("lifecycle")["status"] == "available"
    assert manager.get_status("lifecycle")["last_error"] is None

    result = await manager.call_tool("lifecycle", "read_file", {})
    assert result.isError is False
    assert created == 1
    await manager.close()
    assert close_order == [0]


class _InvalidCallResult(BaseModel):
    value: int


def _validation_error() -> ValidationError:
    with pytest.raises(ValidationError) as raised:
        _InvalidCallResult(value="invalid")
    return raised.value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        McpError(ErrorData(code=INVALID_PARAMS, message="参数不合法")),
        RuntimeError("Invalid structured content returned by tool read_file"),
        _validation_error(),
        ValueError("本地参数错误"),
        httpx.ReadTimeout("调用超时"),
        ExceptionGroup("unknown", [RuntimeError("未知异常")]),
    ],
    ids=[
        "mcp-request-error",
        "output-schema-error",
        "response-validation-error",
        "local-value-error",
        "httpx-timeout",
        "unknown-exception-group",
    ],
)
async def test_nonfatal_call_errors_keep_generation(failure: Exception) -> None:
    session = _FakeSession()
    original_call = session.call_tool
    failed = False
    closed = 0

    async def fail_once(name: str, arguments: dict):
        nonlocal failed
        if not failed:
            failed = True
            raise failure
        return await original_call(name, arguments)

    session.call_tool = fail_once

    @asynccontextmanager
    async def session_factory(_config):
        nonlocal closed
        try:
            yield session
        finally:
            closed += 1

    config = MCPServersConfig(servers=[StdioMCPServerConfig(
        id="nonfatal", name="Nonfatal", enabled=True, command="python"
    )])
    manager = MCPConnectionManager(lambda: config, session_factory=session_factory)

    with pytest.raises(MCPConnectionError, match="未自动重试"):
        await manager.call_tool("nonfatal", "read_file", {})

    assert closed == 0
    assert manager.get_status("nonfatal")["status"] == "available"
    assert manager.get_status("nonfatal")["last_error"] is None
    assert (await manager.call_tool("nonfatal", "read_file", {})).isError is False
    await manager.close()
    assert closed == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        McpError(ErrorData(code=CONNECTION_CLOSED, message="连接已关闭")),
        anyio.ClosedResourceError(),
        anyio.BrokenResourceError(),
        anyio.EndOfStream(),
        httpx.ReadError("读取连接失败"),
        ConnectionResetError("连接被重置"),
        EOFError("连接已结束"),
        ExceptionGroup("transport", [RuntimeError("上下文"), EOFError("连接已结束")]),
    ],
    ids=[
        "mcp-connection-closed",
        "anyio-closed-resource",
        "anyio-broken-resource",
        "anyio-end-of-stream",
        "httpx-read-error",
        "connection-reset",
        "eof",
        "fatal-exception-group",
    ],
)
async def test_fatal_call_errors_retire_generation(failure: Exception) -> None:
    sessions = [_FakeSession(), _FakeSession()]
    original_call = sessions[0].call_tool
    closed: list[int] = []
    created = 0
    failed = False

    async def fail_once(name: str, arguments: dict):
        nonlocal failed
        if not failed:
            failed = True
            raise failure
        return await original_call(name, arguments)

    sessions[0].call_tool = fail_once

    @asynccontextmanager
    async def session_factory(_config):
        nonlocal created
        index = created
        created += 1
        try:
            yield sessions[index]
        finally:
            closed.append(index)

    config = MCPServersConfig(servers=[StdioMCPServerConfig(
        id="fatal", name="Fatal", enabled=True, command="python"
    )])
    manager = MCPConnectionManager(lambda: config, session_factory=session_factory)

    with pytest.raises(MCPConnectionError, match="未自动重试"):
        await manager.call_tool("fatal", "read_file", {})

    assert closed == [0]
    assert manager.get_status("fatal")["status"] == "error"
    assert (await manager.call_tool("fatal", "read_file", {})).isError is False
    assert created == 2
    await manager.close()
    assert closed == [0, 1]


@pytest.mark.asyncio
async def test_one_failed_concurrent_call_does_not_cancel_other_inflight_call() -> None:
    import asyncio

    release_success = asyncio.Event()
    success_started = asyncio.Event()
    closed = 0

    class _ConcurrentSession(_FakeSession):
        async def call_tool(self, name: str, arguments: dict):
            if arguments["kind"] == "fail":
                await success_started.wait()
                raise ConnectionResetError("transport failed")
            success_started.set()
            await release_success.wait()
            return await super().call_tool(name, arguments)

    session = _ConcurrentSession()

    @asynccontextmanager
    async def session_factory(_config):
        nonlocal closed
        try:
            yield session
        finally:
            closed += 1

    config = MCPServersConfig(servers=[StdioMCPServerConfig(
        id="concurrent", name="Concurrent", enabled=True, command="python"
    )])
    manager = MCPConnectionManager(lambda: config, session_factory=session_factory)
    await manager.connect("concurrent")

    success_task = asyncio.create_task(
        manager.call_tool("concurrent", "read_file", {"kind": "success"})
    )
    failure_task = asyncio.create_task(
        manager.call_tool("concurrent", "read_file", {"kind": "fail"})
    )
    await success_started.wait()
    await asyncio.sleep(0)
    assert not success_task.done()
    release_success.set()

    success = await success_task
    assert success.isError is False
    with pytest.raises(MCPConnectionError, match="未自动重试"):
        await failure_task
    assert closed == 1


def _tool_context(
    resume_data: dict | None = None,
    resume_state: dict | None = None,
) -> ToolContext:
    return ToolContext(
        session_id="session-a",
        state=SimpleNamespace(),
        emit_event=lambda *_args: None,
        get_checkpoint=lambda: {},
        set_checkpoint=lambda _data: None,
        resume_data=resume_data,
        resume_state=resume_state,
    )


class _MutablePolicyResolver:
    """为 Adapter 安全测试提供可变的实时权限与身份。"""

    def __init__(self, policy: MCPToolPolicy, identity: str | None) -> None:
        self.policy = policy
        self.identity = identity

    def get_policy(self, _session_id: str, _server_id: str, _tool_name: str) -> MCPToolPolicy:
        return self.policy

    def get_bound_identity(self, _session_id: str, _server_id: str) -> str | None:
        return self.identity


@pytest.mark.asyncio
async def test_ask_adapter_requires_single_approval_and_converts_results() -> None:
    session = _FakeSession()

    @asynccontextmanager
    async def session_factory(_config):
        yield session

    config = MCPServersConfig(
        servers=[
            StdioMCPServerConfig(
                id="filesystem",
                name="Filesystem",
                enabled=True,
                transport="stdio",
                command="python",
            )
        ]
    )
    manager = MCPConnectionManager(lambda: config, session_factory=session_factory)
    await manager.connect("filesystem")
    descriptor = manager.get_tools("filesystem")[1]
    resolver = _MutablePolicyResolver(
        MCPToolPolicy.ASK,
        server_identity_fingerprint(config.servers[0]),
    )
    adapter = MCPToolAdapter(
        session_id="session-a",
        server_id="filesystem",
        server_name="Filesystem",
        descriptor=descriptor,
        policy=MCPToolPolicy.ASK,
        connection_manager=manager,
        policy_resolver=resolver,
    )

    pending = await adapter.execute({"path": "README.md"}, _tool_context())
    assert pending.interrupt is not None
    assert pending.interrupt.type == "mcp_tool_approval_request"
    assert session.calls == []

    denied = await adapter.execute({"path": "README.md"}, _tool_context({"approved": False}))
    assert "拒绝" in denied.content
    assert session.calls == []

    approved = await adapter.execute(
        {"path": "README.md"},
        _tool_context({"approved": True}, pending.resume_state),
    )
    assert "完成" in approved.content
    assert '"ok": true' in approved.content
    assert approved.image_urls == ["data:image/png;base64,iVBORw0KGgo="]
    assert session.calls == [("write_file", {"path": "README.md"})]
    await manager.close()


@pytest.mark.asyncio
async def test_rejected_resume_is_absolute_even_if_policy_changed_to_allow() -> None:
    session = _FakeSession()
    resolver = _MutablePolicyResolver(MCPToolPolicy.ASK, None)

    @asynccontextmanager
    async def session_factory(_config):
        yield session

    config = MCPServersConfig(servers=[StdioMCPServerConfig(
        id="filesystem", name="Filesystem", enabled=True, command="python"
    )])
    manager = MCPConnectionManager(lambda: config, session_factory=session_factory)
    resolver.identity = server_identity_fingerprint(config.servers[0])
    await manager.connect("filesystem")
    descriptor = manager.get_tools("filesystem")[0]
    adapter = MCPToolAdapter(
        session_id="session-a",
        server_id="filesystem",
        server_name="Filesystem",
        descriptor=descriptor,
        policy=MCPToolPolicy.ASK,
        connection_manager=manager,
        policy_resolver=resolver,
    )
    pending = await adapter.execute({}, _tool_context())
    resolver.policy = MCPToolPolicy.ALLOW

    denied = await adapter.execute(
        {},
        _tool_context({"approved": False}, pending.resume_state),
    )

    assert "拒绝" in denied.content
    assert session.calls == []
    await manager.close()


@pytest.mark.asyncio
async def test_approved_resume_rejects_changed_server_or_tool_contract() -> None:
    session = _FakeSession()

    @asynccontextmanager
    async def session_factory(_config):
        yield session

    config = MCPServersConfig(servers=[StdioMCPServerConfig(
        id="filesystem", name="Filesystem", enabled=True, command="python"
    )])
    manager = MCPConnectionManager(lambda: config, session_factory=session_factory)
    await manager.connect("filesystem")
    descriptor = manager.get_tools("filesystem")[0]
    resolver = _MutablePolicyResolver(
        MCPToolPolicy.ASK,
        server_identity_fingerprint(config.servers[0]),
    )
    adapter = MCPToolAdapter(
        session_id="session-a",
        server_id="filesystem",
        server_name="Filesystem",
        descriptor=descriptor,
        policy=MCPToolPolicy.ASK,
        connection_manager=manager,
        policy_resolver=resolver,
    )
    pending = await adapter.execute({}, _tool_context())

    stale_server = dict(pending.resume_state)
    stale_server["server_identity_fingerprint"] = "old-server"
    server_result = await adapter.execute(
        {}, _tool_context({"approved": True}, stale_server)
    )
    stale_tool = dict(pending.resume_state)
    stale_tool["tool_contract_fingerprint"] = "old-tool"
    tool_result = await adapter.execute(
        {}, _tool_context({"approved": True}, stale_tool)
    )
    arguments_result = await adapter.execute(
        {"path": "changed"},
        _tool_context({"approved": True}, pending.resume_state),
    )

    assert "MCP_APPROVAL_STALE" in server_result.content
    assert "MCP_APPROVAL_STALE" in tool_result.content
    assert "MCP_APPROVAL_STALE" in arguments_result.content
    assert session.calls == []
    await manager.close()


def test_identity_fingerprints_only_cover_identity_and_tool_contract() -> None:
    base = StdioMCPServerConfig(
        id="filesystem",
        name="Filesystem",
        enabled=True,
        command="python",
        args=["server.py"],
        env={"TOKEN": "secret", "MODE": "local"},
    )
    renamed = base.model_copy(update={
        "name": "Renamed",
        "enabled": False,
        "connect_timeout_seconds": 30,
        "call_timeout_seconds": 120,
    })
    changed = base.model_copy(update={"args": ["other.py"]})
    descriptor = MCPToolDescriptor(
        name="read_file",
        description="读取文件",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        annotations={"readOnlyHint": True},
    )

    assert server_identity_fingerprint(base) == server_identity_fingerprint(renamed)
    assert server_identity_fingerprint(base) != server_identity_fingerprint(changed)
    assert tool_contract_fingerprint(descriptor) != tool_contract_fingerprint(
        MCPToolDescriptor(
            name=descriptor.name,
            description="新的描述",
            input_schema=descriptor.input_schema,
            annotations=descriptor.annotations,
        )
    )


@pytest.mark.asyncio
async def test_adapter_rechecks_current_policy_before_execution() -> None:
    session = _FakeSession()
    resolver = _MutablePolicyResolver(MCPToolPolicy.ALLOW, None)

    @asynccontextmanager
    async def session_factory(_config):
        yield session

    config = MCPServersConfig(servers=[StdioMCPServerConfig(
        id="filesystem", name="Filesystem", enabled=True, command="python"
    )])
    manager = MCPConnectionManager(lambda: config, session_factory=session_factory)
    resolver.identity = server_identity_fingerprint(config.servers[0])
    await manager.connect("filesystem")
    adapter = MCPToolAdapter(
        session_id="session-a",
        server_id="filesystem",
        server_name="Filesystem",
        descriptor=manager.get_tools("filesystem")[0],
        policy=MCPToolPolicy.ALLOW,
        connection_manager=manager,
        policy_resolver=resolver,
    )

    resolver.policy = MCPToolPolicy.DENY
    result = await adapter.execute({}, _tool_context())

    assert "不允许使用" in result.content
    assert session.calls == []
    await manager.close()


@pytest.mark.asyncio
async def test_adapter_rechecks_policy_inside_connection_lease() -> None:
    session = _FakeSession()
    resolver = _MutablePolicyResolver(MCPToolPolicy.ALLOW, None)

    @asynccontextmanager
    async def session_factory(_config):
        yield session

    config = MCPServersConfig(servers=[StdioMCPServerConfig(
        id="filesystem", name="Filesystem", enabled=True, command="python"
    )])

    class _PolicyChangingManager(MCPConnectionManager):
        async def call_tool(self, *args, **kwargs):
            resolver.policy = MCPToolPolicy.DENY
            return await super().call_tool(*args, **kwargs)

    manager = _PolicyChangingManager(lambda: config, session_factory=session_factory)
    resolver.identity = server_identity_fingerprint(config.servers[0])
    await manager.connect("filesystem")
    adapter = MCPToolAdapter(
        session_id="session-a",
        server_id="filesystem",
        server_name="Filesystem",
        descriptor=manager.get_tools("filesystem")[0],
        policy=MCPToolPolicy.ALLOW,
        connection_manager=manager,
        policy_resolver=resolver,
    )

    result = await adapter.execute({}, _tool_context())

    assert "未获准" in result.content
    assert session.calls == []
    assert manager.get_status("filesystem")["status"] == "available"
    await manager.close()


@pytest.mark.asyncio
async def test_adapter_rejects_changed_policy_binding_identity() -> None:
    session = _FakeSession()

    @asynccontextmanager
    async def session_factory(_config):
        yield session

    config = MCPServersConfig(servers=[StdioMCPServerConfig(
        id="filesystem", name="Filesystem", enabled=True, command="python"
    )])
    manager = MCPConnectionManager(lambda: config, session_factory=session_factory)
    await manager.connect("filesystem")
    resolver = _MutablePolicyResolver(MCPToolPolicy.ALLOW, "旧身份")
    adapter = MCPToolAdapter(
        session_id="session-a",
        server_id="filesystem",
        server_name="Filesystem",
        descriptor=manager.get_tools("filesystem")[0],
        policy=MCPToolPolicy.ALLOW,
        connection_manager=manager,
        policy_resolver=resolver,
    )

    result = await adapter.execute({}, _tool_context())

    assert "MCP_IDENTITY_UNBOUND" in result.content
    assert session.calls == []
    await manager.close()


@pytest.mark.asyncio
async def test_call_timeout_is_not_replayed_keeps_generation_and_redacts_secret() -> None:
    class _SlowSession(_FakeSession):
        timed_out = False

        async def call_tool(self, name: str, arguments: dict):
            self.calls.append((name, arguments))
            if not self.timed_out:
                self.timed_out = True
                await __import__("asyncio").sleep(0.05)
            return await super().call_tool(name, arguments)

    session = _SlowSession()
    closed = 0

    @asynccontextmanager
    async def session_factory(_config):
        nonlocal closed
        try:
            yield session
        finally:
            closed += 1

    config = MCPServersConfig(servers=[StdioMCPServerConfig(
        id="slow",
        name="Slow",
        enabled=True,
        command="python",
        call_timeout_seconds=0.01,
        env={"TOKEN": "plain-secret"},
    )])
    manager = MCPConnectionManager(lambda: config, session_factory=session_factory)
    await manager.connect("slow")

    with pytest.raises(Exception, match="未自动重试") as error:
        await manager.call_tool("slow", "read_file", {"token": "plain-secret"})

    assert len(session.calls) == 1
    assert "plain-secret" not in str(error.value)
    assert closed == 0
    assert manager.get_status("slow")["status"] == "available"
    assert manager.get_status("slow")["last_error"] is None
    result = await manager.call_tool("slow", "read_file", {"token": "plain-secret"})
    assert result.isError is False
    assert len(session.calls) == 3
    await manager.close()
    assert closed == 1


def test_adapter_converts_errors_multiple_images_unsupported_content_and_truncation() -> None:
    error = MCPToolAdapter._convert_result(SimpleNamespace(
        isError=True,
        content=[SimpleNamespace(type="text", text="remote failed")],
    ))
    assert "remote failed" in error.content

    converted = MCPToolAdapter._convert_result(SimpleNamespace(
        isError=False,
        structuredContent={"large": "x" * 60_000},
        content=[
            SimpleNamespace(type="image", data="iVBORw0KGgo=", mimeType="image/png"),
            SimpleNamespace(type="image", data="/9j/", mimeType="image/jpeg"),
            SimpleNamespace(type="audio"),
            SimpleNamespace(type="resource_link"),
            SimpleNamespace(type="resource"),
        ],
    ))
    assert converted.image_urls == [
        "data:image/png;base64,iVBORw0KGgo=",
        "data:image/jpeg;base64,/9j/",
    ]
    assert converted.image_message_name == "mcp_tool_image"
    assert "已忽略 3 个不支持的 MCP 内容类型" in converted.content
    assert "结果已截断" in converted.content
    assert len(converted.content) < 50_100


def test_adapter_applies_error_and_image_quotas() -> None:
    """错误文本、图片数量、Base64 和 MIME 均受统一配额约束。"""
    huge_error = MCPToolAdapter._convert_result(SimpleNamespace(
        isError=True,
        content=[SimpleNamespace(type="text", text="x" * 100_000)],
    ))
    assert "结果已截断" in huge_error.content
    assert len(huge_error.content) < 51_000

    images = [
        SimpleNamespace(type="image", data="iVBORw0KGgo=", mimeType="image/png")
        for _ in range(6)
    ]
    images.extend([
        SimpleNamespace(type="image", data="%%%", mimeType="image/png"),
        SimpleNamespace(type="image", data="iVBORw0KGgo=", mimeType="image/gif"),
    ])
    converted = MCPToolAdapter._convert_result(SimpleNamespace(isError=False, content=images))
    assert len(converted.image_urls) == 5
    assert "已忽略 3 张 MCP 图片：图片数量超过限制" in converted.content


def test_adapter_limits_total_content_parts_and_summarizes_ignored_images(monkeypatch) -> None:
    """无效图片不得造成无界解码、原因列表或二次遍历。"""
    class _RepeatedInvalidImages:
        def __len__(self) -> int:
            return 100_000

        def __iter__(self):
            for _ in range(100_000):
                yield SimpleNamespace(type="image", data="%%%", mimeType="image/png")

    decode_calls = 0
    original_decode = __import__("app.agent.mcp.adapter", fromlist=["base64"]).base64.b64decode

    def counted_decode(*args, **kwargs):
        nonlocal decode_calls
        decode_calls += 1
        return original_decode(*args, **kwargs)

    monkeypatch.setattr("app.agent.mcp.adapter.base64.b64decode", counted_decode)
    converted = MCPToolAdapter._convert_result(SimpleNamespace(
        isError=False,
        content=_RepeatedInvalidImages(),
    ))

    assert decode_calls == 1_000
    assert converted.content.count("Base64 非法") == 1
    assert "已忽略 1000 张 MCP 图片" in converted.content
    assert "已忽略 99000 个 MCP content parts" in converted.content


def test_adapter_does_not_preserve_untrusted_content_type_or_mime_values() -> None:
    """汇总原因必须使用固定类别，不能保存远端构造的任意字符串。"""
    parts = [
        SimpleNamespace(type="image", data="", mimeType=f"image/attacker-{index}")
        for index in range(500)
    ]
    parts.extend(SimpleNamespace(type=f"attacker-{index}") for index in range(500))

    converted = MCPToolAdapter._convert_result(SimpleNamespace(isError=False, content=parts))

    assert "image/attacker-" not in converted.content
    assert "attacker-" not in converted.content
    assert converted.content.count("MIME 不支持") == 1
    assert converted.content.count("不支持的 MCP 内容类型") == 1


@pytest.mark.parametrize("part_type", ["text", "audio", "resource", "unknown"])
def test_adapter_applies_content_part_limit_to_every_part_type(part_type: str) -> None:
    """文本、音频、资源和未知类型均必须受同一总数量限制。"""
    class _RepeatedParts:
        def __len__(self) -> int:
            return 100_000

        def __iter__(self):
            for _ in range(100_000):
                yield SimpleNamespace(type=part_type, text="x")

    converted = MCPToolAdapter._convert_result(SimpleNamespace(
        isError=False,
        content=_RepeatedParts(),
    ))

    assert "已忽略 99000 个 MCP content parts" in converted.content
    if part_type != "text":
        assert "已忽略 1000 个不支持的 MCP 内容类型" in converted.content


def test_adapter_stops_image_signature_checks_at_content_part_limit(monkeypatch) -> None:
    """达到 content parts 上限后不得继续执行图片签名校验。"""
    class _RepeatedImages:
        def __len__(self) -> int:
            return 100_000

        def __iter__(self):
            for _ in range(100_000):
                yield SimpleNamespace(type="image", data="AA==", mimeType="image/png")

    signature_calls = 0

    def counted_signature(_mime_type: str, _data: bytes) -> bool:
        nonlocal signature_calls
        signature_calls += 1
        return False

    monkeypatch.setattr(MCPToolAdapter, "_has_valid_image_signature", counted_signature)
    converted = MCPToolAdapter._convert_result(SimpleNamespace(
        isError=False,
        content=_RepeatedImages(),
    ))

    assert signature_calls == 1_000
    assert "已忽略 1000 张 MCP 图片：文件签名不匹配" in converted.content
    assert "已忽略 99000 个 MCP content parts" in converted.content


def test_tool_catalog_and_instructions_quotas() -> None:
    """超大工具目录在进入缓存前失败，instructions 则安全截断。"""
    from app.mcp.limits import limit_instructions, validate_tool_catalog

    tools = [
        SimpleNamespace(name=f"tool_{index}", description="", inputSchema={}, annotations={})
        for index in range(201)
    ]
    with pytest.raises(ValueError, match="工具数量"):
        validate_tool_catalog(tools)

    oversized_schema = SimpleNamespace(
        name="large",
        description="",
        inputSchema={"value": "x" * (256 * 1024 + 1)},
        annotations={},
    )
    with pytest.raises(ValueError, match="Schema"):
        validate_tool_catalog([oversized_schema])

    limited = limit_instructions("x" * 30_000)
    assert limited is not None and len(limited) < 21_000
    assert "instructions 已截断" in limited


@pytest.mark.asyncio
async def test_disabled_server_never_creates_session_on_connect_or_reconnect() -> None:
    """disabled 是 Manager 底层硬门禁，不得触发 session factory。"""
    calls: list[str] = []
    config = MCPServersConfig(servers=[StdioMCPServerConfig(
        id="disabled", name="Disabled", enabled=False, command="python"
    )])

    @asynccontextmanager
    async def session_factory(server):
        calls.append(server.id)
        yield _FakeSession()

    manager = MCPConnectionManager(lambda: config, session_factory=session_factory)
    with pytest.raises(MCPServerDisabledError):
        await manager.connect("disabled")
    with pytest.raises(MCPServerDisabledError):
        await manager.reconnect("disabled")

    assert calls == []
    assert manager.get_status("disabled")["status"] == "disabled"


class _BoundTool(BaseTool):
    name = "mcp__filesystem__read_file"
    description = "bound"
    parameters_schema = {"type": "object", "properties": {}}

    async def execute(self, args: dict, context: ToolContext) -> ToolResult:
        return ToolResult.success("ok")


@pytest.mark.asyncio
async def test_agent_builds_adapters_without_owning_connections(tmp_path: Path) -> None:
    class _Manager:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.config = StdioMCPServerConfig(
                id="filesystem", name="Filesystem", enabled=True, command="python"
            )

        def get_server_config(self, server_id: str):
            assert server_id == "filesystem"
            return self.config

        async def connect(self, server_id: str):
            self.calls.append(server_id)
            return [MCPToolDescriptor("read_file", "读取", {"type": "object"})]

    manager = _Manager()
    model_settings = MCPModelSettings(
        servers={"filesystem": MCPServerPolicy(enabled=True, tools={"read_file": "allow"})}
    )
    agent = Agent(
        AgentConfig(
            session_id="mcp-agent",
            model_name="model",
            api_key="key",
            context_strategy=ContextStrategyConfig(),
            mcp=model_settings,
        ),
        db_path=str(tmp_path / "state.sqlite3"),
        mcp_connection_manager=manager,
        mcp_policy_resolver=_MutablePolicyResolver(
            MCPToolPolicy.ALLOW,
            server_identity_fingerprint(manager.config),
        ),
    )

    await agent.initialize()
    assert agent.tool_manager.has("mcp__filesystem__read_file")
    assert manager.calls == ["filesystem"]
    await agent.close()


@pytest.mark.asyncio
async def test_mcp_service_crud_exposes_runtime_status_and_cascades_policies(tmp_path: Path) -> None:
    mcp_file = tmp_path / "mcp_servers.yaml"
    chat_file = tmp_path / "chat_settings.yaml"
    chat_file.write_text("chat_models: []\n", encoding="utf-8")
    chat_dao = ChatSettingsDao(config_file=chat_file)
    chat_dao.add_chat_settings(
        _chat_settings(
            mcp={
                "servers": {
                    "github": {
                        "enabled": True,
                        "tools": {"search": "ask"},
                    }
                }
            }
        )
    )

    class _Manager:
        def __init__(self) -> None:
            self.disconnected: list[str] = []

        def get_status(self, _server_id: str):
            return {"status": "available", "tool_count": 1, "last_error": None, "instructions": None}

        async def connect(self, _server_id: str):
            return []

        async def disconnect(self, server_id: str):
            self.disconnected.append(server_id)

        async def test_config(self, _config):
            return {"status": "available", "tools": []}

        def get_tools(self, _server_id: str):
            return []

    manager = _Manager()
    service = MCPService(MCPSettingsDao(mcp_file), chat_dao, manager)
    server = StdioMCPServerConfig(
        id="github",
        name="GitHub",
        enabled=True,
        transport="stdio",
        command="npx",
        env={"GITHUB_TOKEN": "plain-secret"},
    )

    created = await service.create_server(server)
    assert created["config"]["env"]["GITHUB_TOKEN"] == "plain-secret"
    assert created["runtime"]["status"] == "available"
    assert created["affected_model_count"] == 1
    assert len(service.list_servers()) == 1

    affected = await service.delete_server("github")
    assert affected == ["session-a"]
    assert manager.disconnected == ["github"]
    assert MCPSettingsDao(mcp_file).load().servers == []
    assert ChatSettingsDao(chat_file).get_chat_settings("session-a").mcp.servers == {}


@pytest.mark.asyncio
async def test_identity_change_rebinds_all_current_tools_to_ask(tmp_path: Path) -> None:
    mcp_file = tmp_path / "mcp_servers.yaml"
    chat_file = tmp_path / "chat_settings.yaml"
    old_server = StdioMCPServerConfig(
        id="filesystem", name="Filesystem", enabled=True, command="old-command"
    )
    MCPSettingsDao(mcp_file).save(MCPServersConfig(servers=[old_server]))
    chat_file.write_text("chat_models: []\n", encoding="utf-8")
    chat_dao = ChatSettingsDao(chat_file)
    chat_dao.add_chat_settings(_chat_settings(mcp={"servers": {
        "filesystem": {
            "enabled": True,
            "identity_fingerprint": server_identity_fingerprint(old_server),
            "tools": {"read_file": "allow", "old_tool": "allow"},
        }
    }}))

    class _Manager:
        async def reconnect(self, _server_id: str):
            return [
                MCPToolDescriptor("read_file", "read", {"type": "object"}),
                MCPToolDescriptor("new_tool", "new", {"type": "object"}),
            ]

        def get_status(self, _server_id: str):
            return {"status": "available", "tool_count": 2, "last_error": None, "instructions": None}

        async def disconnect(self, _server_id: str):
            pass

    service = MCPService(MCPSettingsDao(mcp_file), chat_dao, _Manager())
    new_server = old_server.model_copy(update={"command": "new-command"})

    await service.update_server("filesystem", new_server)

    policy = ChatSettingsDao(chat_file).get_chat_settings("session-a").mcp.servers["filesystem"]
    assert policy.enabled is True
    assert policy.tools == {
        "read_file": MCPToolPolicy.ASK,
        "new_tool": MCPToolPolicy.ASK,
    }
    assert policy.identity_fingerprint == server_identity_fingerprint(new_server)


@pytest.mark.asyncio
async def test_chat_settings_save_filters_deleted_servers_and_downgrades_unbound_allow(
    tmp_path: Path,
) -> None:
    mcp_file = tmp_path / "mcp_servers.yaml"
    chat_file = tmp_path / "chat_settings.yaml"
    server = StdioMCPServerConfig(
        id="filesystem", name="Filesystem", enabled=True, command="python"
    )
    MCPSettingsDao(mcp_file).save(MCPServersConfig(servers=[server]))
    chat_file.write_text("chat_models: []\n", encoding="utf-8")
    chat_dao = ChatSettingsDao(chat_file)
    chat_dao.add_chat_settings(_chat_settings())

    class _Manager:
        tool_names = ["read_file"]

        def get_available_identity(self, _server_id: str):
            return server_identity_fingerprint(server)

        def get_tools(self, _server_id: str):
            return [
                MCPToolDescriptor(name, name, {"type": "object"})
                for name in self.tool_names
            ]

    manager = _Manager()
    service = ChatSettingsService(
        chat_dao,
        MCPSettingsDao(mcp_file),
        manager,
    )
    incoming = _chat_settings(mcp={"servers": {
        "filesystem": {"enabled": True, "tools": {"read_file": "allow"}},
        "deleted": {"enabled": True, "tools": {"danger": "allow"}},
    }})

    await service.update_chat_settings(incoming)

    saved = ChatSettingsDao(chat_file).get_chat_settings("session-a")
    assert set(saved.mcp.servers) == {"filesystem"}
    assert saved.mcp.servers["filesystem"].tools == {"read_file": MCPToolPolicy.ASK}
    assert (
        saved.mcp.servers["filesystem"].identity_fingerprint
        == server_identity_fingerprint(server)
    )

    manager.tool_names = ["read_file", "new_tool"]
    bound_update = _chat_settings(mcp={"servers": {
        "filesystem": {
            "enabled": True,
            "identity_fingerprint": server_identity_fingerprint(server),
            "tools": {"read_file": "allow", "new_tool": "allow"},
        }
    }})
    await service.update_chat_settings(bound_update)
    rebound = ChatSettingsDao(chat_file).get_chat_settings("session-a")
    assert rebound.mcp.servers["filesystem"].tools == {
        "read_file": MCPToolPolicy.ALLOW,
        "new_tool": MCPToolPolicy.ASK,
    }

    MCPSettingsDao(mcp_file).save(MCPServersConfig())
    await service.update_chat_settings(bound_update)
    assert ChatSettingsDao(chat_file).get_chat_settings("session-a").mcp.servers == {}


@pytest.mark.asyncio
async def test_concurrent_server_delete_and_stale_chat_settings_put_cannot_restore_policy(
    tmp_path: Path,
) -> None:
    import asyncio

    mcp_file = tmp_path / "mcp_servers.yaml"
    chat_file = tmp_path / "chat_settings.yaml"
    server = StdioMCPServerConfig(
        id="filesystem", name="Filesystem", enabled=True, command="python"
    )
    MCPSettingsDao(mcp_file).save(MCPServersConfig(servers=[server]))
    chat_file.write_text("chat_models: []\n", encoding="utf-8")
    chat_dao = ChatSettingsDao(chat_file)
    original = _chat_settings(mcp={"servers": {"filesystem": {
        "enabled": True,
        "identity_fingerprint": server_identity_fingerprint(server),
        "tools": {"read_file": "allow"},
    }}})
    chat_dao.add_chat_settings(original)

    class _Manager:
        async def disconnect(self, _server_id: str):
            await asyncio.sleep(0)

        def get_available_identity(self, _server_id: str):
            return server_identity_fingerprint(server)

        def get_tools(self, _server_id: str):
            return [MCPToolDescriptor("read_file", "read", {"type": "object"})]

    coordinator = SettingsMutationCoordinator()
    manager = _Manager()
    mcp_service = MCPService(
        MCPSettingsDao(mcp_file), chat_dao, manager, coordinator
    )
    chat_service = ChatSettingsService(
        chat_dao, MCPSettingsDao(mcp_file), manager, coordinator
    )

    await asyncio.gather(
        mcp_service.delete_server("filesystem"),
        chat_service.update_chat_settings(original),
    )

    assert ChatSettingsDao(chat_file).get_chat_settings("session-a").mcp.servers == {}


@pytest.mark.asyncio
async def test_mcp_approval_resume_rejects_stale_request_id(monkeypatch) -> None:
    from app.services import agent_service as agent_service_module

    state = AgentState.create_new("session-a")
    state.set_interrupt(
        {
            "type": "mcp_tool_approval_request",
            "request_id": "request-current",
            "message": "允许调用？",
        }
    )

    class _StateManager:
        def __init__(self, _session_id):
            pass

        async def load(self):
            return state

        async def close(self):
            pass

    monkeypatch.setattr(agent_service_module, "StateManager", _StateManager)
    service = AgentService(
        chat_history_dao=None,
        chat_settings_loader=lambda _session_id: object(),
        agent_factory=lambda _settings: (_ for _ in ()).throw(AssertionError("不应构造 Agent")),
    )

    with pytest.raises(ValueError, match="已过期"):
        async for _ in service.resume_after_mcp_tool(
            "session-a", request_id="request-stale", approved=True
        ):
            pass


@pytest.mark.asyncio
async def test_mcp_approval_resume_passes_single_decision_to_agent(monkeypatch) -> None:
    from app.services import agent_service as agent_service_module

    state = AgentState.create_new("session-a")
    state.set_interrupt(
        {
            "type": "mcp_tool_approval_request",
            "request_id": "request-current",
            "message": "允许调用？",
        }
    )

    class _StateManager:
        def __init__(self, _session_id):
            pass

        async def load(self):
            return state

        async def close(self):
            pass

    class _Agent:
        def __init__(self):
            self.resume_data = None
            self.closed = False

        async def resume(self, data):
            self.resume_data = data
            yield AgentEvent(EventType.TEXT_CHUNK, "继续")

        async def close(self):
            self.closed = True

    agent = _Agent()
    monkeypatch.setattr(agent_service_module, "StateManager", _StateManager)
    service = AgentService(
        chat_history_dao=None,
        chat_settings_loader=lambda _session_id: object(),
        agent_factory=lambda _settings: agent,
    )

    events = [
        event
        async for event in service.resume_after_mcp_tool(
            "session-a", request_id="request-current", approved=False
        )
    ]

    assert [event.data for event in events] == ["继续"]
    assert agent.resume_data == {"approved": False}
    assert agent.closed is True
