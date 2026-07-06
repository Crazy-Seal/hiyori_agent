import asyncio

from app.agent.context import HookContext, PluginHook
from app.agent.message import SCREENSHOT_COMPRESSED_NAME, SCREENSHOT_MESSAGE_NAME
from app.agent.plugins.context_window import (
    ContextWindowPlugin,
    _compress_screenshot_messages,
    _slice_recent_messages_by_human,
)
from app.agent.state import AgentState


def _human(index: int) -> dict:
    return {"role": "user", "content": f"human-{index}"}


def _screenshot(index: int) -> dict:
    return {
        "role": "user",
        "content": [{"type": "image_url", "image_url": {"url": f"image-{index}"}}],
        "name": SCREENSHOT_MESSAGE_NAME,
    }


def test_screenshot_expires_after_two_real_human_messages() -> None:
    messages = [_screenshot(1), _human(1), _human(2)]

    result = _compress_screenshot_messages(messages)

    assert result[0]["name"] == SCREENSHOT_COMPRESSED_NAME


def test_only_two_latest_uncompressed_screenshots_remain() -> None:
    result = _compress_screenshot_messages(
        [_screenshot(1), _screenshot(2), _screenshot(3)]
    )

    assert [message["name"] for message in result] == [
        SCREENSHOT_COMPRESSED_NAME,
        SCREENSHOT_MESSAGE_NAME,
        SCREENSHOT_MESSAGE_NAME,
    ]


def test_message_window_counts_only_real_human_messages() -> None:
    messages: list[dict] = []
    for index in range(12):
        messages.extend([_human(index), _screenshot(index)])

    result = _slice_recent_messages_by_human(messages, 10)

    assert [message["content"] for message in result if "name" not in message] == [
        f"human-{index}" for index in range(2, 12)
    ]
    screenshot_count = sum(
        1
        for message in result
        if message.get("name") == SCREENSHOT_MESSAGE_NAME
    )
    assert screenshot_count == 10


def test_context_window_hooks_apply_model_and_checkpoint_limits() -> None:
    async def scenario() -> tuple[int, int]:
        plugin = ContextWindowPlugin()
        state = AgentState.create_new("test-session")
        for index in range(25):
            state.add_user_message(f"human-{index}")
            state.add_assistant_message(f"assistant-{index}")

        await plugin.execute(HookContext.create(PluginHook.BEFORE_LLM, state))
        model_human_count = sum(
            1
            for message in state.extra["llm_messages"]
            if message.get("role") == "user"
        )

        await plugin.execute(HookContext.create(PluginHook.BEFORE_RESPONSE, state))
        checkpoint_human_count = sum(
            1 for message in state.messages if message.get("role") == "user"
        )
        return model_human_count, checkpoint_human_count

    assert asyncio.run(scenario()) == (10, 20)
