import logging

from langchain_core.messages import AIMessage, AnyMessage, ToolMessage

logger = logging.getLogger(__name__)
def normalize_messages_for_model(messages: list[AnyMessage]) -> list[AnyMessage]:
    """修正工具消息顺序/字段，避免向模型发送非法 function_response。"""
    normalized: list[AnyMessage] = []
    tool_call_names: dict[str, str] = {}

    for message in messages:
        if isinstance(message, AIMessage):
            for tool_call in message.tool_calls:
                tool_call_id = tool_call.get("id")
                tool_name = tool_call.get("name")
                if tool_call_id and tool_name:
                    tool_call_names[tool_call_id] = tool_name
            normalized.append(message)
            continue

        if isinstance(message, ToolMessage):
            tool_name = message.name
            if not tool_name and message.tool_call_id:
                tool_name = tool_call_names.get(message.tool_call_id)

            # 缺少工具名的 ToolMessage 会被 Gemini 拒绝，直接丢弃该条脏数据。
            if not tool_name:
                logger.warning(
                    "[Agent] 丢弃无 name 的 ToolMessage，tool_call_id=%s",
                    message.tool_call_id,
                )
                continue

            if tool_name != message.name:
                message = ToolMessage(
                    content=message.content,
                    tool_call_id=message.tool_call_id,
                    name=tool_name,
                    additional_kwargs=message.additional_kwargs,
                    response_metadata=message.response_metadata,
                    id=message.id,
                )

        normalized.append(message)

    return normalized

