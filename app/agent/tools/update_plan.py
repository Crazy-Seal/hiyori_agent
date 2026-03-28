from langchain.tools import tool
from langgraph.prebuilt import ToolRuntime

from app.agent.utils.log import log_tool_call
from app.agent.utils.todo_manager import TodoManager

@tool
@log_tool_call()
def update_plan(items: list[dict], tool_runtime: ToolRuntime) -> str:
    """
    更新编程任务的待办事项列表。更新时，禁止修改id和text字段，仅更改status字段。
    只能有一个待办事项处于in_progress状态，其他必须是pending或completed状态。

    Args:
        items: 列表，最多20项，每项为一个字典，包含"id"（序号），"text"（任务描述）和"status"（pending / in_progress / completed）字段。
        格式示例：{
            "items": [
                {
                    "id": "1",
                    "text": "查看已有代码",
                    "status": "completed"
                },
                {
                    "id": "2",
                    "text": "编写代码",
                    "status": "in_progress"
                },
                {
                    "id": "3",
                    "text": "代码审查",
                    "status": "pending"
                }
            ]
        }
    """
    try:
        # 用 TodoManager 统一做合法性校验与渲染。
        todo_manager = TodoManager()
        todo_view = todo_manager.update(items)
        # 回写到子图状态，供后续节点与 checkpoint 使用。
        tool_runtime.state.todo_items = list(todo_manager.items)
        return "待办事项列表已更新\n" + todo_view
    except Exception as e:
        return f"错误: {e}"