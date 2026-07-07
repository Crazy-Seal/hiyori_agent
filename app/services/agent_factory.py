"""agent 工厂 - 把 ChatSettings 映射为 Agent。"""

from app.agent.agent import Agent, AgentConfig
from app.schemas.chat_settings import (
    CONTEXT_WINDOW_DEFAULT_CONFIG,
    MEMORY_DEFAULT_CONFIG,
    ChatSettings,
)


def _plugin_config(chat_settings: ChatSettings, name: str, defaults: dict) -> dict:
    settings = chat_settings.agent_plugins.get(name)
    config = dict(defaults)
    if settings:
        config.update(settings.config)
    return config


def build_agent(chat_settings: ChatSettings) -> Agent:
    """根据会话配置构造一个 Agent。"""
    plugins: list[dict] = [
        {
            "name": "context_window",
            "config": _plugin_config(
                chat_settings,
                "context_window",
                CONTEXT_WINDOW_DEFAULT_CONFIG,
            ),
        },
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
        plugins=plugins,
        skills=list(chat_settings.skills or []),
    )
    return Agent(config)
