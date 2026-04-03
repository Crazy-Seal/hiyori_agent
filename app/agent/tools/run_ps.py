import os
import re
import subprocess
from typing import Tuple

from langchain.tools import tool

from app.agent.utils.log import log_tool_call
from app.agent.utils.safe_path import WORKDIR

# 默认把 run_ps 放到独立 conda 环境执行，避免污染主项目环境。
RUN_PS_CONDA_ENV = os.getenv("RUN_PS_CONDA_ENV", "agent_workspace")
RUN_PS_FORCE_CONDA = True
RUN_PS_TIMEOUT_SEC = int(os.getenv("RUN_PS_TIMEOUT_SEC", "120"))
# 可选覆盖：按场景设置超时时间（秒）。
RUN_PS_TIMEOUT_PIP_SEC = int(os.getenv("RUN_PS_TIMEOUT_PIP_SEC", "600"))
RUN_PS_TIMEOUT_PYTHON_SEC = int(os.getenv("RUN_PS_TIMEOUT_PYTHON_SEC", "5"))
RUN_PS_TIMEOUT_GIT_SEC = int(os.getenv("RUN_PS_TIMEOUT_GIT_SEC", "180"))
# timeout 行为：background=超时后不杀进程，仅停止等待；kill=超时后终止进程树。
RUN_PS_TIMEOUT_BEHAVIOR = os.getenv("RUN_PS_TIMEOUT_BEHAVIOR", "background").lower()
if RUN_PS_TIMEOUT_BEHAVIOR not in {"background", "kill"}:
    RUN_PS_TIMEOUT_BEHAVIOR = "background"


def _find_conda_exe() -> str | None:
    try:
        # where conda 可能返回多行，这里选第一个 .exe。
        output = subprocess.check_output(
            ["where", "conda"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        for line in output.splitlines():
            candidate = line.strip().strip('"')
            if candidate.lower().endswith(".exe"):
                return candidate
        return None
    except Exception:
        return None


def _build_command(command: str) -> list[str] | None:
    """构建最终执行命令；要求使用独立 conda 环境时返回 conda run 前缀。"""
    # 统一设置 PowerShell 进程与子命令输出为 UTF-8，减少中文乱码。
    utf8_command = (
        "$utf8NoBom = New-Object System.Text.UTF8Encoding($false);"
        "[Console]::InputEncoding = $utf8NoBom;"
        "[Console]::OutputEncoding = $utf8NoBom;"
        "$OutputEncoding = $utf8NoBom;"
        "chcp 65001 > $null;"
        f"{command}"
    )
    ps_cmd = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        utf8_command,
    ]
    if not RUN_PS_FORCE_CONDA:
        return ps_cmd

    conda_exe = _find_conda_exe()
    if not conda_exe:
        return None
    return [conda_exe, "run", "-n", RUN_PS_CONDA_ENV] + ps_cmd


def _kill_process_tree(pid: int) -> None:
    """Windows 上强制结束进程树，避免超时后子进程残留。"""
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        # 兜底：忽略清理异常，避免覆盖原始超时语义。
        pass


def _select_timeout_sec(command: str) -> Tuple[int, str]:
    """根据命令类型动态选择等待时长。"""
    cmd = command.strip().lower()

    # pip/pip3/python -m pip/conda install 通常需要较长下载与安装时间。
    if re.search(r"(^|\s)(pip|pip3)(\s+install|\s+uninstall|\s+download)\b", cmd):
        return RUN_PS_TIMEOUT_PIP_SEC, "命令执行时间长"
    if "python -m pip" in cmd or "py -m pip" in cmd:
        return RUN_PS_TIMEOUT_PIP_SEC, "命令执行时间长"
    if re.search(r"(^|\s)conda\s+(install|update|create)\b", cmd):
        return max(RUN_PS_TIMEOUT_PIP_SEC, 900), "命令执行时间长"

    # git 拉取/克隆可能较慢，但通常短于安装依赖。
    if re.search(r"(^|\s)git\s+(clone|pull|fetch|submodule)\b", cmd):
        return RUN_PS_TIMEOUT_GIT_SEC, "命令执行时间长"

    # 普通 python 脚本默认短等待，超时后按策略进入后台/终止。
    if re.search(r"(^|\s)(python|py)\s+[^-].*\.py(\s|$)", cmd):
        return RUN_PS_TIMEOUT_PYTHON_SEC, "程序运行平稳，但执行时间较长，或为持续运行的服务"

    # 兜底默认值。
    return RUN_PS_TIMEOUT_SEC, "命令执行时间长"


@tool
@log_tool_call()
def run_ps(command: str) -> str:
    """运行 PowerShell 命令并返回输出结果。警告：绝对禁止运行可能对系统造成损害的命令，如删除文件、操作磁盘或注册表、重启或关闭计算机等。

    Args:
        command: PowerShell 命令字符串。
    """
    cmd_lower = command.lower()
    dangerous = [
        # 文件与目录破坏
        "remove-item",
        "rd /s /q",
        "rmdir /s /q",
        "del /f /s /q",
        "erase /f /s /q",
        "cipher /w",
        # 磁盘/分区/卷操作
        "format-volume",
        "clear-disk",
        "diskpart",
        "remove-partition",
        "delete partition",
        "delete volume",
        # 系统关机/重启/引导配置
        "stop-computer",
        "restart-computer",
        "shutdown",
        "bootrec",
        "bcdedit",
        # 影子副本/备份删除（常见于勒索行为）
        "vssadmin delete shadows",
        "wmic shadowcopy delete",
        "wbadmin delete",
        # 注册表高风险写删
        "reg delete",
        "remove-itemproperty",
        "set-itemproperty -path hk",
        "new-itemproperty -path hk",
        # 防火墙/防护关闭
        "netsh advfirewall set allprofiles state off",
        "set-mppreference -disablerealtimemonitoring",
        # 账户与权限高风险变更
        "net user ",
        "net localgroup administrators",
        "add-localgroupmember",
    ]
    if any(d in cmd_lower for d in dangerous):
        return "错误: 检测到潜在危险命令，已阻止执行。"

    final_cmd = _build_command(command)
    if final_cmd is None:
        return "错误: 未找到 conda 可执行文件，无法使用独立环境执行命令。"

    timeout_sec, report = _select_timeout_sec(command)

    try:
        proc = subprocess.Popen(
            final_cmd,
            cwd=WORKDIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            if RUN_PS_TIMEOUT_BEHAVIOR == "kill":
                _kill_process_tree(proc.pid)
                return f"命令执行超时（{timeout_sec}s），已终止进程树。"
            return (
                report +
                f"，超过{timeout_sec}s，已停止等待并保持后台运行，PID={proc.pid}。"
                "如需结束该任务，可使用 taskkill /PID <pid> /T /F。"
            )

        out = (stdout + stderr).strip()
        return out[:50000] if out else "(无输出)"
    except Exception as e:
        return f"错误: 命令执行失败: {e}"
