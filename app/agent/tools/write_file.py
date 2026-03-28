from langchain.tools import tool

from app.agent.utils.log import log_tool_call
from app.agent.utils.safe_path import safe_path

@tool
@log_tool_call()
def write_file(path: str, content: str) -> str:
    """在指定路径写入内容，如果文件不存在则创建。会覆盖原有内容。

    Args:
        path: 被写入的文件路径字符串。
        content: 要写入文件的内容字符串。
    """
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        return f"在{path}中写入了{len(content)}字节的内容。"
    except Exception as e:
        return f"错误: {e}"