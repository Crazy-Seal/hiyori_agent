from functools import lru_cache
from pathlib import Path
from typing import Annotated, Iterator, cast, Any
import logging
import sqlite3

from langchain_core.messages import AIMessage, AIMessageChunk, AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import BaseModel, SecretStr

from app.agent.memory.memory import (
    enqueue_memory_finalize_task,
    get_last_human_text,
    get_latest_short_memory,
    get_store,
)
from app.agent.tools import get_tools
from app.agent.utils.log import shorten_for_log
from app.agent.utils.messages import normalize_messages_for_model
from app.agent.utils.work_memory import slice_recent_messages_by_human
from app.schemas.chat_settings import ChatSettings


logger = logging.getLogger(__name__)
# checkpoint: 保存 LangGraph 每个 session 的短期状态（messages、计数器）
CHECKPOINT_DB_PATH = Path(__file__).resolve().parents[2] / "memory" / "sqlite" / "checkpoints.sqlite3"
MAX_HUMAN_MESSAGES_IN_CHECKPOINT = 100
SUMMARY_EVERY_HUMAN_MESSAGES = 10
# 每次聊天使用的短期记忆窗口
RECENT_CONTEXT_HUMAN_MESSAGES = 10


def reduce_messages_keep_recent_humans(
    left: list[AnyMessage],
    right: list[AnyMessage] | AnyMessage,
) -> list[AnyMessage]:
    """合并 LangGraph 消息并截断为最近固定轮次 Human 窗口。"""
    merged = add_messages(left, right)
    return slice_recent_messages_by_human(
        merged,
        max_human_messages=MAX_HUMAN_MESSAGES_IN_CHECKPOINT,
    )


class AgentState(BaseModel):
    # LangGraph 状态：messages 在每个节点执行后自动累加
    messages: Annotated[list[AnyMessage], reduce_messages_keep_recent_humans]
    chat_settings: ChatSettings
    # 每次用户发言结束后 +1，达到阈值触发一次记忆后台任务
    summary_counter: int = 0
    # 缓存当次聊天的短期记忆和长期记忆，避免重复检索
    short_memory: str | None = None
    memory_text: str | None = None


@lru_cache(maxsize=1)
def get_checkpointer() -> SqliteSaver:
    """存储检查点的 SqliteSaver 实例。"""
    CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(CHECKPOINT_DB_PATH), check_same_thread=False)
    return SqliteSaver(conn)


@lru_cache
def get_model(chat_settings: ChatSettings, stream_tokens: bool = False) -> ChatOpenAI:
    """基于会话配置构建主对话模型，并按 tools_list 动态绑定工具。"""
    model = ChatOpenAI(
        model=chat_settings.model_name,
        base_url=chat_settings.openai_base_url,
        api_key=SecretStr(chat_settings.openai_api_key),
        temperature=chat_settings.temperature,
        streaming=stream_tokens,
    )
    if chat_settings.tools_list:
        tools = get_tools(chat_settings.tools_list)
        model = model.bind_tools(tools)
    return model


def call_model(state: AgentState, config: RunnableConfig | None = None):
    """组装系统提示与短期上下文，检索记忆后调用主模型生成回复。"""
    configurable = (config or {}).get("configurable", {}) if isinstance(config, dict) else {}
    stream_tokens = bool(configurable.get("stream_tokens", False))
    model = get_model(state.chat_settings, stream_tokens=stream_tokens)
    recent_messages = slice_recent_messages_by_human(
        state.messages,
        max_human_messages=RECENT_CONTEXT_HUMAN_MESSAGES,
    )
    recent_messages = normalize_messages_for_model(recent_messages)

    # 本轮对话第一次进入chatbot节点时，才检索并附加长期记忆；后续进入则复用之前的结果。
    if state.memory_text is None:
        store = get_store()
        namespace = ("long_mem", state.chat_settings.session_id)
        recall_query = get_last_human_text(recent_messages)
        memories = store.search(namespace, query=recall_query, limit=3)
        state.memory_text = "\n".join(item.value.get("text", "") for item in memories if isinstance(item.value, dict))

    # 本轮对话第一次进入chatbot节点时，才检索并附加短期记忆；后续进入则复用之前的结果。
    if state.short_memory is None:
        state.short_memory = get_latest_short_memory(state.chat_settings.session_id)

    # 组装系统提示词
    system_prompt = state.chat_settings.system_prompt
    if state.short_memory:
        system_prompt = f"{system_prompt}\n\n[之前对话的短期记忆摘要]\n{state.short_memory}"
    if state.memory_text:
        system_prompt = f"{system_prompt}\n\n[检索到的相关长期记忆]\n{state.memory_text}"

    messages = [SystemMessage(content=system_prompt)] + recent_messages
    response = model.invoke(messages)
    return {"messages": [response]}


def memory_finalize(state: AgentState):
    """轻量收尾节点：仅维护计数器并按阈值投递后台记忆任务。"""
    next_counter = state.summary_counter + 1
    if next_counter < SUMMARY_EVERY_HUMAN_MESSAGES:
        return {"summary_counter": next_counter}

    enqueue_memory_finalize_task(state.chat_settings, list(state.messages))
    return {"summary_counter": 0}


@lru_cache
def build_graph(chat_settings: ChatSettings):
    """按当前会话配置构建并编译 LangGraph 流程图。"""
    tools = get_tools(chat_settings.tools_list)

    def chatbot(state: AgentState, config: RunnableConfig):
        return call_model(state, config)

    builder = StateGraph(AgentState)
    builder.add_node("chatbot", chatbot)
    builder.add_node("tools", ToolNode(tools=tools))
    builder.add_node("memory_finalize", memory_finalize)

    builder.add_edge(START, "chatbot")
    builder.add_conditional_edges(
        "chatbot",
        tools_condition,
        {"tools": "tools", "__end__": "memory_finalize"},
    )
    builder.add_edge("tools", "chatbot")
    builder.add_edge("memory_finalize", END)

    return builder.compile(checkpointer=get_checkpointer(), store=get_store())


def invoke_agent_stream(
    user_message: str,
    chat_settings: ChatSettings,
) -> Iterator[AIMessage | AIMessageChunk]:
    """流式调用入口：仅透传 chatbot 节点的 AI 输出分片。"""
    active_session_id = chat_settings.session_id
    logger.info("[Agent][session=%s] 收到流式消息: %s", active_session_id, shorten_for_log(user_message))

    graph = build_graph(chat_settings)
    config: RunnableConfig = {
        "configurable": {
            "thread_id": active_session_id,
            "stream_tokens": True,
            "short_memory": None,
            "memory_text": None,
        }
    }

    for chunk, metadata in graph.stream(
        cast(Any, {
            "messages": [HumanMessage(content=user_message)],
            "chat_settings": chat_settings,
        }),
        config=config,
        stream_mode="messages",
    ):
        node_name = metadata.get("langgraph_node") if isinstance(metadata, dict) else None
        if node_name != "chatbot":
            continue
        if isinstance(chunk, (AIMessage, AIMessageChunk)):
            yield chunk


def get_thread_checkpoint_watermark(thread_id: str, checkpoint_ns: str = "") -> int:
    """调用agent前，先查询当前会话在checkpoint表中的最大rowid，出错时回滚用"""
    CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(CHECKPOINT_DB_PATH)) as conn:
        row = conn.execute(
            """
            SELECT COALESCE(MAX(rowid), 0)
            FROM checkpoints
            WHERE thread_id = ? AND checkpoint_ns = ?
            """,
            (thread_id, checkpoint_ns),
        ).fetchone()
    return int(row[0]) if row else 0


def rollback_thread_checkpoints_after(
    thread_id: str,
    baseline_rowid: int,
    checkpoint_ns: str = "",
) -> tuple[int, int]:
    """回滚本轮会话的checkpoint"""
    # 删除缓存，确保后续 graph 构建和执行时能正确反映 checkpoint 的回滚结果。
    build_graph.cache_clear()

    CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(CHECKPOINT_DB_PATH)) as conn:
        # 先查询出需要删除的 checkpoint_id 列表
        checkpoint_ids = [
            row[0]
            for row in conn.execute(
                """
                SELECT checkpoint_id
                FROM checkpoints
                WHERE thread_id = ? AND checkpoint_ns = ? AND rowid > ?
                """,
                (thread_id, checkpoint_ns, baseline_rowid),
            ).fetchall()
        ]

        # 删除 writes 表中关联的写入记录
        deleted_writes = 0
        if checkpoint_ids:
            placeholders = ",".join("?" for _ in checkpoint_ids)
            params = [thread_id, checkpoint_ns, *checkpoint_ids]
            write_cursor = conn.execute(
                f"""
                DELETE FROM writes
                WHERE thread_id = ?
                  AND checkpoint_ns = ?
                  AND checkpoint_id IN ({placeholders})
                """,
                params,
            )
            deleted_writes = int(write_cursor.rowcount)
        # 删除 checkpoints 表中对应的 checkpoint 记录
        checkpoint_cursor = conn.execute(
            """
            DELETE FROM checkpoints
            WHERE thread_id = ? AND checkpoint_ns = ? AND rowid > ?
            """,
            (thread_id, checkpoint_ns, baseline_rowid),
        )
        deleted_checkpoints = int(checkpoint_cursor.rowcount)
        conn.commit()

    return deleted_checkpoints, deleted_writes
