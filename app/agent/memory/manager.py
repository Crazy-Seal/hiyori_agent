"""记忆管理器 - 核心调度层"""

import asyncio
import logging
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any

from app.agent.memory.config import MemoryConfig
from app.agent.memory.memories.episodic import EpisodicMemory
from app.agent.memory.memories.semantic_mem0 import Mem0SemanticMemory
from app.agent.memory.memories.summary import SummaryMemory
from app.agent.memory.store.chat_history_store import ChatHistoryStore
from app.agent.message import Message, MessageRole
from app.agent.utils.domain.text import extract_text
from app.crud.chat_settings_dao import ChatSettingsDao
from app.schemas.chat_settings import MEMORY_DEFAULT_CONFIG, ChatSettings

logger = logging.getLogger(__name__)


class MemoryManager:
    """记忆管理器

    职责：
    - 统一管理三种记忆类型
    - 提供统一的添加/检索接口
    - 组装记忆上下文

    关键概念：
    - 摘要：当天聊天记录的阶段性总结，每10/20/30...条用户消息触发一次
    - 日记：当天完整聊天记录的总结，检查最后一个有记录的日期没有日记就生成
    - 情景记忆/语义记忆：每次 add() 都处理，实时生成

    时间规则：
    - 使用配置的时区（默认系统时区）
    - 凌晨 N 点前算前一天，N 点后算当天
    """

    def __init__(
        self,
        session_id: str,
        config: MemoryConfig | None = None,
        chat_settings: ChatSettings | None = None,
    ):
        self.session_id = session_id
        self.config = config or MemoryConfig.from_env()

        # 加载 ChatSettings
        if chat_settings:
            self.chat_settings = chat_settings
        else:
            chat_settings_dao = ChatSettingsDao()
            self.chat_settings = chat_settings_dao.get_chat_settings(session_id)
        self.memory_options = self._memory_options()

        # 初始化存储层
        self.chat_history_store = ChatHistoryStore(
            timezone=self.config.timezone,
            day_boundary_hour=self.config.day_boundary_hour,
        )

        # 按开关初始化三种长期记忆；聊天记录存储始终启用。
        self.summary_memory = (
            SummaryMemory(
                session_id, self.config, self.chat_settings, self.chat_history_store
            )
            if self.memory_options.get("enable_diary", True)
            else None
        )
        self.episodic_memory = (
            EpisodicMemory(session_id, self.config, self.chat_settings)
            if self.memory_options.get("enable_episodic", True)
            else None
        )

        # 初始化语义记忆
        if not self.memory_options.get("enable_semantic", True):
            self.semantic_memory = None
        else:
            self.semantic_memory = Mem0SemanticMemory(
                session_id, self.config, self.chat_settings
            )

    # ==================== 核心方法 ====================

    async def add(
        self,
        messages: list[Message],
        history: list[Message] | None = None,
        *,
        enable_episodic: bool = True,
        enable_semantic: bool = True,
    ) -> dict[str, int]:
        """添加记忆 - 只处理情景记忆和语义记忆

        Args:
            messages: 当前聊天记录
            history: 历史聊天记录（用于前情提要）

        Returns:
            添加结果，如 {"episodic": 3, "semantic": 2}
        """
        # 格式化消息
        messages_text = self._format_messages(messages)
        history_text = self._format_messages(history) if history else ""

        async def process_episodic() -> int:
            """处理情景记忆"""
            if not enable_episodic or self.episodic_memory is None:
                return 0
            try:
                episodic_ids = await self.episodic_memory.add(messages_text, history_text)
                return len(episodic_ids)
            except Exception as e:
                logger.warning("[MemoryManager] 情景记忆处理失败: %s", e)
                return 0

        async def process_semantic() -> int:
            """处理语义记忆"""
            if not enable_semantic or self.semantic_memory is None:
                return 0
            try:
                semantic_ids = await self.semantic_memory.add(messages, history)
                return len(semantic_ids)
            except Exception as e:
                logger.warning("[MemoryManager] 语义记忆处理失败: %s", e)
                return 0

        # 并行处理情景记忆和语义记忆
        episodic_count, semantic_count = await asyncio.gather(
            process_episodic(),
            process_semantic(),
        )

        return {"episodic": episodic_count, "semantic": semantic_count}

    async def try_summary(
        self,
        user_message: str,
        ai_messages: list[dict[str, Any]],
        image_description: str | None = None,
        image_filenames: list[str] | None = None,
        *,
        enable_diary: bool = True,
    ) -> None:
        """触发摘要/日记检查，核心聊天记录由 checkpoint 事务保存。

        在每次 agent 响应完成后调用

        Args:
            user_message: 用户消息
            ai_messages: AI 消息列表，每条包含 content 和 tool_calls
            image_description: 图片描述（可选）
            image_filenames: 图片文件名列表（可选）
        """
        now = datetime.now(self.config.timezone)
        today = self._get_effective_date(now)

        # 聊天历史已随 checkpoint 原子提交，此处只处理派生记忆。
        if enable_diary and self.summary_memory is not None:
            await self.summary_memory.check_and_generate(today)

    async def get_context(
        self,
        query: str = "",
        *,
        include_diary: bool = True,
        include_episodic: bool = True,
        include_semantic: bool = True,
    ) -> str:
        """获取当前对话上下文

        组装顺序：
        1. 前两天摘要/日记 + 今日摘要
        2. 相关情景记忆（需要 query）
        3. 相关语义记忆

        Args:
            query: 查询文本，用于检索相关情景记忆

        Returns:
            格式化的上下文字符串
        """
        parts = []

        # 计算今天的有效日期
        now = datetime.now(self.config.timezone)
        today = self._get_effective_date(now)

        # 1. 摘要部分
        if include_diary and self.summary_memory is not None:
            summary_context = await self.summary_memory.get_context(today)
            if summary_context:
                parts.append(f"[你的历史日记和摘要]\n{summary_context}\n")

        # 2. 情景记忆
        if include_episodic and self.episodic_memory is not None and query.strip():
            episodic_memories = await self.episodic_memory.search(query, self.config.episodic_top_k)
            if episodic_memories:
                memory_texts = [f"- {m.content}（{m.timestamp.strftime('%Y-%m-%d')}）" for m in episodic_memories]
                parts.append(f"[相关情景记忆]\n" + "\n".join(memory_texts) + "\n")

        # 3. 语义记忆
        if include_semantic and self.semantic_memory is not None and query.strip():
            try:
                semantic_memories = await self.semantic_memory.search(query, top_k=3)
                if semantic_memories:
                    memory_texts = []
                    for m in semantic_memories:
                        subject = m.metadata.get("subject", "")
                        relation = m.metadata.get("relation", "")
                        obj = m.metadata.get("obj", "")
                        if subject and relation and obj:
                            memory_texts.append(f"- {subject} {relation} {obj}")
                        else:
                            memory_texts.append(f"- {m.content}")
                    parts.append(f"[相关语义知识]\n" + "\n".join(memory_texts))
            except Exception as e:
                logger.warning("[MemoryManager] 语义记忆检索失败: %s", e)

        return "\n\n".join(parts) if parts else ""

    async def search(
        self,
        query: str,
        memory_type: str,
        top_k: int = 3,
    ) -> str:
        """搜索相关记忆

        Args:
            query: 查询文本
            memory_type: 记忆类型 (episodic/semantic/all)
            top_k: 返回数量

        Returns:
            格式化的记忆文本
        """
        results = []
        memory_options = self._memory_options()
        enable_episodic = bool(memory_options.get("enable_episodic", True))
        enable_semantic = bool(memory_options.get("enable_semantic", True))

        async def search_episodic():
            if (
                not enable_episodic
                or self.episodic_memory is None
                or memory_type not in ("episodic", "all")
            ):
                return []
            return await self.episodic_memory.search(query, top_k)

        async def search_semantic():
            if (
                not enable_semantic
                or self.semantic_memory is None
                or memory_type not in ("semantic", "all")
            ):
                return []
            try:
                return await self.semantic_memory.search(query, top_k)
            except Exception as e:
                logger.warning("[MemoryManager] 语义记忆检索失败: %s", e)
                return []

        # 并行检索
        episodic, semantic = await asyncio.gather(
            search_episodic(),
            search_semantic(),
        )

        results.extend([f"[情景记忆] {m.content}（{m.timestamp.strftime('%Y-%m-%d')}）" for m in episodic])
        results.extend([f"[语义记忆] {m.content}" for m in semantic])

        return "\n".join(results) if results else "未找到相关记忆"

    async def search_diary(self, start: date, end: date) -> str:
        """搜索时间范围内的日记

        Args:
            start: 开始日期
            end: 结束日期（最多间隔5天）

        Returns:
            日记内容

        Raises:
            ValueError: 时间范围超过5天
        """
        if self.summary_memory is None:
            return "日记记忆未启用"

        if (end - start).days > 5:
            raise ValueError("时间范围不能超过5天")

        diaries = await self.summary_memory.search_diary(start, end)
        if not diaries:
            return "该时间范围内没有日记"

        return "\n\n".join(
            f"【{d}】\n{content}"
            for d, content in diaries
        )

    # ==================== 日期相关方法 ====================

    def _get_effective_date(self, now: datetime) -> date:
        """获取有效日期

        凌晨 N 点前算前一天，N 点后算当天
        """
        if now.hour < self.config.day_boundary_hour:
            return (now - timedelta(days=1)).date()
        return now.date()

    def _memory_options(self) -> dict[str, Any]:
        memory = self.chat_settings.agent_plugins.get("memory")
        config = dict(MEMORY_DEFAULT_CONFIG)
        if memory:
            config.update(memory.config)
            if not memory.enabled:
                config["enable_diary"] = False
                config["enable_episodic"] = False
                config["enable_semantic"] = False
        return config

    # ==================== 工具方法 ====================

    def _format_messages(self, messages: list[Message]) -> str:
        """格式化消息列表为文本

        只保留用户和 AI 的普通对话，过滤掉：
        - Tool 消息
        - System 消息

        对于工具调用的 AI 消息，简化为 "[调用了工具: xxx]" 格式
        """
        if not messages:
            return ""
        user_name = self.chat_settings.address or "用户"
        ai_name = self.chat_settings.name or "AI"
        lines = []
        for msg in messages:
            if msg.role == MessageRole.USER:
                role = user_name
                # 提取文本内容
                content = extract_text(msg.content)
            elif msg.role == MessageRole.ASSISTANT:
                role = ai_name
                # 检查是否有工具调用
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    tool_names = [tc.name for tc in msg.tool_calls]
                    content = f"[调用了工具: {', '.join(tool_names)}]"
                else:
                    content = extract_text(msg.content)
            else:
                # 跳过 system、tool 等其他类型
                continue
            lines.append(f"{role}: {content}")
        return "\n".join(lines)


# ==================== 工厂函数 ====================

@lru_cache(maxsize=32)
def get_memory_manager(session_id: str) -> MemoryManager:
    """获取或创建 MemoryManager 实例（带缓存）"""
    config = MemoryConfig.from_env()
    chat_settings = ChatSettingsDao().get_chat_settings(session_id)
    return MemoryManager(session_id, config, chat_settings)
