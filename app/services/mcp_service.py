from __future__ import annotations

from typing import Any

from app.crud.chat_settings_dao import ChatSettingsDao
from app.crud.mcp_settings_dao import MCPSettingsDao
from app.schemas.mcp import MCPServerConfig, MCPServersConfig
from app.mcp.identity import server_identity_fingerprint
from app.services.mcp_connection_manager import (
    MCPConnectionError,
    MCPConnectionManager,
    MCPServerDisabledError,
)
from app.services.settings_mutation import SettingsMutationCoordinator


class MCPService:
    """编排 MCP Server 配置、连接状态和模型权限同步。"""

    def __init__(
        self,
        settings_dao: MCPSettingsDao,
        chat_settings_dao: ChatSettingsDao,
        connection_manager: MCPConnectionManager,
        mutation_coordinator: SettingsMutationCoordinator | None = None,
    ):
        """初始化 MCP 应用服务。

        Args:
            settings_dao: MCP Server 配置数据访问对象。
            chat_settings_dao: 模型配置数据访问对象。
            connection_manager: 进程级 MCP 连接管理器。
            mutation_coordinator: 可选的跨配置写入协调器。
        """
        self.settings_dao = settings_dao
        self.chat_settings_dao = chat_settings_dao
        self.connection_manager = connection_manager
        self.mutation_coordinator = mutation_coordinator or SettingsMutationCoordinator()

    def list_servers(self) -> list[dict[str, Any]]:
        """列出全部 MCP Server 及其运行状态。

        Returns:
            面向设置页的 Server 视图列表。
        """
        return [self._server_view(server) for server in self.settings_dao.load().servers]

    async def test_server(self, server: MCPServerConfig) -> dict[str, Any]:
        """测试一份 MCP Server 配置但不持久化。

        Args:
            server: 待测试的 Server 配置。

        Returns:
            连接状态、instructions 和工具目录。
        """
        return await self.connection_manager.test_config(server)

    async def create_server(self, server: MCPServerConfig) -> dict[str, Any]:
        """创建 MCP Server，并在启用时尝试连接和同步权限。

        Args:
            server: 待创建的 Server 配置。

        Returns:
            新 Server 的设置页视图。

        Raises:
            ValueError: Server ID 已存在。
        """
        async with self.mutation_coordinator.lock:
            config = self.settings_dao.load()
            if any(item.id == server.id for item in config.servers):
                raise ValueError(f"MCP server_id already exists: {server.id}")
            config.servers.append(server)
            self.settings_dao.save(config)
            if server.enabled:
                try:
                    tools = await self.connection_manager.connect(server.id)
                    self._reconcile_policies(server, tools)
                except MCPConnectionError:
                    pass
            return self._server_view(server)

    async def update_server(self, server_id: str, server: MCPServerConfig) -> dict[str, Any]:
        """更新 MCP Server 并处理连接和身份变化。

        Args:
            server_id: 路径中的原 Server ID。
            server: 更新后的完整 Server 配置。

        Returns:
            更新后的设置页视图。

        Raises:
            ValueError: 请求尝试修改 Server ID。
            KeyError: 指定 Server 不存在。
        """
        async with self.mutation_coordinator.lock:
            if server.id != server_id:
                raise ValueError("MCP server_id 不允许修改")
            config = self.settings_dao.load()
            for index, current in enumerate(config.servers):
                if current.id != server_id:
                    continue
                identity_changed = (
                    server_identity_fingerprint(current) != server_identity_fingerprint(server)
                )
                config.servers[index] = server
                self.settings_dao.save(config)
                if server.enabled:
                    try:
                        tools = await self.connection_manager.reconnect(server_id)
                        self._reconcile_policies(server, tools)
                    except MCPConnectionError:
                        if identity_changed:
                            self.chat_settings_dao.invalidate_mcp_server_identity(server_id)
                else:
                    await self.connection_manager.disconnect(server_id)
                    if identity_changed:
                        self.chat_settings_dao.invalidate_mcp_server_identity(server_id)
                return self._server_view(server)
            raise KeyError(f"MCP server_id not found: {server_id}")

    async def delete_server(self, server_id: str) -> list[str]:
        """删除 MCP Server 及全部模型引用。

        Args:
            server_id: 待删除的 MCP Server ID。

        Returns:
            权限引用受到清理的会话 ID 列表。

        Raises:
            KeyError: 指定 Server 不存在。
        """
        async with self.mutation_coordinator.lock:
            config = self.settings_dao.load()
            if not any(server.id == server_id for server in config.servers):
                raise KeyError(f"MCP server_id not found: {server_id}")
            affected = self.chat_settings_dao.remove_mcp_server_references(server_id)
            await self.connection_manager.disconnect(server_id)
            self.settings_dao.save(
                MCPServersConfig(servers=[server for server in config.servers if server.id != server_id])
            )
            return affected

    async def reconnect(self, server_id: str) -> dict[str, Any]:
        """重连 MCP Server 并按最新工具目录同步权限。

        Args:
            server_id: 待重连的 MCP Server ID。

        Returns:
            重连后的设置页视图。

        Raises:
            KeyError: 指定 Server 不存在。
        """
        async with self.mutation_coordinator.lock:
            server = next(
                (item for item in self.settings_dao.load().servers if item.id == server_id),
                None,
            )
            if server is None:
                raise KeyError(f"MCP server_id not found: {server_id}")
            if not server.enabled:
                raise MCPServerDisabledError(f"MCP Server '{server_id}' 已禁用")
            tools = await self.connection_manager.reconnect(server_id)
            self._reconcile_policies(server, tools)
            return self._server_view(server)

    def _reconcile_policies(self, server: MCPServerConfig, tools: list[Any]) -> None:
        """按服务身份和最新工具目录同步所有模型权限。

        Args:
            server: 已成功连接的 Server 配置。
            tools: Server 当前暴露的工具描述符。
        """
        self.chat_settings_dao.reconcile_mcp_server_tools(
            server.id,
            server_identity_fingerprint(server),
            [tool.name for tool in tools],
        )

    def list_tools(self, server_id: str) -> list[dict[str, Any]]:
        """列出指定 MCP Server 的已缓存工具目录。

        Args:
            server_id: MCP Server ID。

        Returns:
            面向 API 的工具信息列表。

        Raises:
            KeyError: 指定 Server 不存在。
        """
        if not any(server.id == server_id for server in self.settings_dao.load().servers):
            raise KeyError(f"MCP server_id not found: {server_id}")
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
                "annotations": tool.annotations,
            }
            for tool in self.connection_manager.get_tools(server_id)
        ]

    def _server_view(self, server: MCPServerConfig) -> dict[str, Any]:
        """构造设置页使用的 MCP Server 视图。

        Args:
            server: MCP Server 配置。

        Returns:
            包含配置、运行状态和模型引用数量的字典。
        """
        return {
            "config": server.model_dump(mode="json"),
            "runtime": self.connection_manager.get_status(server.id),
            "affected_model_count": self.chat_settings_dao.count_mcp_server_references(server.id),
        }
