from app.schemas.chat_settings import ChatSettings
from app.services import agent_factory


def _settings(memory_plugins):
    return ChatSettings(
        session_id="test-session",
        model_name="test-model",
        openai_api_key="test-key",
        openai_base_url="http://127.0.0.1:1/v1",
        temperature=0.1,
        system_prompt="test",
        tools_list=[],
        memory_plugins=memory_plugins,
        skills=[],
    )


def test_memory_plugin_owns_image_processing(monkeypatch) -> None:
    monkeypatch.setattr(agent_factory, "Agent", lambda config: config)

    without_memory = agent_factory.build_agent(_settings(None))
    with_memory = agent_factory.build_agent(_settings(["summary"]))

    assert without_memory.plugins == ["context_window"]
    assert with_memory.plugins == ["context_window", "memory"]


def test_image_is_not_registered_as_standalone_plugin() -> None:
    from app.agent.plugins.registry import PluginRegistry

    assert not PluginRegistry.has("image")
