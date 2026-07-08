from pathlib import Path

import pytest
from pydantic import ValidationError

from app.crud.chat_settings_dao import ChatSettingsDao
from app.schemas.chat_settings import AgentPluginSettings, ChatSettings


def test_skills_survive_round_trip(tmp_path: Path) -> None:
    config_file = tmp_path / "chat_settings.yaml"
    config_file.write_text("chat_models: []\n", encoding="utf-8")
    dao = ChatSettingsDao(config_file=config_file)
    settings = ChatSettings(
        session_id="test-session",
        model_name="test-model",
        openai_api_key="test-key",
        openai_base_url="http://127.0.0.1:1/v1",
        temperature=0.1,
        system_prompt="test",
        tools_list=[],
        skills=["sample"],
    )

    dao.add_chat_settings(settings)
    reloaded = ChatSettingsDao(config_file=config_file).get_chat_settings("test-session")

    assert reloaded.skills == ["sample"]
    assert reloaded.agent_plugins["memory"].enabled is True


def test_agent_plugins_round_trip_without_legacy_memory_field(tmp_path: Path) -> None:
    config_file = tmp_path / "chat_settings.yaml"
    config_file.write_text("chat_models: []\n", encoding="utf-8")
    dao = ChatSettingsDao(config_file=config_file)
    settings = ChatSettings(
        session_id="test-session",
        model_name="test-model",
        openai_api_key="test-key",
        openai_base_url="http://127.0.0.1:1/v1",
        temperature=0.1,
        system_prompt="test",
        tools_list=[],
        agent_plugins={
            "memory": AgentPluginSettings(
                enabled=True,
                config={
                    "enable_diary": False,
                    "enable_episodic": True,
                    "enable_semantic": True,
                    "summary_every_human_messages": 12,
                },
            )
        },
        skills=[],
    )

    dao.add_chat_settings(settings)
    reloaded = ChatSettingsDao(config_file=config_file).get_chat_settings("test-session")
    raw_yaml = config_file.read_text(encoding="utf-8")

    assert reloaded.agent_plugins["memory"].config["summary_every_human_messages"] == 12
    assert "memory" + "_plugins" not in raw_yaml


def test_memory_plugin_is_inherent_even_when_disabled_or_all_types_disabled() -> None:
    settings = ChatSettings(
        session_id="test-session",
        model_name="test-model",
        openai_api_key="test-key",
        openai_base_url="http://127.0.0.1:1/v1",
        temperature=0.1,
        system_prompt="test",
        tools_list=[],
        agent_plugins={
            "memory": AgentPluginSettings(
                enabled=False,
                config={
                    "enable_diary": False,
                    "enable_episodic": False,
                    "enable_semantic": False,
                },
            )
        },
    )

    memory = settings.agent_plugins["memory"]
    assert memory.enabled is True
    assert memory.config["enable_diary"] is False
    assert memory.config["enable_episodic"] is False
    assert memory.config["enable_semantic"] is False


def test_agent_plugin_config_is_validated_before_persistence() -> None:
    with pytest.raises(ValidationError):
        ChatSettings(
            session_id="test-session",
            model_name="test-model",
            openai_api_key="test-key",
            openai_base_url="http://127.0.0.1:1/v1",
            temperature=0.1,
            system_prompt="test",
            tools_list=[],
            agent_plugins={
                "context_window": AgentPluginSettings(
                    enabled=True,
                    config={"recent_context_human_messages": 0},
                ),
                "memory": AgentPluginSettings(
                    enabled=True,
                    config={"summary_every_human_messages": 0},
                ),
            },
        )
