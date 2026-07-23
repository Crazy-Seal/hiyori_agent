import os

import pytest
from pydantic import ValidationError

from app.mcp.process_env import build_mcp_process_env
from app.schemas.mcp import StdioMCPServerConfig


def test_mcp_process_environment_excludes_parent_secrets(monkeypatch) -> None:
    monkeypatch.setenv("AYAYA_API_TOKEN", "runtime-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "model-secret")
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))

    child_env = build_mcp_process_env({"EXPLICIT_VALUE": "allowed"})

    assert child_env["EXPLICIT_VALUE"] == "allowed"
    assert child_env.get("PATH") == os.environ.get("PATH")
    assert "AYAYA_API_TOKEN" not in child_env
    assert "OPENAI_API_KEY" not in child_env


def test_mcp_process_environment_never_allows_runtime_token(monkeypatch) -> None:
    monkeypatch.setenv("AYAYA_API_TOKEN", "runtime-secret")

    child_env = build_mcp_process_env({"AYAYA_API_TOKEN": "configured-secret"})

    assert "AYAYA_API_TOKEN" not in child_env


def test_mcp_process_environment_never_allows_backend_base_url() -> None:
    child_env = build_mcp_process_env(
        {"AYAYA_BACKEND_BASE_URL": "http://attacker.example"}
    )

    assert "AYAYA_BACKEND_BASE_URL" not in child_env


def test_mcp_process_environment_never_allows_parent_pid() -> None:
    child_env = build_mcp_process_env({"AYAYA_PARENT_PID": "1234"})

    assert "AYAYA_PARENT_PID" not in child_env


def test_mcp_server_config_rejects_parent_pid() -> None:
    with pytest.raises(ValidationError, match="AYAYA_PARENT_PID"):
        StdioMCPServerConfig(
            id="unsafe-parent",
            name="Unsafe parent",
            command="python",
            env={"AYAYA_PARENT_PID": "1234"},
        )


def test_mcp_server_config_rejects_backend_api_token() -> None:
    with pytest.raises(ValidationError, match="AYAYA_API_TOKEN"):
        StdioMCPServerConfig(
            id="unsafe",
            name="Unsafe",
            command="python",
            env={"AYAYA_API_TOKEN": "secret"},
        )
