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
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file = self.config_file.with_suffix(f"{self.config_file.suffix}.tmp")
        with temp_file.open("w", encoding="utf-8") as file:
            yaml.safe_dump(data, file, allow_unicode=True, sort_keys=False)
        temp_file.replace(self.config_file)

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
            context_strategy=item["context_strategy"],
            agent_plugins=item.get("agent_plugins") or {},
            skills=item.get("skills"),
            mcp=item.get("mcp") or {},
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

        chat_models.append(chat_settings.model_dump(mode="json"))
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
                chat_models[index] = chat_settings.model_dump(mode="json")
                self._save_chat_settings_file(data)
                self._clear_caches()
                return chat_settings

        raise KeyError(f"session_id not found: {session_id}")

    def remove_mcp_server_references(self, server_id: str) -> list[str]:
        """移除全部模型对指定 MCP Server 的授权。

        Args:
            server_id: 待移除引用的 MCP Server ID。

        Returns:
            权限配置受到修改的会话 ID 列表。
        """
        data = self._load_chat_settings_file()
        affected: list[str] = []
        for item in data["chat_models"]:
            servers = ((item.get("mcp") or {}).get("servers") or {})
            if server_id not in servers:
                continue
            del servers[server_id]
            item["mcp"] = {"servers": servers}
            affected.append(item["session_id"])
        if affected:
            self._save_chat_settings_file(data)
            self._clear_caches()
        return affected

    def reconcile_mcp_server_tools(
        self,
        server_id: str,
        identity_fingerprint: str,
        tool_names: list[str],
    ) -> list[str]:
        """按当前服务身份和工具目录安全重绑定全部模型权限。

        Args:
            server_id: MCP Server ID。
            identity_fingerprint: 当前 Server 身份指纹。
            tool_names: 当前 Server 暴露的工具名称。

        Returns:
            权限配置受到同步的会话 ID 列表。
        """
        data = self._load_chat_settings_file()
        affected: list[str] = []
        for item in data["chat_models"]:
            servers = ((item.get("mcp") or {}).get("servers") or {})
            policy = servers.get(server_id)
            if not isinstance(policy, dict):
                continue
            same_identity = policy.get("identity_fingerprint") == identity_fingerprint
            previous_tools = policy.get("tools") or {}
            policy["tools"] = {
                name: previous_tools.get(name, "ask") if same_identity else "ask"
                for name in tool_names
            }
            policy["identity_fingerprint"] = identity_fingerprint
            affected.append(item["session_id"])
        if affected:
            self._save_chat_settings_file(data)
            self._clear_caches()
        return affected

    def invalidate_mcp_server_identity(self, server_id: str) -> list[str]:
        """在服务身份变化但尚未验证时降级工具权限。

        Args:
            server_id: 身份发生变化的 MCP Server ID。

        Returns:
            工具权限被降级为 ``ask`` 的会话 ID 列表。
        """
        data = self._load_chat_settings_file()
        affected: list[str] = []
        for item in data["chat_models"]:
            policy = (((item.get("mcp") or {}).get("servers") or {}).get(server_id))
            if not isinstance(policy, dict):
                continue
            policy["tools"] = {name: "ask" for name in (policy.get("tools") or {})}
            affected.append(item["session_id"])
        if affected:
            self._save_chat_settings_file(data)
            self._clear_caches()
        return affected

    def count_mcp_server_references(self, server_id: str) -> int:
        """统计引用指定 MCP Server 的模型数量。

        Args:
            server_id: MCP Server ID。

        Returns:
            包含该 Server 权限配置的模型数量。
        """
        data = self._load_chat_settings_file()
        return sum(
            server_id in (((item.get("mcp") or {}).get("servers")) or {})
            for item in data["chat_models"]
        )
