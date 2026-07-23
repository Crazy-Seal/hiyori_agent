"""由桌面端受控启动的 Uvicorn 服务入口。"""

from __future__ import annotations

import uvicorn

from app.parent_process_monitor import start_parent_process_monitor


def run() -> None:
    """在固定回环地址启动后端，并公开优雅关闭句柄。"""
    from main import app

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
        timeout_graceful_shutdown=5,
    )
    server = uvicorn.Server(config)
    app.state.uvicorn_server = server
    start_parent_process_monitor(
        lambda: setattr(server, "should_exit", True),
    )
    server.run()


if __name__ == "__main__":
    run()
