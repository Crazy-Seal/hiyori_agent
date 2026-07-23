from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_mcp_service
from app.routes.mcp import router


class _Service:
    def list_servers(self):
        return [{"config": {"id": "demo"}, "runtime": {"status": "available"}}]

    async def test_server(self, server):
        return {"status": "available", "tools": [{"name": "echo"}], "id": server.id}

    async def create_server(self, server):
        return {"config": server.model_dump(mode="json"), "runtime": {"status": "disconnected"}}

    async def update_server(self, server_id, server):
        assert server_id == server.id
        return {"config": server.model_dump(mode="json"), "runtime": {"status": "disconnected"}}

    async def delete_server(self, server_id):
        return [f"session-for-{server_id}"]

    async def reconnect(self, server_id):
        return {"config": {"id": server_id}, "runtime": {"status": "available"}}

    def list_tools(self, _server_id):
        return [{"name": "echo"}]


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_mcp_service] = lambda: _Service()
    return TestClient(app)


def test_mcp_server_routes_use_result_wrapper() -> None:
    with _client() as client:
        listed = client.get("/mcp/servers")
        tested = client.post(
            "/mcp/servers/test",
            json={
                "id": "demo",
                "name": "Demo",
                "transport": "stdio",
                "command": "python",
            },
        )
        created = client.post(
            "/mcp/servers",
            json={
                "id": "demo",
                "name": "Demo",
                "transport": "stdio",
                "command": "python",
            },
        )

    assert listed.json()["data"][0]["runtime"]["status"] == "available"
    assert tested.json()["data"]["tools"] == [{"name": "echo"}]
    assert created.json()["code"] == 200


def test_mcp_server_routes_update_reconnect_tools_and_delete() -> None:
    with _client() as client:
        updated = client.put(
            "/mcp/servers/demo",
            json={
                "id": "demo",
                "name": "Demo 2",
                "transport": "streamable_http",
                "url": "http://127.0.0.1:9000/mcp",
            },
        )
        reconnected = client.post("/mcp/servers/demo/reconnect")
        tools = client.get("/mcp/servers/demo/tools")
        deleted = client.delete("/mcp/servers/demo")

    assert updated.json()["data"]["config"]["name"] == "Demo 2"
    assert reconnected.json()["data"]["runtime"]["status"] == "available"
    assert tools.json()["data"] == [{"name": "echo"}]
    assert deleted.json()["data"]["affected_sessions"] == ["session-for-demo"]
