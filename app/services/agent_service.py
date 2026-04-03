from datetime import datetime
from typing import Callable, Iterator
import logging

from app.agent.graph import (
    invoke_agent_stream,
    get_thread_checkpoint_watermark,
    rollback_thread_checkpoints_after,
)
from app.config.config import get_chat_settings
from app.crud.chat_history_dao import ChatHistoryDao
from app.schemas.chat_settings import ChatSettings


logger = logging.getLogger(__name__)


class AgentService:
    def __init__(
        self,
        chat_history_dao: ChatHistoryDao,
        chat_settings_loader: Callable[[str], ChatSettings] = get_chat_settings,
    ):
        self.chat_history_dao = chat_history_dao
        self.chat_settings_loader = chat_settings_loader

    @staticmethod
    def _build_timed_user_message(user_message: str) -> str:
        """将本地时间写入用户消息，便于模型感知时间演进。"""
        now = datetime.now().astimezone()
        weekday_text = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][now.weekday()]
        now_text = f"{now.strftime('%Y-%m-%d %H:%M:%S %z')} {weekday_text}"
        return f"[{now_text}] {user_message}"

    @staticmethod
    def _extract_text(content: object) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            text = content.get("text")
            if isinstance(text, str):
                return text
            return ""
        if isinstance(content, list):
            text_parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    text_parts.append(item)
                    continue
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        text_parts.append(text)
            return "".join(text_parts)

        # 兼容 LangChain message/chunk 的 text 属性/方法
        if hasattr(content, "text"):
            text_attr = getattr(content, "text")
            if isinstance(text_attr, str):
                return text_attr
            if callable(text_attr):  # 兼容旧版 .text()
                text = text_attr()
                if isinstance(text, str):
                    return text
        return ""

    def get_health_data(self, session_id: str) -> dict[str, str]:
        chat_settings = self.chat_settings_loader(session_id)
        return {
            "status": "ok",
            "model": chat_settings.model_name,
        }

    @staticmethod
    def _rollback_checkpoints(session_id: str, checkpoint_baseline: int) -> tuple[int, int]:
        try:
            return rollback_thread_checkpoints_after(session_id, checkpoint_baseline)
        except Exception:
            logger.exception("[AgentService][session=%s] checkpoints回滚失败", session_id)
            return 0, 0

    def stream_chat(self, user_message: str, session_id: str = "default") -> Iterator[str]:
        chat_settings = self.chat_settings_loader(session_id)
        timed_user_message = self._build_timed_user_message(user_message)

        checkpoint_baseline = get_thread_checkpoint_watermark(session_id)

        response_parts: list[str] = []
        try:
            for chunk in invoke_agent_stream(timed_user_message, chat_settings):
                text = self._extract_text(chunk.content)
                if not text:
                    text = self._extract_text(chunk)
                if not text:
                    continue
                response_parts.append(text)
                yield text
        except Exception:
            logger.exception("[AgentService][session=%s] graph运行中出现错误，尝试回滚checkpoints", session_id)
            self._rollback_checkpoints(session_id, checkpoint_baseline)
            yield "[错误：agent调用异常]"
            return

        ai_message = "".join(response_parts)
        if not ai_message.strip():
            deleted_checkpoints, deleted_writes = self._rollback_checkpoints(session_id, checkpoint_baseline)
            logger.warning(
                "[AgentService][session=%s] 模型输出空，已回滚 checkpoints=%d, writes=%d",
                session_id,
                deleted_checkpoints,
                deleted_writes,
            )
            yield "[错误：未返回内容]"
            return

        self.chat_history_dao.save_chat_message(session_id, "Human", user_message)
        self.chat_history_dao.save_chat_message(session_id, "AI", ai_message)
