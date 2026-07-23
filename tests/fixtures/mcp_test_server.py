"""真实 MCP SDK 集成测试服务，不读写项目运行时数据。"""

from __future__ import annotations

import os
import sys

from mcp.server.fastmcp import FastMCP


transport = sys.argv[1]
port = int(sys.argv[2]) if len(sys.argv) > 2 else 8000
server = FastMCP(
    "Ayaya integration test",
    instructions="integration-test-only",
    host="127.0.0.1",
    port=port,
    stateless_http=True,
    json_response=True,
)


@server.tool()
def echo(value: str) -> dict[str, str]:
    """Return the supplied value."""
    return {"value": value}


@server.tool()
def read_environment(name: str) -> str:
    """Read one environment variable for transport inheritance tests."""
    return os.environ.get(name, "")


if transport == "http":
    import uvicorn

    app = server.streamable_http_app()

    class RequireIntegrationHeader:
        def __init__(self, inner):
            self.inner = inner

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                headers = {key.lower(): value for key, value in scope.get("headers", [])}
                if headers.get(b"x-integration-test") != b"plain-local-value":
                    await send({"type": "http.response.start", "status": 403, "headers": []})
                    await send({"type": "http.response.body", "body": b"missing test header"})
                    return
            await self.inner(scope, receive, send)

    uvicorn.run(RequireIntegrationHeader(app), host="127.0.0.1", port=port, log_level="error")
else:
    server.run(transport="stdio")
