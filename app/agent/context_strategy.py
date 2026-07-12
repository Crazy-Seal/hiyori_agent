"""Agent 必经的上下文窗口策略。"""

from copy import deepcopy

from pydantic import BaseModel, Field

from app.agent.message import (
    SCREENSHOT_COMPRESSED_NAME,
    SCREENSHOT_MESSAGE_NAME,
    is_real_human_message,
    is_user_message,
)
from app.agent.state import AgentState
from app.agent.message_time import project_messages_with_time
from app.agent.utils.domain.text import normalize_messages_for_model


class ContextStrategyConfig(BaseModel):
    recent_context_human_messages: int = Field(default=10, ge=1)
    max_images_in_context: int = Field(default=5, ge=0)
    image_ttl_human_messages: int = Field(default=10, ge=0)
    max_screenshots_in_context: int = Field(default=2, ge=0)
    screenshot_ttl_human_messages: int = Field(default=2, ge=0)

    @property
    def checkpoint_human_messages(self) -> int:
        return self.recent_context_human_messages + 10


_COMPRESSED_SCREENSHOT_PLACEHOLDER = "[系统消息]已被压缩的旧截图"
_COMPRESSED_IMAGE_PLACEHOLDER = "[系统消息]已被压缩的旧图片"


def _compressed_screenshot(message: dict) -> dict:
    result = {
        key: deepcopy(value)
        for key, value in message.items()
        if key not in {"content", "name"}
    }
    result.update({
        "role": "user",
        "content": _COMPRESSED_SCREENSHOT_PLACEHOLDER,
        "name": SCREENSHOT_COMPRESSED_NAME,
    })
    return result


def _compress_screenshot_messages(messages: list[dict], config: ContextStrategyConfig | None = None) -> list[dict]:
    config = config or ContextStrategyConfig()
    result = list(messages)
    for index, message in enumerate(messages):
        if not (is_user_message(message) and message.get("name") == SCREENSHOT_MESSAGE_NAME):
            continue
        human_count_after = sum(1 for later in messages[index + 1:] if is_real_human_message(later))
        if human_count_after >= config.screenshot_ttl_human_messages:
            result[index] = _compressed_screenshot(message)
    screenshot_indices = [
        index for index, message in enumerate(result)
        if is_user_message(message) and message.get("name") == SCREENSHOT_MESSAGE_NAME
    ]
    excess = len(screenshot_indices) - config.max_screenshots_in_context
    for index in screenshot_indices[:max(excess, 0)]:
        result[index] = _compressed_screenshot(result[index])
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
    content[part_index] = {"type": "text", "text": placeholder}


def _compress_user_image_messages(messages: list[dict], config: ContextStrategyConfig) -> list[dict]:
    result = deepcopy(messages)
    compressed: set[tuple[int, int]] = set()
    refs = _image_part_refs(result)
    for message_index, part_index in refs:
        human_count_after = sum(1 for later in result[message_index + 1:] if is_real_human_message(later))
        if human_count_after >= config.image_ttl_human_messages:
            _compress_image_part(result[message_index], part_index)
            compressed.add((message_index, part_index))
    remaining_refs = [ref for ref in refs if ref not in compressed]
    excess = len(remaining_refs) - config.max_images_in_context
    for message_index, part_index in remaining_refs[:max(excess, 0)]:
        _compress_image_part(result[message_index], part_index)
    return result


def _compress_window_messages(messages: list[dict], config: ContextStrategyConfig | None = None) -> list[dict]:
    config = config or ContextStrategyConfig()
    return _compress_user_image_messages(_compress_screenshot_messages(messages, config), config)


def _slice_recent_messages_by_human(messages: list[dict], max_human_messages: int = 10) -> list[dict]:
    human_count = 0
    start_index = 0
    for index in range(len(messages) - 1, -1, -1):
        if is_real_human_message(messages[index]):
            human_count += 1
            if human_count == max_human_messages:
                start_index = index
                break
    return messages[start_index:]


class ContextWindowPolicy:
    def __init__(self, config: ContextStrategyConfig) -> None:
        self.config = config

    def build_model_window(self, messages: list[dict]) -> list[dict]:
        compressed = _compress_window_messages(messages, self.config)
        sliced = _slice_recent_messages_by_human(compressed, self.config.recent_context_human_messages)
        return normalize_messages_for_model(project_messages_with_time(sliced))

    def build_checkpoint_window(self, messages: list[dict], *, memory_human_floor: int = 0) -> list[dict]:
        compressed = _compress_window_messages(messages, self.config)
        return _slice_recent_messages_by_human(
            compressed,
            max(self.config.checkpoint_human_messages, memory_human_floor),
        )


class ContextStrategyManager:
    def __init__(self, config: ContextStrategyConfig) -> None:
        self.policy = ContextWindowPolicy(config)

    def build_model_window(self, state: AgentState) -> list[dict]:
        return self.policy.build_model_window(state.messages)

    def compact_checkpoint(self, state: AgentState, *, memory_human_floor: int = 0) -> None:
        state.messages = self.policy.build_checkpoint_window(
            state.messages,
            memory_human_floor=memory_human_floor,
        )
