import asyncio

from app.agent.context import HookContext, PluginHook
from app.agent.message import SCREENSHOT_COMPRESSED_NAME, SCREENSHOT_MESSAGE_NAME
from app.agent.plugins.context_window import (
    ContextWindowPluginConfig,
    ContextWindowPlugin,
    _compress_screenshot_messages,
    _compress_window_messages,
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


def _image_message(index: int) -> dict:
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": f"image-message-{index}"},
            {"type": "image_url", "image_url": {"url": f"image-{index}"}},
        ],
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
        plugin = ContextWindowPlugin(
            recent_context_human_messages=6,
        )
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

    assert asyncio.run(scenario()) == (6, 16)


def test_user_images_are_compressed_by_ttl_and_max_count() -> None:
    config = ContextWindowPluginConfig(
        max_images_in_context=1,
        image_ttl_human_messages=2,
    )
    result = _compress_window_messages(
        [
            _image_message(1),
            _human(1),
            _image_message(2),
            _image_message(3),
        ],
        config,
    )

    image_urls = [
        part["image_url"]["url"]
        for message in result
        if isinstance(message.get("content"), list)
        for part in message["content"]
        if isinstance(part, dict) and part.get("type") == "image_url"
    ]

    assert image_urls == ["image-3"]
    assert result[0]["content"][1]["type"] == "text"


def test_compressed_user_image_uses_message_level_image_description() -> None:
    config = ContextWindowPluginConfig(image_ttl_human_messages=1)
    image_message = _image_message(1)
    image_message["image_description"] = "一只橘猫趴在键盘旁边。"

    result = _compress_window_messages([image_message, _human(1)], config)

    compressed_part = result[0]["content"][1]
    assert compressed_part["type"] == "text"
    assert "一只橘猫趴在键盘旁边。" in compressed_part["text"]
