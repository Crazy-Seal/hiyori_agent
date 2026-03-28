from langchain.tools import tool

from app.agent.utils.log import log_tool_call
from app.agent.utils.safe_path import safe_path

@tool
@log_tool_call()
def delete_file(path: str) -> str:
    """删除指定路径的文件或文件夹。

    Args:
        path: 被删除的文件/文件夹路径字符串。
    """
    try:
        fp = safe_path(path)
        if not fp.exists():
            return f"错误: {path}不存在。"

        fp.unlink()
        return f"已删除{path}"
    except Exception as e:
        return f"错误: {e}"