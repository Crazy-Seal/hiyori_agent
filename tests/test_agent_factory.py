from app.agent.context_strategy import ContextStrategyConfig
from app.schemas.chat_settings import AgentPluginSettings, ChatSettings
from app.services import agent_factory


def _settings(agent_plugins=None, context_strategy=None):
    return ChatSettings(
        session_id="test-session",
        model_name="test-model",
        openai_api_key="test-key",
        openai_base_url="http://127.0.0.1:1/v1",
        temperature=0.1,
        system_prompt="test",
        tools_list=[],
        agent_plugins=agent_plugins,
        context_strategy=context_strategy or ContextStrategyConfig(),
        skills=[],
    )


def test_memory_plugin_owns_image_processing(monkeypatch) -> None:
    monkeypatch.setattr(agent_factory, "Agent", lambda config: config)

    config = agent_factory.build_agent(_settings())

    assert config.context_strategy.recent_context_human_messages == 10
    assert config.plugins == [
        {"name": "memory", "config": {
            "enable_diary": True,
            "enable_episodic": True,
            "enable_semantic": True,
            "summary_every_human_messages": 10,
        }},
    ]


def test_agent_factory_uses_top_level_context_strategy(monkeypatch) -> None:
    monkeypatch.setattr(agent_factory, "Agent", lambda config: config)

    settings = _settings(
        context_strategy=ContextStrategyConfig(recent_context_human_messages=3),
        agent_plugins={
            "memory": AgentPluginSettings(
                enabled=False,
                config={
                    "enable_diary": False,
                    "enable_episodic": True,
                    "enable_semantic": False,
                    "summary_every_human_messages": 7,
                },
            ),
        }
    )

    config = agent_factory.build_agent(settings)

    assert config.context_strategy.recent_context_human_messages == 3
    assert config.plugins == [
        {"name": "memory", "config": {
            "enable_diary": False,
            "enable_episodic": True,
            "enable_semantic": False,
            "summary_every_human_messages": 7,
        }},
    ]


def test_agent_factory_loads_memory_when_all_memory_types_are_disabled(monkeypatch) -> None:
    monkeypatch.setattr(agent_factory, "Agent", lambda config: config)

    settings = _settings(
        agent_plugins={
            "memory": AgentPluginSettings(
                enabled=False,
                config={
                    "enable_diary": False,
                    "enable_episodic": False,
                    "enable_semantic": False,
                },
            )
        }
    )

    config = agent_factory.build_agent(settings)

    assert config.plugins[0] == {
        "name": "memory",
        "config": {
            "enable_diary": False,
            "enable_episodic": False,
            "enable_semantic": False,
            "summary_every_human_messages": 10,
        },
    }


def test_image_is_not_registered_as_standalone_plugin() -> None:
    from app.agent.plugins.registry import PluginRegistry

    assert not PluginRegistry.has("image")
