from fastapi.testclient import TestClient

from main import app
from app.agent.plugins.registry import PluginRegistry


def test_plugin_registry_auto_discovers_plugins() -> None:
    assert PluginRegistry.has("context_window")
    assert PluginRegistry.has("memory")
    assert not PluginRegistry.has("image")


def test_plugins_endpoint_exposes_metadata_from_config_model() -> None:
    response = TestClient(app).get("/plugins")

    assert response.status_code == 200
    payload = response.json()
    plugins = {item["name"]: item for item in payload["data"]["plugins"]}

    context_window = plugins["context_window"]
    assert context_window["inherent"] is True
    assert context_window["default_config"]["recent_context_human_messages"] == 10
    assert context_window["default_config"]["max_images_in_context"] == 5
    assert "properties" in context_window["config_schema"]
    assert "recent_context_human_messages" in context_window["config_schema"]["properties"]

    memory = plugins["memory"]
    assert memory["inherent"] is True
    assert memory["default_config"]["enable_diary"] is True
    assert memory["default_config"]["summary_every_human_messages"] == 10
