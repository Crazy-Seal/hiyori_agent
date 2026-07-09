"""消息文本处理（OpenAI dict 版）。

适配 agent：消息为 OpenAI 风格的 dict（含 "role"/"content"/"name" 等字段），
不依赖 LangChain 消息类型。包含：
- 文本提取（extract_text，兼容 dict 项与带 .text 的对象）
- 人类消息定位/上下文切分（截图不计入人类消息）
- 模型消息规范化（normalize_messages_for_model）
"""

import logging

from app.agent.message import is_real_human_message, is_user_message

logger = logging.getLogger(__name__)


def extract_text(content: object) -> str:
    """从模型消息 content 中提取纯文本。

    兼容三种输入：纯字符串、OpenAI 风格 dict 列表（取 "text" 字段）、
    以及带 `.text` 属性的对象列表（如 ContentPart）。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            text = item.get("text") if isinstance(item, dict) else getattr(item, "text", None)
            if isinstance(text, str) and text:
                text_parts.append(text)
        return "".join(text_parts)
    return ""


def get_last_human_text(messages: list[dict]) -> str:
    """反向查找最近一条用户消息文本。

    注意：截图消息不计入用户消息。
    """
    for msg in reversed(messages):
        if is_real_human_message(msg):
            return extract_text(msg.get("content"))
    return ""


def split_context(
    messages: list[dict],
    later_human_count: int,
    previous_human_count: int,
) -> tuple[list[dict], list[dict]]:
    """把上下文切分成"前情提要段"和"待总结段"。

    Args:
        messages: 消息列表（OpenAI dict 格式）
        later_human_count: 待提取的人类消息数量
        previous_human_count: 前情提要的人类消息数量

    Returns:
        (前情提要消息, 待提取消息)

    注意：截图消息不计入人类消息计数。
    """
    # 过滤截图消息后的人类消息索引
    human_indices = [
        idx for idx, msg in enumerate(messages)
        if is_real_human_message(msg)
    ]
    if not human_indices:
        return [], []

    later_start_human_pos = max(len(human_indices) - later_human_count, 0)
    later_start_idx = human_indices[later_start_human_pos]
    later_messages = messages[later_start_idx:]

    before_messages = messages[:later_start_idx]
    before_human_indices = [
        idx for idx, msg in enumerate(before_messages)
        if is_real_human_message(msg)
    ]
    if not before_human_indices:
        return [], later_messages

    previous_start_human_pos = max(len(before_human_indices) - previous_human_count, 0)
    previous_start_idx = before_human_indices[previous_start_human_pos]
    previous_tail_messages = before_messages[previous_start_idx:]
    return previous_tail_messages, later_messages


def extract_multimodal_signals(messages: list[dict]) -> list[str]:
    """从消息中提取可持久化的多模态信号文本。"""
    signals: list[str] = []
    for msg in messages:
        if not is_user_message(msg):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type", "")).strip() or "unknown"
            if item_type == "text":
                continue
            payload = {k: v for k, v in item.items() if k != "text"}
            signals.append(f"多模态输入[{item_type}]：{payload}")
    return signals


def normalize_messages_for_model(messages: list[dict]) -> list[dict]:
    """规范化消息：修正/丢弃非法的 tool 消息，避免被部分网关（如 Gemini 兼容层）拒绝。

    - 为缺 name 的 tool 消息回填工具名（从前面的 assistant.tool_calls 推断）
    - 实在无法确定工具名的 tool 消息直接丢弃
    """
    normalized: list[dict] = []
    tool_call_names: dict[str, str] = {}

    for original_message in messages:
        message = {
            key: value
            for key, value in original_message.items()
            if not key.startswith("_")
            and key not in {"image_description", "image_filenames"}
        }
        role = message.get("role")

        if role == "assistant":
            for tool_call in message.get("tool_calls") or []:
                tc_id = tool_call.get("id")
                fn = tool_call.get("function") or {}
                fn_name = fn.get("name")
                if tc_id and fn_name:
                    tool_call_names[tc_id] = fn_name
            normalized.append(message)
            continue

        if role == "tool":
            tool_name = message.get("name")
            if not tool_name and message.get("tool_call_id"):
                tool_name = tool_call_names.get(message["tool_call_id"])

            if not tool_name:
                logger.warning(
                    "[Agent] 丢弃无 name 的 tool 消息，tool_call_id=%s",
                    message.get("tool_call_id"),
                )
                continue

            if tool_name != message.get("name"):
                message = {**message, "name": tool_name}

        normalized.append(message)

    return normalized
