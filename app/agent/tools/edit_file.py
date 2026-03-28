from langchain.tools import tool

from app.agent.utils.log import log_tool_call
from app.agent.utils.safe_path import safe_path

@tool
@log_tool_call()
def edit_file(path: str, old_text: str, new_text: str) -> str:
    """将第一次出现处的旧文本替换为新文本

    Args:
        path: 被修改的文件路径字符串。
        old_text: 被替换的旧文本字符串。
        new_text: 替换后的新文本字符串。
    """
    try:
        fp = safe_path(path)
        content = fp.read_text(encoding="utf-8")
        if old_text not in content:
            return f"错误: {path}中不存在目标文本'{old_text}'。"
        fp.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
        return f"已修改{path}"
    except Exception as e:
        return f"错误: {e}"