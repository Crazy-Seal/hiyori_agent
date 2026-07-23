from app.crud.chat_settings_dao import ChatSettingsDao
from app.crud.mcp_settings_dao import MCPSettingsDao
from app.mcp.identity import server_identity_fingerprint
from app.schemas.chat_settings import ChatSettings
from app.schemas.mcp import MCPModelSettings, MCPServerPolicy, MCPToolPolicy
from app.services.mcp_connection_manager import MCPConnectionManager
from app.services.settings_mutation import SettingsMutationCoordinator


class ChatSettingsService:
    """管理模型配置，并协调模型级 MCP 权限的安全写入。"""

    def __init__(
        self,
        chat_settings_dao: ChatSettingsDao,
        mcp_settings_dao: MCPSettingsDao | None = None,
        connection_manager: MCPConnectionManager | None = None,
        mutation_coordinator: SettingsMutationCoordinator | None = None,
    ):
        """初始化模型配置服务。

        Args:
            chat_settings_dao: 模型配置数据访问对象。
            mcp_settings_dao: 可选的 MCP Server 配置数据访问对象。
            connection_manager: 可选的 MCP 连接管理器。
            mutation_coordinator: 可选的跨配置写入协调器。
        """
        self.chat_settings_dao = chat_settings_dao
        self.mcp_settings_dao = mcp_settings_dao
        self.connection_manager = connection_manager
        self.mutation_coordinator = mutation_coordinator or SettingsMutationCoordinator()

    async def add_chat_settings(self, chat_settings: ChatSettings) -> ChatSettings:
        """新增模型配置并正规化 MCP 权限。

        Args:
            chat_settings: 待新增的模型配置。

        Returns:
            已保存的模型配置。
        """
        async with self.mutation_coordinator.lock:
            return self.chat_settings_dao.add_chat_settings(self._sanitize_mcp(chat_settings, None))

    async def delete_chat_settings(self, session_id: str) -> None:
        """删除指定会话对应的模型配置。

        Args:
            session_id: 待删除配置的会话 ID。
        """
        async with self.mutation_coordinator.lock:
            self.chat_settings_dao.delete_chat_settings(session_id)

    def get_chat_settings_by_session(self, session_id: str) -> ChatSettings:
        return self.chat_settings_dao.get_chat_settings(session_id)

    async def update_chat_settings(self, chat_settings: ChatSettings) -> ChatSettings:
        """更新模型配置并安全合并 MCP 权限。

        Args:
            chat_settings: 更新后的完整模型配置。

        Returns:
            已保存的模型配置。
        """
        async with self.mutation_coordinator.lock:
            try:
                existing = self.chat_settings_dao.get_chat_settings(chat_settings.session_id)
            except KeyError:
                existing = None
            sanitized = self._sanitize_mcp(chat_settings, existing)
            return self.chat_settings_dao.update_chat_settings(chat_settings.session_id, sanitized)

    def _sanitize_mcp(
        self,
        chat_settings: ChatSettings,
        existing: ChatSettings | None,
    ) -> ChatSettings:
        """依据服务身份和可用工具目录正规化 MCP 权限。

        Args:
            chat_settings: 前端提交的模型配置。
            existing: 当前已保存的模型配置；新建时为 ``None``。

        Returns:
            已移除无效引用并安全降级新权限的配置副本。
        """
        if self.mcp_settings_dao is None:
            return chat_settings
        configs = {server.id: server for server in self.mcp_settings_dao.load().servers}
        normalized: dict[str, MCPServerPolicy] = {}
        for server_id, incoming in chat_settings.mcp.servers.items():
            config = configs.get(server_id)
            if config is None:
                continue
            identity = server_identity_fingerprint(config)
            previous = existing.mcp.servers.get(server_id) if existing else None
            previous_is_bound = bool(previous and previous.identity_fingerprint == identity)
            incoming_is_bound = incoming.identity_fingerprint == identity
            available_identity = (
                self.connection_manager.get_available_identity(server_id)
                if self.connection_manager is not None
                else None
            )
            available_tools = (
                [tool.name for tool in self.connection_manager.get_tools(server_id)]
                if available_identity == identity and self.connection_manager is not None
                else None
            )

            if previous_is_bound and incoming_is_bound:
                tool_names = (
                    available_tools
                    if available_tools is not None
                    else list(dict.fromkeys([*previous.tools, *incoming.tools]))
                )
                normalized[server_id] = MCPServerPolicy(
                    enabled=incoming.enabled,
                    tools={
                        name: incoming.tools.get(name, MCPToolPolicy.ASK)
                        if name in previous.tools
                        else MCPToolPolicy.ASK
                        for name in tool_names
                    },
                    identity_fingerprint=identity,
                )
                continue

            if available_tools is not None:
                tool_names = available_tools
                fingerprint = identity
            else:
                tool_names = list(incoming.tools)
                fingerprint = previous.identity_fingerprint if previous else None
            normalized[server_id] = MCPServerPolicy(
                enabled=incoming.enabled,
                tools={name: MCPToolPolicy.ASK for name in tool_names},
                identity_fingerprint=fingerprint,
            )

        return chat_settings.model_copy(
            update={"mcp": MCPModelSettings(servers=normalized)}
        )
