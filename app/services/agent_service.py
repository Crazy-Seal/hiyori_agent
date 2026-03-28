from datetime import datetime
from typing import Callable, Iterator

from app.agent.graph import invoke_agent_stream
from app.config.config import get_chat_settings
from app.crud.chat_history_dao import ChatHistoryDao
from app.schemas.chat_settings import ChatSettings


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
        if isinstance(content, list):
            text_parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        text_parts.append(text)
            return "".join(text_parts)
        return ""

    def get_health_data(self, session_id: str) -> dict[str, str]:
        chat_settings = self.chat_settings_loader(session_id)
        return {
            "status": "ok",
            "model": chat_settings.model_name,
        }

    def stream_chat(self, user_message: str, session_id: str = "default") -> Iterator[str]:
        chat_settings = self.chat_settings_loader(session_id)
        timed_user_message = self._build_timed_user_message(user_message)

        response_parts: list[str] = []
        for chunk in invoke_agent_stream(timed_user_message, chat_settings):
            text = self._extract_text(chunk.content)
            if not text:
                continue
            response_parts.append(text)
            yield text

        if response_parts:
            self.chat_history_dao.save_chat_message(session_id, "Human", user_message)
            self.chat_history_dao.save_chat_message(session_id, "AI", "".join(response_parts))