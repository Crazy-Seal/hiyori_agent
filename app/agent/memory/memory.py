from functools import lru_cache
from pathlib import Path
from typing import Any
import logging
import re
import sqlite3
import time
from concurrent.futures import Future, ThreadPoolExecutor

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langgraph.store.sqlite import SqliteStore
from langgraph.store.sqlite.base import SqliteIndexConfig
from pydantic import SecretStr

from app.config.config import get_embedding_model_settings
from app.schemas.chat_settings import ChatSettings


logger = logging.getLogger(__name__)
STORE_DB_PATH = Path(__file__).resolve().parents[3] / "memory" / "sqlite" / "store.sqlite3"
CHECKPOINT_DB_PATH = Path(__file__).resolve().parents[3] / "memory" / "sqlite" / "checkpoints.sqlite3"
LONG_MEMORY_MERGE_SIMILARITY_THRESHOLD = 0.9
PREVIOUS_HUMAN_MESSAGES_FOR_SUMMARY = 5
LATER_HUMAN_MESSAGES_FOR_SUMMARY = 10
_summary_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="memory-summary")


# @lru_cache(maxsize=1)  # 注释掉，防止数据库并发冲突
def get_store() -> SqliteStore:
    """创建长期记忆向量存储。"""
    STORE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(STORE_DB_PATH), check_same_thread=False, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    embedding_settings = get_embedding_model_settings()
    index_config = SqliteIndexConfig(
        dims=int(embedding_settings["dimension"]),
        embed=OpenAIEmbeddings(
            model=str(embedding_settings["model"]),
            api_key=SecretStr(str(embedding_settings["api_key"])),
            base_url=str(embedding_settings["base_url"]),
            check_embedding_ctx_length=False,
            tiktoken_enabled=False,
        ),
        fields=["text"],
    )
    store = SqliteStore(conn=conn, index=index_config)
    store.setup()
    return store


@lru_cache
def get_summary_model(chat_settings: ChatSettings) -> ChatOpenAI:
    """构建用于记忆提取与融合的总结模型。"""
    return ChatOpenAI(
        model=chat_settings.model_name,
        base_url=chat_settings.openai_base_url,
        api_key=SecretStr(chat_settings.openai_api_key),
        temperature=0,
    )


def extract_text(content: object) -> str:
    """从模型消息 content 中提取纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    text_parts.append(text)
        return "".join(text_parts)
    return ""


def get_last_human_text(messages: list[AnyMessage]) -> str:
    """反向查找最近一条用户消息文本。"""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return extract_text(msg.content)
    return ""


def get_latest_short_memory(session_id: str) -> str:
    """读取会话最新一条短期记忆。"""
    STORE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(STORE_DB_PATH)) as conn:
        row = conn.execute(
            """
            SELECT content
            FROM short_memory
            WHERE thread_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
    return str(row[0]) if row else ""


def _save_short_memory(session_id: str, content: str) -> None:
    """写入一条新的短期记忆快照。"""
    STORE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(STORE_DB_PATH)) as conn:
        conn.execute(
            "INSERT INTO short_memory (thread_id, content) VALUES (?, ?)",
            (session_id, content),
        )
        conn.commit()


def _message_role_name(message: AnyMessage) -> str:
    """将消息类型映射为摘要提示中的角色名。"""
    if isinstance(message, HumanMessage):
        return "主人"
    if isinstance(message, AIMessage):
        return "助手"
    return "工具"


def _build_summary_source(messages: list[AnyMessage]) -> str:
    """把消息整理为“角色: 内容”文本，供总结模型使用。"""
    lines: list[str] = []
    for message in messages:
        text = extract_text(message.content)
        if text:
            lines.append(f"{_message_role_name(message)}: {text}")
    return "\n".join(lines)


def _split_context(
    messages: list[AnyMessage],
    later_human_count: int,
    previous_human_count: int,
) -> tuple[list[AnyMessage], list[AnyMessage]]:
    """把上下文切分成“前情提要段”和“待总结段”。"""
    human_indices = [idx for idx, msg in enumerate(messages) if isinstance(msg, HumanMessage)]
    if not human_indices:
        return [], []

    later_start_human_pos = max(len(human_indices) - later_human_count, 0)
    later_start_idx = human_indices[later_start_human_pos]
    later_messages = messages[later_start_idx:]

    before_messages = messages[:later_start_idx]
    before_human_indices = [idx for idx, msg in enumerate(before_messages) if isinstance(msg, HumanMessage)]
    if not before_human_indices:
        return [], later_messages

    previous_start_human_pos = max(len(before_human_indices) - previous_human_count, 0)
    previous_start_idx = before_human_indices[previous_start_human_pos]
    previous_tail_messages = before_messages[previous_start_idx:]
    return previous_tail_messages, later_messages


def _split_summary_items(summary_text: str) -> list[str]:
    """把多行摘要拆成独立记忆条目。"""
    items: list[str] = []
    for raw_line in summary_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[-*•]\s+", "", line)
        line = re.sub(r"^\d+[.)]\s+", "", line)
        if line:
            items.append(line)
    if items:
        return items
    line = summary_text.strip()
    return [line] if line else []


def _merge_long_memory_text(chat_settings: ChatSettings, existing_text: str, new_text: str) -> str:
    """融合两条相似长期记忆。"""
    if existing_text == new_text:
        return existing_text

    prompt = (
        "请把两条相似的长期记忆合并为一条更完整、去重后的记忆。"
        "保持事实准确，保留所有有效信息，不要新增原文没有的信息，只输出最终一条记忆。"
    )
    model = get_summary_model(chat_settings)
    response = model.invoke([
        SystemMessage(content=prompt),
        HumanMessage(content=f"已有记忆：{existing_text}\n新记忆：{new_text}"),
    ])
    merged_text = extract_text(response.content).strip()
    return merged_text if merged_text else f"{existing_text}；{new_text}"


def _upsert_long_memory_item(chat_settings: ChatSettings, memory_text: str) -> None:
    """相似则融合，否则新增长期记忆。"""
    store = get_store()
    namespace = ("long_mem", chat_settings.session_id)

    similar_items = store.search(namespace, query=memory_text, limit=1)
    top_item = similar_items[0] if similar_items else None
    if top_item and top_item.score is not None and top_item.score > LONG_MEMORY_MERGE_SIMILARITY_THRESHOLD:
        existing_text = ""
        if isinstance(top_item.value, dict):
            existing_text = str(top_item.value.get("text", ""))
        merged_text = _merge_long_memory_text(chat_settings, existing_text, memory_text)
        store.put(namespace, key=top_item.key, value={"text": merged_text})
        return

    key = f"summary:{time.time_ns()}"
    store.put(namespace, key=key, value={"text": memory_text})


def _summarize_and_store(
    chat_settings: ChatSettings,
    messages: list[AnyMessage],
    short_memory: str,
) -> None:
    """提取长期记忆条目并逐条写入向量存储。"""
    previous_tail_messages, later_messages = _split_context(
        messages,
        LATER_HUMAN_MESSAGES_FOR_SUMMARY,
        PREVIOUS_HUMAN_MESSAGES_FOR_SUMMARY,
    )
    previous_tail_source = _build_summary_source(previous_tail_messages)
    later_source = _build_summary_source(later_messages)
    if not previous_tail_source and not later_source:
        return

    prompt = (
        """你是记忆提取专家。请基于已有短期记忆、前情提要和要总结的对话，提取可长期存储的关键事实记忆，用自然流畅的语言记录。\n\n
身份说明：
- "主人"是使用AI的真人用户
- "助手"是AI助手（不是真人）

提取规则：
1. 用自然的中文描述，像写日记一样记录要点
2. 示例格式：
   主人常在晚上与AI互动，称呼AI为日和；喜欢听AI唱歌
   主人说自己生日是9月25日，希望AI记住
   主人最近在学Python，问了很多编程问题
   AI承诺帮主人提醒明天的会议
3. 多个相关要点可以用分号或逗号连接，较为不相关的要点需要分成不同的记忆条目，每条只记录一个事实或事件
4. 每条记忆15-80字，保留关键细节
5. 忽略无意义的闲聊（如"嗯"、"好的"、"知道了"）
6. 可以记忆以下内容，重要程度从高到低：
   - 生日、重大事件、用户核心偏好、用户特征
   - 习惯、经历、明确表态
   - 普通话题、临时想法
7. 注意：提供短期记忆和前情提要只是为了让你理解上下文，你只需要总结要总结的对话中的新信息
8. 禁止使用“现在”“最近”“目前”“正在”等表示现在进行时的时间词，以保持时间中立性
9. 可以提取0-5条记忆，返回多条记忆时使用换行分隔，不要输出额外解释。没有记忆要总结就返回None"""
    )
    model = get_summary_model(chat_settings)
    response = model.invoke([
        SystemMessage(content=prompt),
        HumanMessage(
            content=(
                f"已有短期记忆：\n{short_memory}\n\n"
                f"前情提要：\n{previous_tail_source}\n\n"
                f"要总结的对话：\n{later_source}"
            )
        ),
    ])
    summary_text = extract_text(response.content)
    if summary_text in ["None", "none", "NONE", ""]:
        return

    for item in _split_summary_items(summary_text):
        _upsert_long_memory_item(chat_settings, item)


def _summarize_short_memory(
    chat_settings: ChatSettings,
    messages: list[AnyMessage],
    previous_short_memory: str,
) -> str:
    """生成新的短期记忆段落。"""
    previous_tail_messages, later_messages = _split_context(
        messages,
        LATER_HUMAN_MESSAGES_FOR_SUMMARY,
        PREVIOUS_HUMAN_MESSAGES_FOR_SUMMARY,
    )
    previous_tail_source = _build_summary_source(previous_tail_messages)
    later_source = _build_summary_source(later_messages)
    if not previous_tail_source and not later_source:
        return previous_short_memory

    prompt = (
        "你是短期记忆归纳助手。请基于已有短期记忆、之前的对话结尾与之后的对话，"
        "将这些所有的记忆更新为一段连续、自然的新短期记忆（50-300字）。"
        "要求保留事件时间、事件摘要等重要细节，删除无意义闲聊，"
        "并确保和之前记忆衔接自然，不要重复堆砌。"
        "用中文输出，只输出一段话。"
        "如果字数过多，可以适量精简或删去时间较早的事件。"
        "禁止改变段落意思，禁止添加之前没有的信息或事件关系。"
    )
    model = get_summary_model(chat_settings)
    response = model.invoke([
        SystemMessage(content=prompt),
        HumanMessage(
            content=(
                f"已有短期记忆：\n{previous_short_memory}\n\n"
                f"之前的对话结尾（之前5轮）：\n{previous_tail_source}\n\n"
                f"之后的对话（最后10轮）：\n{later_source}"
            )
        ),
    ])
    short_memory_text = extract_text(response.content).strip()
    return short_memory_text if short_memory_text else previous_short_memory


def _run_memory_finalize(chat_settings: ChatSettings, messages: list[AnyMessage]) -> None:
    """执行一次完整的记忆收尾：先长期记忆，再写入新的短期记忆。"""
    previous_short_memory = get_latest_short_memory(chat_settings.session_id)
    _summarize_and_store(chat_settings, messages, previous_short_memory)
    new_short_memory = _summarize_short_memory(
        chat_settings,
        messages,
        previous_short_memory,
    )
    if new_short_memory and new_short_memory != previous_short_memory:
        _save_short_memory(chat_settings.session_id, new_short_memory)


def _log_future_error(future: Future[Any]) -> None:
    """记录后台任务异常，避免异常静默。"""
    try:
        future.result()
    except Exception:
        logger.exception("异步写入记忆失败")


def enqueue_memory_finalize_task(chat_settings: ChatSettings, messages: list[AnyMessage]) -> None:
    """投递记忆收尾任务到后台线程。"""
    future = _summary_executor.submit(_run_memory_finalize, chat_settings, list(messages))
    future.add_done_callback(_log_future_error)

