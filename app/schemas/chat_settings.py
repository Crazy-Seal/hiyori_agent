from typing import Any

from pydantic import BaseModel, Field, model_validator


CONTEXT_WINDOW_DEFAULT_CONFIG = {
    "recent_context_human_messages": 10,
    "max_images_in_context": 5,
    "image_ttl_human_messages": 10,
    "max_screenshots_in_context": 2,
    "screenshot_ttl_human_messages": 2,
}

MEMORY_DEFAULT_CONFIG = {
    "enable_diary": True,
    "enable_episodic": True,
    "enable_semantic": True,
    "summary_every_human_messages": 10,
}


class AgentPluginSettings(BaseModel):
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


def _merge_plugin_config(defaults: dict[str, Any], value: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(defaults)
    if value:
        merged.update(value)
    return merged


def _validate_plugin_config(name: str, config: dict[str, Any]) -> dict[str, Any]:
    from app.agent.plugins.registry import PluginRegistry

    plugin_class = PluginRegistry.get(name)
    config_model = getattr(plugin_class, "config_model", None) if plugin_class else None
    if config_model is None:
        return config
    return config_model(**config).model_dump()


def _legacy_memory_config(memory_plugins: list[str] | None) -> tuple[bool, dict[str, Any]]:
    if not memory_plugins:
        return False, dict(MEMORY_DEFAULT_CONFIG)

    names = set(memory_plugins)
    config = dict(MEMORY_DEFAULT_CONFIG)
    config["enable_diary"] = "diary" in names or "summary" in names
    config["enable_episodic"] = "episodic" in names
    config["enable_semantic"] = "semantic" in names

    # 兼容未知旧值：只要旧字段非空，就按默认记忆能力启用 memory 插件。
    if not any(
        config[key]
        for key in ("enable_diary", "enable_episodic", "enable_semantic")
    ):
        config.update(MEMORY_DEFAULT_CONFIG)
    return True, config


def _memory_plugins_from_agent_plugins(
    agent_plugins: dict[str, AgentPluginSettings],
) -> list[str] | None:
    memory = agent_plugins.get("memory")
    if not memory or not memory.enabled:
        return None

    config = _merge_plugin_config(MEMORY_DEFAULT_CONFIG, memory.config)
    names: list[str] = []
    if config.get("enable_diary"):
        names.append("diary")
    if config.get("enable_episodic"):
        names.append("episodic")
    if config.get("enable_semantic"):
        names.append("semantic")
    return names or None


class ChatSettings(BaseModel):
    session_id: str
    model_name: str
    openai_api_key: str
    openai_base_url: str
    temperature: float
    system_prompt: str
    tools_list: list[str]
    memory_plugins: list[str] | None = None
    agent_plugins: dict[str, AgentPluginSettings] | None = None
    skills: list[str] | None = None

    name: str | None = None
    feature: str | None = None
    character: str | None = None
    address: str | None = None
    characteristic: str | None = None
    constraint: str | None = None

    @model_validator(mode="after")
    def normalize_agent_plugins(self) -> "ChatSettings":
        plugins = dict(self.agent_plugins or {})

        context_window = plugins.get("context_window")
        plugins["context_window"] = AgentPluginSettings(
            enabled=True,
            config=_validate_plugin_config(
                "context_window",
                _merge_plugin_config(
                    CONTEXT_WINDOW_DEFAULT_CONFIG,
                    context_window.config if context_window else None,
                ),
            ),
        )

        memory = plugins.get("memory")
        if memory is None:
            enabled, memory_config = _legacy_memory_config(self.memory_plugins)
            if not enabled:
                memory_config = dict(MEMORY_DEFAULT_CONFIG)
            plugins["memory"] = AgentPluginSettings(
                enabled=True,
                config=_validate_plugin_config("memory", memory_config),
            )
        else:
            plugins["memory"] = AgentPluginSettings(
                enabled=True,
                config=_validate_plugin_config(
                    "memory",
                    _merge_plugin_config(MEMORY_DEFAULT_CONFIG, memory.config),
                ),
            )

        for name, settings in list(plugins.items()):
            if name in {"context_window", "memory"}:
                continue
            plugins[name] = AgentPluginSettings(
                enabled=settings.enabled,
                config=_validate_plugin_config(name, settings.config),
            )

        self.agent_plugins = plugins
        self.memory_plugins = _memory_plugins_from_agent_plugins(plugins)
        return self

    def __hash__(self):
        return hash((
            self.session_id,
            self.model_name,
            self.openai_api_key,
            self.openai_base_url,
            self.temperature,
            self.system_prompt,
            tuple(self.tools_list),
            tuple(self.memory_plugins or []),
            tuple(
                (name, settings.enabled, tuple(sorted(settings.config.items())))
                for name, settings in sorted(self.agent_plugins.items())
            ),
            tuple(self.skills or []),
        ))
