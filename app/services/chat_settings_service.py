from app.crud.chat_settings_dao import ChatSettingsDao
from app.schemas.chat_settings import ChatSettings


class ChatSettingsService:
    def __init__(self, chat_settings_dao: ChatSettingsDao):
        self.chat_settings_dao = chat_settings_dao

    def add_chat_settings(self, chat_settings: ChatSettings) -> ChatSettings:
        return self.chat_settings_dao.add_api_key(chat_settings)

    def delete_chat_settings(self, session_id: str) -> None:
        self.chat_settings_dao.delete_api_key(session_id)

    def get_chat_settings_by_session(self, session_id: str) -> ChatSettings:
        return self.chat_settings_dao.get_api_key(session_id)

    def update_chat_settings(self, chat_settings: ChatSettings) -> ChatSettings:
        return self.chat_settings_dao.update_api_key(chat_settings.session_id, chat_settings)