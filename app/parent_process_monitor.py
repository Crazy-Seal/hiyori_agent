"""监控受管后端生命周期所有者的 Windows 进程。"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
from collections.abc import Callable, Mapping
from typing import Any, Protocol


logger = logging.getLogger(__name__)

PARENT_PID_ENV = "AYAYA_PARENT_PID"
SYNCHRONIZE = 0x00100000
INFINITE = 0xFFFFFFFF
WAIT_OBJECT_0 = 0x00000000
WAIT_FAILED = 0xFFFFFFFF


class ParentProcessMonitorError(RuntimeError):
    """生命周期所有者监控无法建立或失效。"""


class _ThreadLike(Protocol):
    """监控线程所需的最小接口。"""

    daemon: bool

    def start(self) -> None:
        """启动监控线程。"""


class WindowsProcessWaiter:
    """使用 Windows 进程句柄等待指定进程退出。"""

    def __init__(
        self,
        *,
        kernel32: Any | None = None,
        get_last_error: Callable[[], int] | None = None,
    ) -> None:
        """初始化 Windows 进程等待器。

        Args:
            kernel32: 可选的 Kernel32 API 对象，主要用于测试。
            get_last_error: 返回最近一个 Windows 错误码的函数。

        Raises:
            ParentProcessMonitorError: 非 Windows 平台无法创建默认等待器。
        """
        if kernel32 is None:
            if sys.platform != "win32":
                raise ParentProcessMonitorError("Windows 进程监控仅支持 Windows")
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [
                ctypes.c_uint32,
                ctypes.c_bool,
                ctypes.c_uint32,
            ]
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            kernel32.WaitForSingleObject.restype = ctypes.c_uint32
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = ctypes.c_bool
        self._kernel32 = kernel32
        self._get_last_error = get_last_error or getattr(
            ctypes, "get_last_error", lambda: 0
        )

    def open(self, process_id: int) -> "_OpenedWindowsProcess":
        """同步打开目标进程句柄。

        Args:
            process_id: 生命周期所有者的进程 ID。

        Returns:
            持有已打开句柄的进程等待对象。

        Raises:
            ParentProcessMonitorError: 无法打开目标进程句柄。
        """
        handle = self._kernel32.OpenProcess(SYNCHRONIZE, False, process_id)
        if not handle:
            error_code = self._get_last_error()
            raise ParentProcessMonitorError(
                f"无法打开生命周期所有者进程句柄，Windows 错误码: {error_code}"
            )
        return _OpenedWindowsProcess(
            kernel32=self._kernel32,
            handle=handle,
            get_last_error=self._get_last_error,
        )

    def wait(self, process_id: int) -> None:
        """同步打开句柄并阻塞等待目标进程退出。"""
        opened_process = self.open(process_id)
        try:
            opened_process.wait()
        finally:
            opened_process.close()


class _OpenedWindowsProcess:
    """持有一个已验证的 Windows 进程句柄。"""

    def __init__(
        self,
        *,
        kernel32: Any,
        handle: Any,
        get_last_error: Callable[[], int],
    ) -> None:
        self._kernel32 = kernel32
        self._handle = handle
        self._get_last_error = get_last_error
        self._closed = False

    def wait(self) -> None:
        """等待句柄进入已终止状态。"""
        result = self._kernel32.WaitForSingleObject(self._handle, INFINITE)
        if result == WAIT_FAILED:
            error_code = self._get_last_error()
            raise ParentProcessMonitorError(
                f"等待生命周期所有者退出失败，Windows 错误码: {error_code}"
            )
        if result != WAIT_OBJECT_0:
            raise ParentProcessMonitorError(
                f"等待生命周期所有者返回未知状态: {result}"
            )

    def close(self) -> None:
        """幂等关闭进程句柄。"""
        if self._closed:
            return
        self._closed = True
        self._kernel32.CloseHandle(self._handle)


def _parse_parent_pid(
    environment: Mapping[str, str],
    *,
    current_pid: int,
) -> int | None:
    """解析并验证可选的生命周期所有者 PID。"""
    value = environment.get(PARENT_PID_ENV)
    if value is None:
        return None
    try:
        process_id = int(value)
    except ValueError as error:
        raise ParentProcessMonitorError(f"{PARENT_PID_ENV} 必须是正整数") from error
    if process_id <= 0:
        raise ParentProcessMonitorError(f"{PARENT_PID_ENV} 必须是正整数")
    if process_id == current_pid:
        raise ParentProcessMonitorError(f"{PARENT_PID_ENV} 不能指向后端自身")
    return process_id


def start_parent_process_monitor(
    on_parent_exit: Callable[[], None],
    *,
    environment: Mapping[str, str] | None = None,
    current_pid: int | None = None,
    platform: str | None = None,
    waiter: Callable[[int], None] | None = None,
    process_waiter: WindowsProcessWaiter | None = None,
    thread_factory: Callable[..., _ThreadLike] = threading.Thread,
) -> _ThreadLike | None:
    """按需启动生命周期所有者监控线程。

    Args:
        on_parent_exit: 所有者退出或监控失效时调用的关闭回调。
        environment: 后端进程环境，默认读取 ``os.environ``。
        current_pid: 后端自身 PID，默认读取 ``os.getpid()``。
        platform: 当前平台，默认读取 ``sys.platform``。
        waiter: 阻塞等待目标 PID 退出的函数。
        process_waiter: 可同步打开 Windows 句柄的等待器。
        thread_factory: 创建 daemon 线程的工厂。

    Returns:
        已启动的监控线程；未绑定所有者时返回 ``None``。

    Raises:
        ParentProcessMonitorError: PID 非法或目标平台不支持监控。
    """
    resolved_environment = os.environ if environment is None else environment
    resolved_pid = os.getpid() if current_pid is None else current_pid
    owner_pid = _parse_parent_pid(resolved_environment, current_pid=resolved_pid)
    if owner_pid is None:
        return None

    resolved_platform = sys.platform if platform is None else platform
    if resolved_platform != "win32":
        raise ParentProcessMonitorError(
            f"{PARENT_PID_ENV} 当前仅支持 Windows 受管后端"
        )
    opened_process: _OpenedWindowsProcess | None = None
    if waiter is None:
        resolved_waiter = process_waiter or WindowsProcessWaiter()
        opened_process = resolved_waiter.open(owner_pid)
        wait_for_exit = lambda _pid: opened_process.wait()
    else:
        wait_for_exit = waiter

    def monitor() -> None:
        try:
            wait_for_exit(owner_pid)
        except Exception:
            logger.exception("生命周期所有者监控失效，后端将安全退出")
        finally:
            if opened_process is not None:
                opened_process.close()
            on_parent_exit()

    try:
        thread = thread_factory(
            target=monitor,
            daemon=True,
        )
        thread.start()
    except Exception:
        if opened_process is not None:
            opened_process.close()
        raise
    return thread
