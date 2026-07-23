"""本地 HTTP API 的认证、Host 与 Origin 防护。"""

from __future__ import annotations

import hmac
import os
from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


API_TOKEN_ENV = "AYAYA_API_TOKEN"
MIN_API_TOKEN_CHARS = 43
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "[::1]"]


def load_api_token() -> str:
    """读取并验证本地 API Token。

    Returns:
        由统一启动器提供的临时 Token。

    Raises:
        RuntimeError: Token 缺失或长度不足。
    """
    token = os.environ.get(API_TOKEN_ENV, "")
    if len(token) < MIN_API_TOKEN_CHARS:
        raise RuntimeError(
            f"{API_TOKEN_ENV} 缺失或长度不足，必须由桌面启动器提供临时 Token"
        )
    return token


class LocalApiAuthMiddleware:
    """保护除根存活检查外的全部本地 HTTP 接口。"""

    def __init__(self, app: ASGIApp, *, token: str) -> None:
        """初始化本地 API 认证中间件。

        Args:
            app: 下游 ASGI 应用。
            token: 当前进程有效的 Bearer Token。
        """
        self.app = app
        self._token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """验证 HTTP 请求并转发已授权流量。"""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", "")).upper()
        path = str(scope.get("path", ""))
        if method == "GET" and path == "/":
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        if headers.get("origin"):
            await JSONResponse(
                {"detail": "Forbidden"},
                status_code=403,
            )(scope, receive, send)
            return

        authorization = headers.get("authorization", "")
        prefix = "Bearer "
        supplied = authorization[len(prefix):] if authorization.startswith(prefix) else ""
        if not supplied or not hmac.compare_digest(supplied, self._token):
            await JSONResponse(
                {"detail": "Unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )(scope, receive, send)
            return

        await self.app(scope, receive, send)


def install_local_api_security(app: FastAPI, token: str) -> None:
    """为 FastAPI 应用安装本地 API 安全边界。

    Args:
        app: 待保护的 FastAPI 应用。
        token: 当前启动周期的 Bearer Token。
    """
    if len(token) < MIN_API_TOKEN_CHARS:
        raise ValueError("本地 API Token 长度不足")
    app.add_middleware(LocalApiAuthMiddleware, token=token)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
