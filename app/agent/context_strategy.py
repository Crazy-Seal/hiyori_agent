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
    """上下文窗口的保留数量和图片生命周期配置。"""

    recent_context_human_messages: int = Field(default=10, ge=1)
    max_images_in_context: int = Field(default=5, ge=0)
    image_ttl_human_messages: int = Field(default=10, ge=0)
    max_screenshots_in_context: int = Field(default=2, ge=0)
    screenshot_ttl_human_messages: int = Field(default=2, ge=0)

    @property
    def checkpoint_human_messages(self) -> int:
        """Checkpoint 比模型窗口多保留 10 轮真人消息，便于恢复和记忆处理。"""
        return self.recent_context_human_messages + 10


_COMPRESSED_SCREENSHOT_PLACEHOLDER = "[系统消息]已被压缩的旧截图"
_COMPRESSED_IMAGE_PLACEHOLDER = "[系统消息]已被压缩的旧图片"


def _compressed_screenshot(message: dict) -> dict:
    """将一条原始截图消息替换为轻量文本占位符。

    除 content 和 name 外保留原消息的其他元数据，避免压缩图片时丢失
    message_time 等与图片内容无关的信息。
    """
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


def _compress_screenshot_messages(
    messages: list[dict],
    config: ContextStrategyConfig | None = None,
) -> list[dict]:
    """按截图专用 TTL 和数量上限压缩系统截图。

    第一遍按后续真人消息数判断截图是否过期；第二遍再执行数量上限，
    从仍未过期的截图中优先压缩最旧的部分。这里不会处理用户图片或
    MCP 工具图片，它们由普通图片链路负责。
    """
    config = config or ContextStrategyConfig()
    result = list(messages)

    # TTL 只按截图之后出现的真实用户消息计数，系统注入消息不推进 TTL。
    for index, message in enumerate(messages):
        if not (is_user_message(message) and message.get("name") == SCREENSHOT_MESSAGE_NAME):
            continue
        human_count_after = sum(1 for later in messages[index + 1:] if is_real_human_message(later))
        if human_count_after >= config.screenshot_ttl_human_messages:
            result[index] = _compressed_screenshot(message)

    # 对未因 TTL 过期的原始截图继续执行最大保留数量限制。
    screenshot_indices = [
        index for index, message in enumerate(result)
        if is_user_message(message) and message.get("name") == SCREENSHOT_MESSAGE_NAME
    ]
    excess = len(screenshot_indices) - config.max_screenshots_in_context
    for index in screenshot_indices[:max(excess, 0)]:
        result[index] = _compressed_screenshot(result[index])
    return result


def _is_plain_user_image_message(message: dict) -> bool:
    """判断消息是否进入“普通图片”管理链路。

    普通图片包括真实用户上传图片和 MCP 工具返回图片。两者都使用
    image_ttl_human_messages/max_images_in_context。系统截图拥有独立配置，
    因此在这里明确排除。content 必须是列表，因为 OpenAI 多模态消息
    通过由 text、image_url 等内容块组成的列表表达。
    """
    return (
        is_user_message(message)
        and message.get("name") not in {SCREENSHOT_MESSAGE_NAME, SCREENSHOT_COMPRESSED_NAME}
        and isinstance(message.get("content"), list)
    )


def _image_part_refs(messages: list[dict]) -> list[tuple[int, int]]:
    """收集所有普通图片内容块的位置。

    返回值中的每一项是 ``(消息下标, content 内容块下标)``，后续可以
    精确替换某张图片，而不影响同一消息内的文字或其他图片。
    """
    refs: list[tuple[int, int]] = []
    for message_index, message in enumerate(messages):
        if not _is_plain_user_image_message(message):
            continue
        for part_index, part in enumerate(message.get("content") or []):
            if isinstance(part, dict) and part.get("type") == "image_url":
                refs.append((message_index, part_index))
    return refs


def _compress_image_part(message: dict, part_index: int) -> None:
    """把指定 image_url 内容块原地替换为文本占位符。

    如果消息已经带有 image_description，则保留该摘要，让模型在图片
    原始数据被移除后仍能获得必要的语义信息。
    """
    content = message.get("content")
    if not isinstance(content, list) or part_index >= len(content):
        return
    placeholder = _COMPRESSED_IMAGE_PLACEHOLDER
    image_description = message.get("image_description")
    if isinstance(image_description, str) and image_description.strip():
        placeholder = f"{placeholder}。图片摘要：{image_description.strip()}"
    content[part_index] = {"type": "text", "text": placeholder}


def _compress_user_image_messages(
    messages: list[dict],
    config: ContextStrategyConfig,
) -> list[dict]:
    """按普通图片 TTL 和总数限制压缩用户图片及 MCP 图片。

    函数先深拷贝消息，确保构建模型窗口时不会修改持久化状态；然后先
    压缩超过真人轮次 TTL 的图片，再从剩余图片中按时间顺序压缩超出
    max_images_in_context 的最旧图片。
    """
    result = deepcopy(messages)
    compressed: set[tuple[int, int]] = set()
    refs = _image_part_refs(result)

    # MCP 图片本身不是真人消息，但它的寿命仍由之后的真人消息数推进。
    for message_index, part_index in refs:
        human_count_after = sum(1 for later in result[message_index + 1:] if is_real_human_message(later))
        if human_count_after >= config.image_ttl_human_messages:
            _compress_image_part(result[message_index], part_index)
            compressed.add((message_index, part_index))

    # TTL 处理后，对仍保留的用户图片和 MCP 图片共同应用一个数量上限。
    remaining_refs = [ref for ref in refs if ref not in compressed]
    excess = len(remaining_refs) - config.max_images_in_context
    for message_index, part_index in remaining_refs[:max(excess, 0)]:
        _compress_image_part(result[message_index], part_index)
    return result


def _compress_window_messages(
    messages: list[dict],
    config: ContextStrategyConfig | None = None,
) -> list[dict]:
    """依次执行截图链路和普通图片链路，生成图片压缩后的消息窗口。"""
    config = config or ContextStrategyConfig()
    return _compress_user_image_messages(_compress_screenshot_messages(messages, config), config)


def _slice_recent_messages_by_human(
    messages: list[dict],
    max_human_messages: int = 10,
) -> list[dict]:
    """以真实用户消息为轮次锚点，保留最近若干轮及其后的全部消息。

    从后向前找到第 ``max_human_messages`` 条真人输入后直接切片，因此
    与这些用户轮次关联的 assistant、tool、截图和 MCP 图片都会保留，
    但系统注入的 user 消息不会被错误计为新一轮对话。
    """
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
    """根据统一配置构建模型输入窗口和持久化 checkpoint 窗口。"""

    def __init__(self, config: ContextStrategyConfig) -> None:
        """保存不可变的窗口策略配置。"""
        self.config = config

    def build_model_window(self, messages: list[dict]) -> list[dict]:
        """构建本次发给模型的短窗口，并补充时间、规范化消息格式。"""
        compressed = _compress_window_messages(messages, self.config)
        sliced = _slice_recent_messages_by_human(
            compressed,
            self.config.recent_context_human_messages,
        )
        return normalize_messages_for_model(project_messages_with_time(sliced))

    def build_checkpoint_window(
        self,
        messages: list[dict],
        *,
        memory_human_floor: int = 0,
    ) -> list[dict]:
        """构建 checkpoint 窗口，并满足记忆插件要求的最低真人轮次数。"""
        compressed = _compress_window_messages(messages, self.config)
        return _slice_recent_messages_by_human(
            compressed,
            max(self.config.checkpoint_human_messages, memory_human_floor),
        )


class ContextStrategyManager:
    """面向 AgentState 的上下文策略入口。"""

    def __init__(self, config: ContextStrategyConfig) -> None:
        """根据配置创建统一的窗口策略。"""
        self.policy = ContextWindowPolicy(config)

    def build_model_window(self, state: AgentState) -> list[dict]:
        """从当前 AgentState 生成模型调用使用的临时消息窗口。"""
        return self.policy.build_model_window(state.messages)

    def compact_checkpoint(self, state: AgentState, *, memory_human_floor: int = 0) -> None:
        """原地压缩 AgentState，只保留 checkpoint 所需的消息范围。"""
        state.messages = self.policy.build_checkpoint_window(
            state.messages,
            memory_human_floor=memory_human_floor,
        )
