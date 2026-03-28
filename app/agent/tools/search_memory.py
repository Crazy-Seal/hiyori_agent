from langchain.tools import tool
from langgraph.prebuilt import ToolRuntime
from app.agent.utils.log import log_tool_call


@tool
@log_tool_call()
def search_memory(
    query: str,
    runtime: ToolRuntime
) -> str:
    """在长期记忆中搜索相关信息，并返回最相近的5条。

    Args:
        query: 搜索关键词/关键句。
    """
    try:
        store = runtime.store
        session_id = runtime.state.chat_settings.session_id
        if not query or not query.strip():
            return "错误: query不能为空。"
        if session_id is None:
            return "错误: 缺少会话id信息，无法定位长期记忆。"

        namespace = ("long_mem", session_id)
        items = store.search(namespace, query=query.strip(), limit=5)

        lines: list[str] = []
        for idx, item in enumerate(items, start=1):
            text = ""
            if isinstance(item.value, dict):
                text = str(item.value.get("text", "")).strip()
            if not text:
                continue
            score = f"{item.score:.4f}" if item.score is not None else "N/A"
            lines.append(f"{idx}. {text} (score={score})")

        if not lines:
            return "未找到有效的长期记忆内容。"
        return "检索到的长期记忆:\n" + "\n".join(lines)
    except Exception as e:
        return f"错误: {e}"
