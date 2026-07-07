from pathlib import Path

import yaml
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
        memory_plugins=None,
        skills=["coding"],
    )

    dao.add_chat_settings(settings)
    reloaded = ChatSettingsDao(config_file=config_file).get_chat_settings("test-session")

    assert reloaded.skills == ["coding"]
    assert reloaded.agent_plugins["memory"].enabled is True


def test_legacy_memory_plugins_are_migrated_to_agent_plugins(tmp_path: Path) -> None:
    config_file = tmp_path / "chat_settings.yaml"
    config_file.write_text(
        yaml.safe_dump(
            {
                "chat_models": [
                    {
                        "session_id": "legacy-session",
                        "model_name": "test-model",
                        "openai_api_key": "test-key",
                        "openai_base_url": "http://127.0.0.1:1/v1",
                        "temperature": 0.1,
                        "system_prompt": "test",
                        "tools_list": [],
                        "memory_plugins": ["diary", "semantic"],
                    }
                ]
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    settings = ChatSettingsDao(config_file=config_file).get_chat_settings("legacy-session")

    assert settings.agent_plugins["context_window"].enabled is True
    memory = settings.agent_plugins["memory"]
    assert memory.enabled is True
    assert memory.config["enable_diary"] is True
    assert memory.config["enable_episodic"] is False
    assert memory.config["enable_semantic"] is True


def test_agent_plugins_round_trip_and_sync_memory_plugins(tmp_path: Path) -> None:
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
        memory_plugins=None,
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

    assert reloaded.memory_plugins == ["episodic", "semantic"]
    assert reloaded.agent_plugins["memory"].config["summary_every_human_messages"] == 12


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
    assert settings.memory_plugins is None


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
