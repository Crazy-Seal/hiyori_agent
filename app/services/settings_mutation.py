from __future__ import annotations

import asyncio


class SettingsMutationCoordinator:
    """协调 MCP 定义与模型级 MCP 权限的跨文件写入。

    Attributes:
        lock: 串行化关联配置写入的异步锁。
    """

    def __init__(self) -> None:
        """创建进程内共享的配置写入锁。"""
        self.lock = asyncio.Lock()
