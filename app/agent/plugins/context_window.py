"""上下文窗口插件。

把窗口管理拆成两个钩子：
- BEFORE_LLM：构造「送模型窗口」（截图压缩 + 保留最近 10 条人类消息 + 规范化），
  写入 state.extra["llm_messages"]，供 pipeline._build_messages 使用；不改 state.messages。
- BEFORE_RESPONSE：对 state.messages 做「checkpoint 裁剪」（截图压缩 + 保留最近 20 条人类消息），
  控制持久化体积。

不在送模型前直接改 state.messages——以免记忆抽取丢失完整历史。
"""

import logging

from app.agent.context import BasePlugin, PluginHook, HookContext
from app.agent.message import (
    SCREENSHOT_COMPRESSED_NAME,
    SCREENSHOT_MESSAGE_NAME,
    is_real_human_message,
    is_user_message,
)
from app.agent.utils.domain.text import normalize_messages_for_model

logger = logging.getLogger(__name__)

MAX_HUMAN_MESSAGES_IN_CHECKPOINT = 20
RECENT_CONTEXT_HUMAN_MESSAGES = 10
SCREENSHOT_TTL_HUMAN_MESSAGES = 2
MAX_SCREENSHOTS_IN_CONTEXT = 2

_COMPRESSED_PLACEHOLDER = "[系统消息]已被压缩的旧截图"


def _compressed_screenshot() -> dict:
    return {
        "role": "user",
        "content": _COMPRESSED_PLACEHOLDER,
        "name": SCREENSHOT_COMPRESSED_NAME,
    }


def _compress_screenshot_messages(messages: list[dict]) -> list[dict]:
    """按 TTL 和最大数量压缩上下文中的截图消息。"""
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
        if human_count_after >= SCREENSHOT_TTL_HUMAN_MESSAGES:
            result[index] = _compressed_screenshot()

    screenshot_indices = [
        index
        for index, message in enumerate(result)
        if is_user_message(message)
        and message.get("name") == SCREENSHOT_MESSAGE_NAME
    ]
    excess = len(screenshot_indices) - MAX_SCREENSHOTS_IN_CONTEXT
    for index in screenshot_indices[:max(excess, 0)]:
        result[index] = _compressed_screenshot()

    return result


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
    version = "1.0.0"
    priority = 200  # 晚于 MemoryPlugin(100)，确保 BEFORE_RESPONSE 时记忆已读到完整历史

    @property
    def hooks(self) -> list[PluginHook]:
        return [PluginHook.BEFORE_LLM, PluginHook.BEFORE_RESPONSE]

    async def execute(self, context: HookContext) -> HookContext:
        state = context.agent_state
        if context.hook == PluginHook.BEFORE_LLM:
            msgs = _compress_screenshot_messages(state.messages)
            msgs = _slice_recent_messages_by_human(
                msgs,
                RECENT_CONTEXT_HUMAN_MESSAGES,
            )
            msgs = normalize_messages_for_model(msgs)
            state.extra["llm_messages"] = msgs
        elif context.hook == PluginHook.BEFORE_RESPONSE:
            msgs = _compress_screenshot_messages(state.messages)
            msgs = _slice_recent_messages_by_human(
                msgs,
                MAX_HUMAN_MESSAGES_IN_CHECKPOINT,
            )
            state.messages = msgs
            state.extra.pop("llm_messages", None)
        return context
