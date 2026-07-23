"""构造 stdio MCP 子进程的最小环境。"""

from __future__ import annotations

import os
from collections.abc import Mapping


WINDOWS_ENV_ALLOWLIST = (
    "PATH",
    "SystemRoot",
    "WINDIR",
    "ComSpec",
    "PATHEXT",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
)
POSIX_ENV_ALLOWLIST = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")
RESERVED_ENV_NAMES = {
    "AYAYA_API_TOKEN",
    "AYAYA_MANAGE_BACKEND",
    "AYAYA_PYTHON_EXECUTABLE",
    "AYAYA_BACKEND_CWD",
    "AYAYA_BACKEND_BASE_URL",
    "AYAYA_PARENT_PID",
}


def _get_environment_value(name: str) -> tuple[str, str] | None:
    """按平台规则读取一个允许继承的环境变量。"""
    if os.name != "nt":
        value = os.environ.get(name)
        return (name, value) if value is not None else None
    expected = name.casefold()
    for key, value in os.environ.items():
        if key.casefold() == expected:
            return key, value
    return None


def build_mcp_process_env(explicit_env: Mapping[str, str]) -> dict[str, str]:
    """构造只包含启动必需项和显式配置项的子进程环境。

    Args:
        explicit_env: 用户在单个 MCP Server 上明确配置的环境变量。

    Returns:
        可直接传给子进程的独立环境字典。
    """
    allowlist = WINDOWS_ENV_ALLOWLIST if os.name == "nt" else POSIX_ENV_ALLOWLIST
    child_env: dict[str, str] = {}
    for name in allowlist:
        item = _get_environment_value(name)
        if item is not None:
            child_env[item[0]] = item[1]

    reserved = {name.casefold() for name in RESERVED_ENV_NAMES}
    for key, value in explicit_env.items():
        if key.casefold() in reserved:
            continue
        child_env[key] = value
    return child_env
