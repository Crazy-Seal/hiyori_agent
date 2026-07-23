from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.security.local_api import install_local_api_security


TEST_TOKEN = "t" * 43


def _secured_app(call_counter: list[str]) -> FastAPI:
    app = FastAPI()
    install_local_api_security(app, TEST_TOKEN)

    @app.get("/")
    def root():
        return {"ok": True}

    @app.post("/sensitive")
    def sensitive():
        call_counter.append("called")
        return {"ok": True}

    return app


def test_sensitive_api_requires_valid_bearer_token() -> None:
    calls: list[str] = []
    client = TestClient(_secured_app(calls), base_url="http://127.0.0.1")

    assert client.post("/sensitive").status_code == 401
    assert client.post(
        "/sensitive", headers={"Authorization": "Bearer wrong"}
    ).status_code == 401
    assert calls == []

    accepted = client.post(
        "/sensitive", headers={"Authorization": f"Bearer {TEST_TOKEN}"}
    )
    assert accepted.status_code == 200
    assert calls == ["called"]


def test_local_api_rejects_untrusted_host_and_origin() -> None:
    calls: list[str] = []
    client = TestClient(_secured_app(calls), base_url="http://127.0.0.1")
    auth = {"Authorization": f"Bearer {TEST_TOKEN}"}

    assert client.post(
        "http://evil.example/sensitive", headers=auth
    ).status_code == 400
    assert client.post(
        "/sensitive", headers={**auth, "Origin": "http://evil.example"}
    ).status_code == 403
    assert calls == []


def test_public_root_is_the_only_token_free_endpoint() -> None:
    client = TestClient(_secured_app([]), base_url="http://127.0.0.1")

    assert client.get("/").status_code == 200
    assert client.get("/openapi.json").status_code == 401
