from typing import Callable

from fastapi import Depends
from functools import lru_cache

from app.crud.chat_history_dao import ChatHistoryDao
from app.crud.chat_settings_dao import ChatSettingsDao
from app.crud.mcp_settings_dao import MCPSettingsDao
from app.schemas.chat_settings import ChatSettings
from app.services.agent_service import AgentService
from app.services.mcp_connection_manager import MCPConnectionManager
from app.services.mcp_policy_resolver import MCPPolicyResolver
from app.services.mcp_service import MCPService
from app.services.chat_settings_service import ChatSettingsService
from app.services.chat_history_service import ChatHistoryService
from app.services.settings_mutation import SettingsMutationCoordinator


@lru_cache(maxsize=1)
def get_chat_history_dao() -> ChatHistoryDao:
    return ChatHistoryDao()


@lru_cache(maxsize=1)
def get_chat_settings_dao() -> ChatSettingsDao:
    return ChatSettingsDao()


@lru_cache(maxsize=1)
def get_mcp_settings_dao() -> MCPSettingsDao:
    return MCPSettingsDao()


@lru_cache(maxsize=1)
def get_settings_mutation_coordinator() -> SettingsMutationCoordinator:
    return SettingsMutationCoordinator()


@lru_cache(maxsize=1)
def get_mcp_connection_manager() -> MCPConnectionManager:
    dao = get_mcp_settings_dao()
    return MCPConnectionManager(dao.load)


@lru_cache(maxsize=1)
def get_mcp_policy_resolver() -> MCPPolicyResolver:
    return MCPPolicyResolver(get_chat_settings_dao().get_chat_settings)


def get_chat_settings_loader(
    chat_settings_dao: ChatSettingsDao = Depends(get_chat_settings_dao),
) -> Callable[[str], ChatSettings]:
    """提供配置加载函数，用于 AgentService 等需要延迟加载的场景"""
    return chat_settings_dao.get_chat_settings


@lru_cache(maxsize=1)
def get_agent_service(
    chat_history_dao: ChatHistoryDao = Depends(get_chat_history_dao),
    chat_settings_loader: Callable[[str], ChatSettings] = Depends(get_chat_settings_loader),
) -> AgentService:
    return AgentService(
        chat_history_dao=chat_history_dao,
        chat_settings_loader=chat_settings_loader,
    )


@lru_cache(maxsize=1)
def get_chat_settings_service(
    chat_settings_dao: ChatSettingsDao = Depends(get_chat_settings_dao),
    mcp_settings_dao: MCPSettingsDao = Depends(get_mcp_settings_dao),
    connection_manager: MCPConnectionManager = Depends(get_mcp_connection_manager),
    mutation_coordinator: SettingsMutationCoordinator = Depends(get_settings_mutation_coordinator),
) -> ChatSettingsService:
    return ChatSettingsService(
        chat_settings_dao=chat_settings_dao,
        mcp_settings_dao=mcp_settings_dao,
        connection_manager=connection_manager,
        mutation_coordinator=mutation_coordinator,
    )


def get_mcp_service(
    mcp_settings_dao: MCPSettingsDao = Depends(get_mcp_settings_dao),
    chat_settings_dao: ChatSettingsDao = Depends(get_chat_settings_dao),
    connection_manager: MCPConnectionManager = Depends(get_mcp_connection_manager),
    mutation_coordinator: SettingsMutationCoordinator = Depends(get_settings_mutation_coordinator),
) -> MCPService:
    return MCPService(
        mcp_settings_dao,
        chat_settings_dao,
        connection_manager,
        mutation_coordinator,
    )


@lru_cache(maxsize=1)
def get_chat_history_service(chat_history_dao: ChatHistoryDao = Depends(get_chat_history_dao)) -> ChatHistoryService:
    return ChatHistoryService(chat_history_dao=chat_history_dao)
