from langchain.tools import tool
from langgraph.prebuilt import ToolRuntime
from typing import Any, cast

from app.agent.subgraph_for_coding import invoke_coding_subgraph
from app.agent.utils.log import log_tool_call
from app.agent.utils.todo_manager import TodoManager


def _parse_todo_items(raw_items: str) -> list[dict[str, str]]:
    """把多行原始待办文本解析为 TodoManager.update 所需结构。"""
    # 每个非空行转换成一个待办项，id 从 1 递增，初始状态固定为 pending。
    items: list[dict[str, str]] = []
    for line in raw_items.splitlines():
        text = line.strip()
        if not text:
            continue
        items.append({"id": str(len(items) + 1), "text": text, "status": "pending"})
    return items


@tool
@log_tool_call()
def plan_and_coding(raw_items: str, command: str, runtime: ToolRuntime) -> str:
    """
    创建编程任务的待办事项列表，并命令编程专家agent进行编程。
    请将编程任务精确地拆解成多个待办事项，任务代码量大时，可将其按不同模块拆分成多个待办事项。

    Args:
        raw_items: 编程任务的待办事项列表，每行一项，最多20项。如："检查并准备环境\n创建文件并写入代码\n运行代码"
        command: 字符串，对编程专家下的命令，如：“用python画一个爱心”
    """
    try:
        # 先构建并校验待办管理器，作为子图状态的一部分传入。
        items = _parse_todo_items(raw_items)
        todo_manager = TodoManager()
        todo_view = todo_manager.update(items)
    except Exception as e:
        return f"错误: {e}"
    try:
        # 从父图 runtime 中取出 chat_settings，确保子图沿用同一会话配置。
        chat_settings = cast(Any, runtime.state).chat_settings
        result = invoke_coding_subgraph(
            command=command,
            todo_manager=todo_manager,
            chat_settings=chat_settings,
        )
        # 返回给父图的结果里保留计划和执行输出，便于用户查看。
        return f"[编程专家回复]\n{result}"
    except Exception as e:
        return f"编程专家出错: {e}"
