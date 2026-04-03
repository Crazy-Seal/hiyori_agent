import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.tools import run_ps as run_ps_module


def test_build_command_wraps_utf8_settings(monkeypatch):
    monkeypatch.setattr(run_ps_module, "RUN_PS_FORCE_CONDA", False)

    command = "Write-Output '中文输出'"
    built = run_ps_module._build_command(command)

    assert built is not None
    assert built[0] == "powershell.exe"
    wrapped = built[-1]
    assert "[Console]::OutputEncoding = $utf8NoBom" in wrapped
    assert "$OutputEncoding = $utf8NoBom" in wrapped
    assert "chcp 65001 > $null" in wrapped
    assert command in wrapped


def test_run_ps_uses_utf8_decode_and_returns_chinese(monkeypatch):
    monkeypatch.setattr(run_ps_module, "RUN_PS_FORCE_CONDA", False)

    captured_kwargs = {}

    class FakeProc:
        pid = 1234

        def communicate(self, timeout):
            return "中文正常", ""

    def fake_popen(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return FakeProc()

    monkeypatch.setattr(run_ps_module.subprocess, "Popen", fake_popen)

    run_ps_func = getattr(run_ps_module.run_ps, "func")
    result = run_ps_func("Write-Output '中文正常'")

    assert result == "中文正常"
    assert captured_kwargs["encoding"] == "utf-8"
    assert captured_kwargs["errors"] == "replace"
