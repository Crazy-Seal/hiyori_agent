import os
import re
import yaml
from functools import lru_cache
from pathlib import Path
from typing import Any
from app.schemas.chat_settings import ChatSettings

CHAT_CONFIG_FILE = Path(__file__).resolve().parents[2] / "config" / "chat_settings.yaml"
SETTINGS_FILE = Path(__file__).resolve().parents[2] / "config" / "settings.yaml"


_ENV_PLACEHOLDER_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)}")


def _resolve_env_placeholders(value: Any) -> Any:
    """Recursively resolve ${VAR_NAME} placeholders using environment variables."""
    if isinstance(value, dict):
        return {k: _resolve_env_placeholders(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_placeholders(item) for item in value]
    if isinstance(value, str):
        def _replace(match: re.Match[str]) -> str:
            env_name = match.group(1)
            env_value = os.getenv(env_name)
            if env_value is None:
                raise RuntimeError(f"Environment variable not found: {env_name}")
            return env_value

        return _ENV_PLACEHOLDER_PATTERN.sub(_replace, value)
    return value


def _load_yaml_with_env(file_path: Path) -> dict[str, Any]:
    with file_path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}
    return _resolve_env_placeholders(raw)


@lru_cache(maxsize=1)
def get_chat_settings(session_id: str) -> ChatSettings:
    # 从 YAML 文件读取配置
    if not CHAT_CONFIG_FILE.exists():
        raise RuntimeError(f"Config file not found: {CHAT_CONFIG_FILE}")

    raw = _load_yaml_with_env(CHAT_CONFIG_FILE)

    chat_models = raw["chat_models"]
    matched_model = next(model for model in chat_models if model["session_id"] == session_id)

    return ChatSettings(
        session_id=matched_model["session_id"],
        model_name=matched_model["model_name"],
        openai_api_key=matched_model["openai_api_key"],
        openai_base_url=matched_model["openai_base_url"],
        temperature=matched_model["temperature"],
        system_prompt=matched_model["system_prompt"],
        tools_list=matched_model["tools_list"],
    )


@lru_cache(maxsize=1)
def get_embedding_model_settings() -> dict[str, str | int]:
    raw = _load_yaml_with_env(SETTINGS_FILE)

    embedding = raw["memory"]["embedding_model"]
    return {
        "api_key": embedding["api_key"],
        "model": embedding["model"],
        "dimension": embedding["dimension"],
        "base_url": embedding["base_url"],
    }


@lru_cache(maxsize=1)
def get_coding_model_settings() -> dict[str, str | float]:
    """读取编程子图模型配置。"""
    raw = _load_yaml_with_env(SETTINGS_FILE)

    coding_model = raw["coding"]["coding_model"]
    return {
        "api_key": coding_model["api_key"],
        "model": coding_model["model"],
        "base_url": coding_model["base_url"],
        "temperature": float(coding_model["temperature"]),
    }
