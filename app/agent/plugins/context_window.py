"""上下文窗口插件。

负责构造发送给模型的短窗口，并在响应结束后裁剪 checkpoint 体积。
"""

from copy import deepcopy
import logging
from typing import Any

from pydantic import BaseModel, Field

from app.agent.context import BasePlugin, PluginHook, HookContext
from app.agent.message import (
    SCREENSHOT_COMPRESSED_NAME,
    SCREENSHOT_MESSAGE_NAME,
    is_real_human_message,
    is_user_message,
)
from app.agent.utils.domain.text import normalize_messages_for_model

logger = logging.getLogger(__name__)


class ContextWindowPluginConfig(BaseModel):
    recent_context_human_messages: int = Field(
        default=10,
        ge=1,
        description="发送给模型的最近真实用户消息轮数。",
    )
    max_images_in_context: int = Field(
        default=5,
        ge=0,
        description="上下文中最多保留的普通用户上传图片数。",
    )
    image_ttl_human_messages: int = Field(
        default=10,
        ge=0,
        description="普通用户上传图片在多少轮真实用户消息后压缩。",
    )
    max_screenshots_in_context: int = Field(
        default=2,
        ge=0,
        description="上下文中最多保留的截图数。",
    )
    screenshot_ttl_human_messages: int = Field(
        default=2,
        ge=0,
        description="截图在多少轮真实用户消息后压缩。",
    )

    @property
    def checkpoint_human_messages(self) -> int:
        return self.recent_context_human_messages + 10


_COMPRESSED_SCREENSHOT_PLACEHOLDER = "[系统消息]已被压缩的旧截图"
_COMPRESSED_IMAGE_PLACEHOLDER = "[系统消息]已被压缩的旧图片"


def _compressed_screenshot() -> dict:
    return {
        "role": "user",
        "content": _COMPRESSED_SCREENSHOT_PLACEHOLDER,
        "name": SCREENSHOT_COMPRESSED_NAME,
    }


def _compress_screenshot_messages(
    messages: list[dict],
    config: ContextWindowPluginConfig | None = None,
) -> list[dict]:
    """按 TTL 和最大数量压缩上下文中的截图消息。"""
    config = config or ContextWindowPluginConfig()
    result = list(messages)

    for index, message in enumerate(messages):
        if not (
            is_user_message(message)
            and message.get("name") == SCREENSHOT_MESSAGE_NAME
        ):
            continue
        human_count_after = sum(
            1
            for later_message in messages[index + 1:]
            if is_real_human_message(later_message)
        )
        if human_count_after >= config.screenshot_ttl_human_messages:
            result[index] = _compressed_screenshot()

    screenshot_indices = [
        index
        for index, message in enumerate(result)
        if is_user_message(message)
        and message.get("name") == SCREENSHOT_MESSAGE_NAME
    ]
    excess = len(screenshot_indices) - config.max_screenshots_in_context
    for index in screenshot_indices[:max(excess, 0)]:
        result[index] = _compressed_screenshot()

    return result


def _is_plain_user_image_message(message: dict) -> bool:
    return is_real_human_message(message) and isinstance(message.get("content"), list)


def _image_part_refs(messages: list[dict]) -> list[tuple[int, int]]:
    refs: list[tuple[int, int]] = []
    for message_index, message in enumerate(messages):
        if not _is_plain_user_image_message(message):
            continue
        for part_index, part in enumerate(message.get("content") or []):
            if isinstance(part, dict) and part.get("type") == "image_url":
                refs.append((message_index, part_index))
    return refs


def _compress_image_part(message: dict, part_index: int) -> None:
    content = message.get("content")
    if not isinstance(content, list) or part_index >= len(content):
        return
    placeholder = _COMPRESSED_IMAGE_PLACEHOLDER
    image_description = message.get("image_description")
    if isinstance(image_description, str) and image_description.strip():
        placeholder = f"{placeholder}。图片摘要：{image_description.strip()}"
    content[part_index] = {
        "type": "text",
        "text": placeholder,
    }


def _compress_user_image_messages(
    messages: list[dict],
    config: ContextWindowPluginConfig,
) -> list[dict]:
    """按 TTL 和最大数量压缩普通用户上传图片，截图不参与该计数。"""
    result = deepcopy(messages)
    compressed: set[tuple[int, int]] = set()
    refs = _image_part_refs(result)

    for message_index, part_index in refs:
        human_count_after = sum(
            1
            for later_message in result[message_index + 1:]
            if is_real_human_message(later_message)
        )
        if human_count_after >= config.image_ttl_human_messages:
            _compress_image_part(result[message_index], part_index)
            compressed.add((message_index, part_index))

    remaining_refs = [
        ref for ref in refs
        if ref not in compressed
    ]
    excess = len(remaining_refs) - config.max_images_in_context
    for message_index, part_index in remaining_refs[:max(excess, 0)]:
        _compress_image_part(result[message_index], part_index)

    return result


def _compress_window_messages(
    messages: list[dict],
    config: ContextWindowPluginConfig | None = None,
) -> list[dict]:
    config = config or ContextWindowPluginConfig()
    msgs = _compress_screenshot_messages(messages, config)
    return _compress_user_image_messages(msgs, config)


def _slice_recent_messages_by_human(
    messages: list[dict],
    max_human_messages: int = 10,
) -> list[dict]:
    """保留从倒数第 N 条真实用户消息开始的完整消息尾部。"""
    human_count = 0
    start_index = 0
    for index in range(len(messages) - 1, -1, -1):
        if is_real_human_message(messages[index]):
            human_count += 1
            if human_count == max_human_messages:
                start_index = index
                break
    return messages[start_index:]


class ContextWindowPlugin(BasePlugin):
    name = "context_window"
    description = "管理发送给模型的上下文窗口，以及普通图片和截图的压缩策略。"
    inherent = True
    config_model = ContextWindowPluginConfig
    version = "1.0.0"
    priority = 200

    def __init__(self, **config: Any) -> None:
        self.config = ContextWindowPluginConfig(**config)

    @property
    def hooks(self) -> list[PluginHook]:
        return [PluginHook.BEFORE_LLM, PluginHook.BEFORE_RESPONSE]

    async def execute(self, context: HookContext) -> HookContext:
        state = context.agent_state
        if context.hook == PluginHook.BEFORE_LLM:
            msgs = _compress_window_messages(state.messages, self.config)
            msgs = _slice_recent_messages_by_human(
                msgs,
                self.config.recent_context_human_messages,
            )
            msgs = normalize_messages_for_model(msgs)
            state.extra["llm_messages"] = msgs
        elif context.hook == PluginHook.BEFORE_RESPONSE:
            msgs = _compress_window_messages(state.messages, self.config)
            msgs = _slice_recent_messages_by_human(
                msgs,
                self.config.checkpoint_human_messages,
            )
            state.messages = msgs
            state.extra.pop("llm_messages", None)
        return context
