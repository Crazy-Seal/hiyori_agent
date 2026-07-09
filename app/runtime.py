"""运行环境与存储路径隔离。

桌面端正常运行时默认使用生产环境。测试必须显式设置 ``AYAYA_ENV=test``，
并提供隔离的 ``AYAYA_DATA_DIR``；禁止测试静默回退到生产 ``memory`` 目录。
"""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_DATA_DIR = PROJECT_ROOT / "memory"
PRODUCTION_CHAT_SETTINGS_FILE = PROJECT_ROOT / "config" / "chat_settings.yaml"


def get_environment() -> str:
    value = os.getenv("AYAYA_ENV", "production").strip().lower()
    aliases = {"prod": "production", "testing": "test"}
    value = aliases.get(value, value)
    if value not in {"production", "test"}:
        raise RuntimeError("AYAYA_ENV 必须设置为 'production' 或 'test'")
    return value


def is_test_environment() -> bool:
    return get_environment() == "test"


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve()


def _is_within(path: Path, parent: Path) -> bool:
    path = _resolved(path)
    parent = _resolved(parent)
    return path == parent or path.is_relative_to(parent)


def get_data_dir() -> Path:
    configured = os.getenv("AYAYA_DATA_DIR", "").strip()
    if is_test_environment():
        if not configured:
            raise RuntimeError(
                "AYAYA_ENV=test 时必须设置 AYAYA_DATA_DIR；"
                "测试不得回退到生产存储"
            )
        data_dir = _resolved(Path(configured))
        if _is_within(data_dir, PRODUCTION_DATA_DIR):
            raise RuntimeError("测试数据目录必须位于生产 memory/ 目录之外")
        return data_dir

    return _resolved(Path(configured)) if configured else PRODUCTION_DATA_DIR


def require_test_storage_path(path: Path, label: str) -> Path:
    """确保测试环境中的存储路径覆盖值始终位于 AYAYA_DATA_DIR 内。"""
    resolved = _resolved(path)
    if is_test_environment() and not _is_within(resolved, get_data_dir()):
        raise RuntimeError(f"测试模式下 {label} 必须位于 AYAYA_DATA_DIR 内")
    return resolved


def get_memory_base_dir() -> Path:
    configured = os.getenv("MEMORY_BASE_PATH", "").strip()
    path = Path(configured) if configured else get_data_dir()
    return require_test_storage_path(path, "MEMORY_BASE_PATH")


def get_mem0_qdrant_dir(memory_base_dir: Path) -> Path:
    configured = os.getenv("MEM0_QDRANT_PATH", "").strip()
    path = Path(configured) if configured else memory_base_dir / "mem0" / "qdrant_data"
    return require_test_storage_path(path, "MEM0_QDRANT_PATH")


def get_chat_settings_file() -> Path:
    configured = os.getenv("AYAYA_CHAT_SETTINGS_FILE", "").strip()
    if configured:
        path = _resolved(Path(configured))
    elif is_test_environment():
        path = get_data_dir() / "config" / "chat_settings.yaml"
    else:
        path = PRODUCTION_CHAT_SETTINGS_FILE

    if is_test_environment():
        return require_test_storage_path(path, "AYAYA_CHAT_SETTINGS_FILE")
    return path


def get_sqlite_dir() -> Path:
    return get_data_dir() / "sqlite"


def get_agent_state_db() -> Path:
    """返回 Agent checkpoint 与聊天记录共用的 SQLite 文件。"""
    return get_sqlite_dir() / "agent_checkpoints.sqlite3"


def get_chat_history_db() -> Path:
    return get_agent_state_db()


def get_checkpoint_db() -> Path:
    return get_agent_state_db()


def get_legacy_chat_history_db() -> Path:
    """返回迁移前独立聊天记录数据库的位置。"""
    return get_sqlite_dir() / "chat_history.sqlite3"


def get_images_dir() -> Path:
    return get_data_dir() / "images"
