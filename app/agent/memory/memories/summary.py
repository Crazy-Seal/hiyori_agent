"""摘要记忆 - 按日期存储摘要和日记"""

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

from app.agent.memory.config import MemoryConfig
from app.agent.memory.store.chat_history_store import ChatHistoryStore
from app.agent.memory.store.diary_sqlite_store import DiarySqliteStore
from app.agent.models.llm_client import LLMClient, LLMConfig
from app.schemas.chat_settings import ChatSettings

logger = logging.getLogger(__name__)


class SummaryMemory:
    """摘要记忆类

    职责：
    - 按日期存储对话摘要和日记
    - 检查触发条件，调用 LLM 生成摘要/日记
    - 提供上下文组装

    关键概念：
    - 摘要：当天聊天记录的阶段性总结，每天只保留一条（覆盖更新）
    - 日记：当天完整聊天记录的总结，一天只有一条日记

    触发规则：
    - 日记：最后一个有聊天记录的日期（排除今天）没有日记时触发
    - 摘要：今天的用户消息数达到阈值（10/20/30...）时触发
    """

    def __init__(
        self,
        session_id: str,
        config: MemoryConfig,
        chat_settings: ChatSettings,
        chat_history_store: ChatHistoryStore,
    ):
        self.session_id = session_id
        self.config = config
        self.chat_settings = chat_settings
        self.chat_history_store = chat_history_store
        self.store = DiarySqliteStore(config.sqlite_path)
        self._summary_lock = asyncio.Lock()

        # 初始化 LLM
        self.llm = LLMClient(LLMConfig(
            model=chat_settings.model_name,
            api_key=chat_settings.openai_api_key,
            base_url=chat_settings.openai_base_url,
            temperature=0.2,
            timeout=60.0,
        ))

    # ==================== 核心方法 ====================

    async def check_and_generate(self, today: date) -> None:
        """检查并触发生成摘要/日记

        Args:
            today: 今天的有效日期（需调用方传入，考虑时区和分界点规则）
        """
        # 1. 日记检查：最后一个有聊天记录的日期（排除今天）是否有日记
        await self._check_and_generate_diary(today)

        # 2. 摘要检查：今天的用户消息数是否达到阈值
        await self._check_and_generate_summary(today)

    async def add(self, date_obj: date, content: str, is_diary: bool = False) -> int:
        """添加摘要或日记

        Args:
            date_obj: 日期
            content: 内容
            is_diary: 是否为日记

        Returns:
            记录ID
        """
        return await self.store.add(
            session_id=self.session_id,
            date_obj=date_obj,
            content=content,
            is_diary=is_diary,
        )

    # ==================== 查询方法 ====================

    async def search(self, date_obj: date, is_diary: bool = False) -> str | None:
        """获取指定日期的摘要或日记

        Args:
            date_obj: 日期
            is_diary: 是否查询日记

        Returns:
            内容，不存在则返回 None
        """
        return await self.store.get(
            session_id=self.session_id,
            date_obj=date_obj,
            is_diary=is_diary,
        )

    async def has_summary(self, date_obj: date) -> bool:
        """检查指定日期是否有摘要"""
        return await self.store.exists(
            session_id=self.session_id,
            date_obj=date_obj,
            is_diary=False,
        )

    async def has_diary(self, date_obj: date) -> bool:
        """检查指定日期是否有日记"""
        return await self.store.exists(
            session_id=self.session_id,
            date_obj=date_obj,
            is_diary=True,
        )

    async def search_diary(self, start: date, end: date) -> list[tuple[date, str]]:
        """搜索时间范围内的日记

        Args:
            start: 开始日期
            end: 结束日期

        Returns:
            (日期, 内容) 列表（按日期升序）
        """
        return await self.store.get_range(
            session_id=self.session_id,
            start=start,
            end=end,
            is_diary=True,
        )

    # ==================== 上下文组装 ====================

    async def get_context(self, today: date) -> str:
        """获取当前对话上下文

        组装规则：
        1. 从今天往前数，取最近的 2 条日记，并生成缺失日期说明
        2. 今日有摘要则用摘要，没有则为空

        Args:
            today: 今天的有效日期

        Returns:
            上下文字符串
        """
        parts = []

        # 获取今天之前的最近 2 条日记
        previous_diaries = await self.store.get_recent_before_date(
            session_id=self.session_id,
            before_date=today,
            n=2,
            is_diary=True,
        )

        # 使用 _format_diaries_with_gaps 格式化日记并生成缺失日期说明
        diary_text, diary_gaps = self._format_diaries_with_gaps(
            previous_diaries, today
        )

        # 如果有日记内容，添加到 parts
        if previous_diaries:
            parts.append(diary_text)
            if diary_gaps.strip():
                parts.append(diary_gaps.strip())

        # 获取今日摘要
        today_content = await self.search(today, is_diary=False)
        if today_content:
            parts.append(f"【今天】\n{today_content}")

        return "\n\n".join(parts) if parts else ""

    # ==================== 检查和生成逻辑 ====================

    async def _check_and_generate_diary(self, today: date) -> None:
        """检查并生成日记"""
        last_chat_date = await self.chat_history_store.get_last_chat_date(
            self.session_id, exclude_today=today
        )
        if not last_chat_date:
            return

        has_diary = await self.has_diary(last_chat_date)
        if has_diary:
            return

        messages = await self.chat_history_store.get_messages_by_date(
            self.session_id, last_chat_date
        )
        if not messages:
            return

        logger.info(
            "[SummaryMemory] 检测到 %s 缺少日记，开始生成",
            last_chat_date
        )
        await self._generate_diary(last_chat_date, messages)

    async def _check_and_generate_summary(self, today: date) -> None:
        """检查并生成摘要"""
        async with self._summary_lock:
            today_count = await self.chat_history_store.get_message_count_by_date(
                self.session_id, today, role="Human"
            )
            summarized_count = await self.store.get_summary_progress(
                self.session_id,
                today,
            )
            interval = self.config.summary_every_messages
            next_threshold = ((summarized_count // interval) + 1) * interval
            if today_count < next_threshold:
                return

            messages = await self.chat_history_store.get_messages_by_date(
                self.session_id, today
            )
            if not messages:
                return

            logger.info(
                "[SummaryMemory] 今日用户消息数达到 %d，开始生成摘要",
                today_count
            )
            await self._generate_summary(today, messages, today_count)

    # ==================== LLM 生成 ====================

    async def _generate_summary(
        self,
        target_date: date,
        messages: list[dict[str, Any]],
        summarized_human_count: int,
    ) -> None:
        """生成指定日期的摘要"""
        prompt = await self._build_system_prompt(messages, target_date, "对话摘要")
        try:
            response = await self.llm.ainvoke(
                messages=[{"role": "user", "content": prompt}]
            )
            summary_content = response.content
            await self.store.add_summary_with_progress(
                session_id=self.session_id,
                date_obj=target_date,
                content=summary_content,
                summarized_human_count=summarized_human_count,
            )
            logger.info(
                "[SummaryMemory] 摘要生成成功: date=%s, length=%d",
                target_date, len(summary_content)
            )
        except Exception:
            logger.exception("[SummaryMemory] 生成摘要失败")

    async def _generate_diary(
        self,
        target_date: date,
        messages: list[dict[str, Any]],
    ) -> None:
        """生成指定日期的日记"""
        prompt = await self._build_system_prompt(messages, target_date, "日记")
        try:
            response = await self.llm.ainvoke(
                messages=[{"role": "user", "content": prompt}]
            )
            diary_content = response.content
            await self.add(target_date, diary_content, is_diary=True)
            logger.info(
                "[SummaryMemory] 日记生成成功: date=%s, length=%d",
                target_date, len(diary_content)
            )
        except Exception:
            logger.exception("[SummaryMemory] 生成日记失败")

    # ==================== 提示词构建 ====================

    async def _build_system_prompt(
        self,
        messages: list[dict[str, Any]],
        target_date: date,
        summary_type: str
    ) -> str:
        """构建摘要提示词"""
        # 差异化提示
        difference_prompt = f"这是你的日记，没有人会偷看，所以你可以尽情地记录你和{self.chat_settings.address}在这一天共度的点点滴滴，也可以记录下自己的心里话和情绪。" if summary_type == "日记" else f"要求保留你和{self.chat_settings.address}之间的重要交流、发生的主要事情，并忽略无意义闲聊。"

        # 格式化聊天记录
        chat_text = self._format_messages(messages)

        # 获取之前的日记（2条）
        previous_diaries = await self.store.get_recent_before_date(
            session_id=self.session_id,
            before_date=target_date,
            n=2,
            is_diary=True,
        )
        # 构建日记文本（包含缺失日期说明）
        diary_text, diary_gaps = self._format_diaries_with_gaps(
            previous_diaries, target_date
        )

        # 获取之前的对话记录（10条，约5轮）
        previous_messages = await self.chat_history_store.get_messages_before_date(
            session_id=self.session_id,
            before_date=target_date,
            limit=10,
        )
        if previous_messages:
            prev_chat_text = self._format_messages(previous_messages)
        else:
            prev_chat_text = f"这是你和{self.chat_settings.address}第一天交流，暂无"

        return f"""你是{self.chat_settings.name}，一个{self.chat_settings.feature}的{self.chat_settings.character}，称呼用户为{self.chat_settings.address}。

{self.chat_settings.characteristic}

请以{self.chat_settings.name}的第一人称视角，基于你之前的日记、{target_date}之前最后的对话记录、{target_date}的对话，
将{target_date}这一天的对话记录为一段连续、自然的{summary_type}（200字以内）。
{difference_prompt}
注意：提供之前的日记、{target_date}之前最后的对话记录只是为了让你更好的理解上下文，不要将这些内容重复总结。禁止改变对话意思，禁止添加原文没有的信息、事件或关系，用中文输出，只输出一段话。

之前的日记：
{diary_text}
{diary_gaps}
{target_date}之前的最后的对话记录：
{prev_chat_text}

{target_date}的对话内容（需要你记录的部分）：
{chat_text}

请生成{summary_type}（300字以内）："""

    def _format_diaries_with_gaps(
        self,
        diaries: list[tuple[date, str]],
        target_date: date,
    ) -> tuple[str, str]:
        """格式化日记并生成缺失日期说明

        Args:
            diaries: 日记列表 [(日期, 内容), ...]，按日期降序
            target_date: 目标日期

        Returns:
            (日记文本, 缺失日期说明)
        """
        if not diaries:
            return "你还没有写过日记，暂无", ""

        # 按日期升序排列
        diaries_sorted = sorted(diaries, key=lambda x: x[0])

        # 构建日记文本
        diary_parts = [f"【{d}】\n{c}" for d, c in diaries_sorted]
        diary_text = "\n\n".join(diary_parts)

        # 计算缺失日期（没有日记 = 没有交互）
        diary_dates = set(d for d, _ in diaries)

        # 从 target_date 前一天往前检查，直到最早的日记日期（不含）
        check_date = target_date - timedelta(days=1)
        earliest_diary = diaries_sorted[0][0]

        # 收集连续缺失区间 [(start, end), ...]，其中 start > end
        gap_ranges: list[tuple[date, date]] = []
        current_gap_start: date | None = None

        while check_date > earliest_diary:
            if check_date not in diary_dates:
                if current_gap_start is None:
                    current_gap_start = check_date
            else:
                if current_gap_start is not None:
                    gap_ranges.append((current_gap_start, check_date + timedelta(days=1)))
                    current_gap_start = None
            check_date -= timedelta(days=1)

        # 处理最后一个 gap
        if current_gap_start is not None:
            gap_ranges.append((current_gap_start, earliest_diary + timedelta(days=1)))

        # 生成缺失说明
        gap_descriptions = []
        for gap_start, gap_end in gap_ranges:
            if gap_start == gap_end:
                gap_descriptions.append(f"{gap_start}没有与{self.chat_settings.address}交互")
            else:
                gap_descriptions.append(
                    f"{gap_end}至{gap_start}没有与{self.chat_settings.address}交互"
                )

        if gap_descriptions:
            gap_text = "\n（注：" + "；".join(gap_descriptions) + "）\n\n"
        else:
            gap_text = "\n\n"

        return diary_text, gap_text

    # ==================== 工具方法 ====================

    def _format_messages(self, messages: list[dict[str, Any]]) -> str:
        """格式化聊天记录为文本"""
        if not messages:
            return ""
        user_name = self.chat_settings.address or "用户"
        ai_name = self.chat_settings.name or "AI"
        lines = []

        for msg in messages:
            role_value = msg["role"]

            # 过滤工具调用消息
            if role_value == "AI_Tool_Calling":
                continue

            if role_value == "Human":
                role = user_name
            else:
                role = ai_name

            # 处理图片描述
            content = msg["content"]
            image_description = msg.get("image_description")
            if image_description:
                content = f"[发送了图片：{image_description}] {content}"

            timestamp = msg.get("timestamp", "")
            if timestamp:
                lines.append(f"[{timestamp}] {role}: {content}")
            else:
                lines.append(f"{role}: {content}")
        return "\n".join(lines)
