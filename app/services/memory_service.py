from app.crud.chat_history_dao import ChatHistoryDao


class MemoryService:
    def __init__(self, chat_history_dao: ChatHistoryDao):
        self.chat_history_dao = chat_history_dao

    def get_chat_history_data(self, session_id: str, start: int = 0, limit: int = 200) -> list[dict[str, str]]:
        return self.chat_history_dao.list_chat_history(session_id, start, limit)

