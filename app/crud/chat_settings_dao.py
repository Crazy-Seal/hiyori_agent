from pathlib import Path

import yaml

from app.schemas.chat_settings import ChatSettings

APIKEY_FILE = Path(__file__).resolve().parents[2] / "config" / "chat_settings.yaml"


class ChatSettingsDao:
    def __init__(self, apikey_file: Path = APIKEY_FILE):
        self.apikey_file = apikey_file

    def _load_apikey_file(self) -> dict:
        if not self.apikey_file.exists():
            raise RuntimeError(f"Config file not found: {self.apikey_file}")

        with self.apikey_file.open("r", encoding="utf-8") as file:
            return yaml.safe_load(file)

    def _save_apikey_file(self, data: dict) -> None:
        with self.apikey_file.open("w", encoding="utf-8") as file:
            yaml.safe_dump(data, file, allow_unicode=True, sort_keys=False)

    def _clear_caches(self) -> None:
        from app.config.config import get_chat_settings

        get_chat_settings.cache_clear()

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
        )

    def add_api_key(self, chat_settings: ChatSettings) -> ChatSettings:
        data = self._load_apikey_file()
        chat_models = data["chat_models"]
        session_id = chat_settings.session_id

        if any(item["session_id"] == session_id for item in chat_models):
            raise ValueError(f"session_id already exists: {session_id}")

        chat_models.append(chat_settings.model_dump())
        self._save_apikey_file(data)
        self._clear_caches()
        return chat_settings

    def get_api_key(self, session_id: str) -> ChatSettings:
        data = self._load_apikey_file()
        chat_models = data["chat_models"]

        for item in chat_models:
            if item["session_id"] == session_id:
                return self._to_chat_settings(item)

        raise KeyError(f"session_id not found: {session_id}")

    def delete_api_key(self, session_id: str) -> None:
        data = self._load_apikey_file()
        chat_models = data["chat_models"]

        for index, item in enumerate(chat_models):
            if item["session_id"] == session_id:
                del chat_models[index]
                self._save_apikey_file(data)
                self._clear_caches()
                return

        raise KeyError(f"session_id not found: {session_id}")

    def update_api_key(self, session_id: str, chat_settings: ChatSettings) -> ChatSettings:
        data = self._load_apikey_file()
        chat_models = data["chat_models"]

        for index, item in enumerate(chat_models):
            if item["session_id"] == session_id:
                chat_models[index] = chat_settings.model_dump()
                self._save_apikey_file(data)
                self._clear_caches()
                return chat_settings

        raise KeyError(f"session_id not found: {session_id}")
