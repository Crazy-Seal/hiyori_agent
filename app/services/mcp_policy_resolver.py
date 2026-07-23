"""解析会话级 MCP 实时权限。"""

from collections.abc import Callable

from app.schemas.chat_settings import ChatSettings
from app.schemas.mcp import MCPToolPolicy


class MCPPolicyResolver:
    """按调用读取最新会话配置并解析 MCP 权限。"""

    def __init__(self, settings_loader: Callable[[str], ChatSettings]) -> None:
        """初始化权限解析器。

        Args:
            settings_loader: 根据会话 ID 读取最新聊天配置的函数。
        """
        self._settings_loader = settings_loader

    def get_policy(
        self,
        session_id: str,
        server_id: str,
        tool_name: str,
    ) -> MCPToolPolicy:
        """读取工具在当前会话中的实时权限。

        Args:
            session_id: 模型配置对应的会话 ID。
            server_id: MCP Server ID。
            tool_name: Server 中的原始工具名称。

        Returns:
            当前工具策略。新发现且未记录的工具默认为 ``ask``；配置缺失、
            Server 禁用或读取异常时安全降级为 ``deny``。
        """
        try:
            settings = self._settings_loader(session_id)
            server = settings.mcp.servers.get(server_id)
            if server is None or not server.enabled:
                return MCPToolPolicy.DENY
            return MCPToolPolicy(server.tools.get(tool_name, MCPToolPolicy.ASK))
        except Exception:
            return MCPToolPolicy.DENY

    def get_bound_identity(self, session_id: str, server_id: str) -> str | None:
        """读取当前会话权限绑定的 MCP Server 身份。

        Args:
            session_id: 模型配置对应的会话 ID。
            server_id: MCP Server ID。

        Returns:
            已启用 Server 的身份指纹；配置缺失、禁用或读取异常时返回
            ``None``。
        """
        try:
            settings = self._settings_loader(session_id)
            server = settings.mcp.servers.get(server_id)
            if server is None or not server.enabled:
                return None
            return server.identity_fingerprint
        except Exception:
            return None
