from pathlib import Path

import yaml

from app.schemas.chat_settings import ChatSettings
from app.runtime import get_chat_settings_file


class ChatSettingsDao:
    def __init__(self, config_file: Path | None = None):
        self.config_file = config_file or get_chat_settings_file()
        self._cache: dict[str, ChatSettings] = {}

    def _load_chat_settings_file(self) -> dict:
        if not self.config_file.exists():
            raise RuntimeError(f"Config file not found: {self.config_file}")

        with self.config_file.open("r", encoding="utf-8") as file:
            return yaml.safe_load(file)

    def _save_chat_settings_file(self, data: dict) -> None:
        with self.config_file.open("w", encoding="utf-8") as file:
            yaml.safe_dump(data, file, allow_unicode=True, sort_keys=False)

    def _clear_caches(self) -> None:
        """清除所有相关缓存"""
        self._cache.clear()
        # 清除 MemoryManager 工厂缓存
        from app.agent.memory import get_memory_manager
        get_memory_manager.cache_clear()

    @staticmethod
    def _to_chat_settings(item: dict) -> ChatSettings:
        return ChatSettings(
            session_id=item["session_id"],
            model_name=item["model_name"],
            openai_api_key=item["openai_api_key"],
            openai_base_url=item["openai_base_url"],
            temperature=item["temperature"],
            system_prompt=item["system_prompt"],
            tools_list=item["tools_list"],
            memory_plugins=item.get("memory_plugins"),
            agent_plugins=item.get("agent_plugins") or {},
            skills=item.get("skills"),
            # 提示词模板字段
            name=item.get("name"),
            feature=item.get("feature"),
            character=item.get("character"),
            address=item.get("address"),
            characteristic=item.get("characteristic"),
            constraint=item.get("constraint"),
        )

    def add_chat_settings(self, chat_settings: ChatSettings) -> ChatSettings:
        data = self._load_chat_settings_file()
        chat_models = data["chat_models"]
        session_id = chat_settings.session_id

        if any(item["session_id"] == session_id for item in chat_models):
            raise ValueError(f"session_id already exists: {session_id}")

        chat_models.append(chat_settings.model_dump())
        self._save_chat_settings_file(data)
        self._clear_caches()
        return chat_settings

    def get_chat_settings(self, session_id: str) -> ChatSettings:
        if session_id in self._cache:
            return self._cache[session_id]

        data = self._load_chat_settings_file()
        for item in data["chat_models"]:
            if item["session_id"] == session_id:
                result = self._to_chat_settings(item)
                self._cache[session_id] = result
                return result

        raise KeyError(f"session_id not found: {session_id}")

    def delete_chat_settings(self, session_id: str) -> None:
        data = self._load_chat_settings_file()
        chat_models = data["chat_models"]

        for index, item in enumerate(chat_models):
            if item["session_id"] == session_id:
                del chat_models[index]
                self._save_chat_settings_file(data)
                self._clear_caches()
                return

        raise KeyError(f"session_id not found: {session_id}")

    def update_chat_settings(self, session_id: str, chat_settings: ChatSettings) -> ChatSettings:
        data = self._load_chat_settings_file()
        chat_models = data["chat_models"]

        for index, item in enumerate(chat_models):
            if item["session_id"] == session_id:
                chat_models[index] = chat_settings.model_dump()
                self._save_chat_settings_file(data)
                self._clear_caches()
                return chat_settings

        raise KeyError(f"session_id not found: {session_id}")
