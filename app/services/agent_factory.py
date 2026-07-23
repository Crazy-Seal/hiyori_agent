"""agent 工厂 - 把 ChatSettings 映射为 Agent。"""

from app.agent.agent import Agent, AgentConfig
from app.schemas.chat_settings import (
    MEMORY_DEFAULT_CONFIG,
    ChatSettings,
)
from app.services.mcp_connection_manager import MCPConnectionManager
from app.services.mcp_policy_resolver import MCPPolicyResolver


def _plugin_config(chat_settings: ChatSettings, name: str, defaults: dict) -> dict:
    settings = chat_settings.agent_plugins.get(name)
    config = dict(defaults)
    if settings:
        config.update(settings.config)
    return config


def build_agent(
    chat_settings: ChatSettings,
    mcp_connection_manager: MCPConnectionManager | None = None,
    mcp_policy_resolver: MCPPolicyResolver | None = None,
) -> Agent:
    """根据会话配置构造 Agent。

    Args:
        chat_settings: 当前模型和会话的完整配置。
        mcp_connection_manager: 可选的进程级 MCP 连接管理器。
        mcp_policy_resolver: 可选的会话级 MCP 权限解析器。

    Returns:
        已注入模型配置和 MCP 权限的 Agent。
    """
    plugins: list[dict] = [
        {
            "name": "memory",
            "config": _plugin_config(chat_settings, "memory", MEMORY_DEFAULT_CONFIG),
        },
    ]

    config = AgentConfig(
        session_id=chat_settings.session_id,
        model_name=chat_settings.model_name,
        api_key=chat_settings.openai_api_key,
        base_url=chat_settings.openai_base_url,
        temperature=chat_settings.temperature,
        system_prompt=chat_settings.system_prompt,
        tools=list(chat_settings.tools_list or []),
        context_strategy=chat_settings.context_strategy,
        plugins=plugins,
        skills=list(chat_settings.skills or []),
        mcp=chat_settings.mcp,
    )
    if mcp_connection_manager is None and mcp_policy_resolver is None:
        return Agent(config)
    return Agent(
        config,
        mcp_connection_manager=mcp_connection_manager,
        mcp_policy_resolver=mcp_policy_resolver,
    )
