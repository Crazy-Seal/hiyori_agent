from fastapi import Depends
from functools import lru_cache

from app.crud.chat_history_dao import ChatHistoryDao
from app.crud.chat_settings_dao import ChatSettingsDao
from app.services.agent_service import AgentService
from app.services.chat_settings_service import ChatSettingsService
from app.services.memory_service import MemoryService


@lru_cache(maxsize=1)
def get_chat_history_dao() -> ChatHistoryDao:
    return ChatHistoryDao()


@lru_cache(maxsize=1)
def get_chat_settings_dao() -> ChatSettingsDao:
    return ChatSettingsDao()


@lru_cache(maxsize=1)
def get_agent_service(chat_history_dao: ChatHistoryDao = Depends(get_chat_history_dao)) -> AgentService:
    return AgentService(chat_history_dao=chat_history_dao)


@lru_cache(maxsize=1)
def get_chat_settings_service(
    chat_settings_dao: ChatSettingsDao = Depends(get_chat_settings_dao),
) -> ChatSettingsService:
    return ChatSettingsService(chat_settings_dao=chat_settings_dao)


@lru_cache(maxsize=1)
def get_memory_service(chat_history_dao: ChatHistoryDao = Depends(get_chat_history_dao)) -> MemoryService:
    return MemoryService(chat_history_dao=chat_history_dao)
