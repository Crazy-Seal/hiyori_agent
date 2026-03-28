from langchain_core.messages import AnyMessage, HumanMessage


def slice_recent_messages_by_human(messages: list[AnyMessage], max_human_messages: int = 10) -> list[AnyMessage]:
    """控制工作记忆，从后往前数到第 max_human_messages 条 HumanMessage，并保留该条到结尾的所有消息。"""
    human_count = 0
    start_index = 0

    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            human_count += 1
            if human_count == max_human_messages:
                start_index = index
                break

    return messages[start_index:]