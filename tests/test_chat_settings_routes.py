import pytest

from app.agent.context_strategy import ContextStrategyConfig
from app.routes.chat_settings import add_chat_settings, update_chat_settings
from app.schemas.chat_settings import ChatSettings


def _settings(policy: str) -> ChatSettings:
    return ChatSettings(
        session_id="normalized-route",
        model_name="model",
        openai_api_key="key",
        openai_base_url="http://127.0.0.1:1/v1",
        temperature=0.1,
        system_prompt="prompt",
        tools_list=[],
        context_strategy=ContextStrategyConfig(),
        mcp={"servers": {"filesystem": {"enabled": True, "tools": {"read": policy}}}},
    )


class _NormalizingService:
    async def add_chat_settings(self, _incoming: ChatSettings) -> ChatSettings:
        return _settings("ask")

    async def update_chat_settings(self, _incoming: ChatSettings) -> ChatSettings:
        return _settings("ask")


@pytest.mark.asyncio
@pytest.mark.parametrize("handler", [add_chat_settings, update_chat_settings])
async def test_chat_settings_write_returns_normalized_saved_object(handler) -> None:
    result = await handler(_settings("allow"), _NormalizingService())

    assert result.data.mcp.servers["filesystem"].tools["read"].value == "ask"
