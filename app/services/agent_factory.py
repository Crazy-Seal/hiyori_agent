"""agent 工厂 - 把 ChatSettings 映射为 Agent。"""

from app.agent.agent import Agent, AgentConfig
from app.schemas.chat_settings import ChatSettings


def build_agent(chat_settings: ChatSettings) -> Agent:
    """根据会话配置构造一个 Agent。"""
    plugins = ["context_window"]
    # 记忆默认随 memory_plugins 开启（与旧语义一致：未配置则不挂记忆）
    if chat_settings.memory_plugins:
        plugins.append("memory")

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
