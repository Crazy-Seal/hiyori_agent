from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, cast
import sqlite3

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import BaseModel, SecretStr

from app.agent.tools import get_subgraph_tools
from app.config.config import get_coding_model_settings

from app.agent.utils.messages import normalize_messages_for_model
from app.agent.utils.todo_manager import TodoManager
from app.agent.utils.work_memory import slice_recent_messages_by_human
from app.schemas.chat_settings import ChatSettings


# 子图 checkpoint 独立存储路径，避免和主图短期记忆冲突。
CHECKPOINT_DB_PATH = Path(__file__).resolve().parents[2] / "memory" / "sqlite" / "subgraph_for_coding.sqlite3"
# 子图状态中最多保留的人类消息轮次（用于 checkpoint 压缩）。
MAX_HUMAN_MESSAGES_IN_CHECKPOINT = 50
# 每次喂给模型的最近人类消息窗口大小。
RECENT_CONTEXT_HUMAN_MESSAGES = 5

# 子图可调用工具由 app.agent.tools.get_subgraph_tools 统一管理。


def reduce_messages_keep_recent_humans(
    left: list[AnyMessage],
    right: list[AnyMessage] | AnyMessage,
) -> list[AnyMessage]:
    """合并子图消息并截断为最近固定轮次 Human 窗口。"""
    merged = add_messages(left, right)
    return slice_recent_messages_by_human(
        merged,
        max_human_messages=MAX_HUMAN_MESSAGES_IN_CHECKPOINT,
    )


class CodingSubgraphState(BaseModel):
    # 子图运行时消息状态：使用 reducer 自动合并并裁剪历史消息。
    messages: Annotated[list[AnyMessage], reduce_messages_keep_recent_humans]
    # 当前会话模型配置。
    chat_settings: ChatSettings
    # 可序列化的待办事项列表，供 checkpoint 持久化。
    todo_items: list[dict[str, str]]


@lru_cache(maxsize=1)
def get_subgraph_checkpointer() -> SqliteSaver:
    """创建并缓存子图专用 checkpoint 存储器。"""
    CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(CHECKPOINT_DB_PATH), check_same_thread=False)
    return SqliteSaver(conn)


@lru_cache
def get_subgraph_model(stream_tokens: bool = False) -> ChatOpenAI:
    """读取 settings.yaml 中的编程模型配置并创建子图模型。"""
    coding_settings = get_coding_model_settings()
    model = ChatOpenAI(
        model=str(coding_settings["model"]),
        base_url=str(coding_settings["base_url"]),
        api_key=SecretStr(str(coding_settings["api_key"])),
        temperature=float(coding_settings["temperature"]),
        streaming=stream_tokens,
    )
    tools = get_subgraph_tools()
    if tools:
        model = model.bind_tools(tools)
    return model


def call_subgraph_model(state: CodingSubgraphState, config: RunnableConfig | None = None):
    """子图核心推理节点：拼装上下文后调用模型。"""
    configurable = (config or {}).get("configurable", {}) if isinstance(config, dict) else {}
    stream_tokens = bool(configurable.get("stream_tokens", False))
    model = get_subgraph_model(stream_tokens=stream_tokens)

    # 仅保留最近窗口消息，降低 token 开销。
    recent_messages = slice_recent_messages_by_human(
        state.messages,
        max_human_messages=RECENT_CONTEXT_HUMAN_MESSAGES,
    )
    # 清洗消息，避免工具消息格式异常影响模型调用。
    recent_messages = normalize_messages_for_model(recent_messages)

    # 从状态里的 todo_items 还原计划视图，注入系统提示。
    todo_manager = TodoManager()
    todo_view = todo_manager.update(state.todo_items)
    system_prompt = (
        "你是专注执行编码任务的编程专家。"
        "你会根据用户给出的待办事项列表和命令，逐步完成编程任务。"
        "编程时请调用工具，并优先给出可执行结果。如缺少依赖，可根据错误提示安装后重试。"
        "conda环境和工作目录都已经为你准备好，你可以直接执行命令和生成文件。"
        "每完成一条待办事项，必须调用工具更新待办事项列表的状态。"
        "回答用户时，如执行成功直接回复完成，如执行失败回复错误原因，回复禁止多于30字"
        f"\n\n[编码计划]\n{todo_view}"
    )
    messages = [SystemMessage(content=system_prompt)] + recent_messages
    response = model.invoke(messages)
    return {"messages": [response]}


@lru_cache
def build_coding_subgraph(chat_settings: ChatSettings):
    """构建并编译子图：coding_chatbot -> coding_tools -> coding_chatbot。"""
    tools = get_subgraph_tools()

    def coding_chatbot(state: CodingSubgraphState, config: RunnableConfig):
        """子图聊天节点包装，便于接入 StateGraph。"""
        return call_subgraph_model(state, config)

    builder = StateGraph(CodingSubgraphState)
    # 使用 coding_ 前缀，避免在父图流式输出中过滤到子图节点事件。
    builder.add_node("coding_chatbot", coding_chatbot)
    builder.add_node("coding_tools", ToolNode(tools=tools))

    # 子图入口先走模型，再根据是否触发工具决定流转。
    builder.add_edge(START, "coding_chatbot")
    builder.add_conditional_edges(
        "coding_chatbot",
        tools_condition,
        {"tools": "coding_tools", "__end__": END},
    )
    # 工具执行后回到模型继续推理。
    builder.add_edge("coding_tools", "coding_chatbot")

    # 子图状态已改为可序列化结构，可安全挂载 checkpoint。
    return builder.compile(checkpointer=get_subgraph_checkpointer())


def _content_to_text(content: object) -> str:
    """把模型 content 统一提取为纯文本字符串。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def invoke_coding_subgraph(command: str, todo_manager: TodoManager, chat_settings: ChatSettings) -> str:
    """调用子图执行编码任务，并返回最后一条 AI 文本结果。"""
    graph = build_coding_subgraph(chat_settings)

    # 使用独立命名空间，后续若恢复子图 checkpoint 也可避免和父图串线。
    thread_id = f"{chat_settings.session_id}:coding"
    config: RunnableConfig = {
        "configurable": {
            "thread_id": thread_id,
            "stream_tokens": False,
        }
    }

    # 初始 state 注入可序列化 todo_items
    result = graph.invoke(
        cast(Any, {
            "messages": [HumanMessage(content=command)],
            "chat_settings": chat_settings,
            "todo_items": list(todo_manager.items),
        }),
        config=config,
    )

    # 取最后一条 AIMessage 作为子图输出。
    result_data = result if isinstance(result, dict) else result.model_dump()
    messages = result_data.get("messages", [])
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            text = _content_to_text(message.content).strip()
            return text if text else "[未返回内容]"
    return "[未返回内容]"
