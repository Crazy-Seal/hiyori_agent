from langchain.tools import tool

from app.agent.utils.log import log_tool_call
from app.agent.utils.safe_path import safe_path

@tool
@log_tool_call()
def read_file(path: str, limit: int = None) -> str:
    """读取指定路径的文件内容，并返回字符串结果。最多返回50000字符。

    Args:
        path: 被读取的文件路径字符串。
        limit: 可选参数，最多返回的行数。
    """

    try:
        text = safe_path(path).read_text()
        lines = text.splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... (剩余{len(lines) - limit}行被省略)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"错误: {e}"