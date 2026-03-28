import importlib.util
import re
import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

# 通过文件路径加载 main.py，避免受当前工作目录影响
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.crud.chat_history_dao import ChatHistoryDao

MAIN_FILE = PROJECT_ROOT / "main.py"
_spec = importlib.util.spec_from_file_location("demo_main", MAIN_FILE)
if _spec is None or _spec.loader is None:
    raise RuntimeError("Unable to load main.py for tests")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
app = _module.app

client = TestClient(app)
TEST_SESSION_ID = "a9ea0407-6a54-4535-b424-b7cd454d7bcd"


def test_root():
    # 根路径应可正常访问
    response = client.get("/")
    assert response.status_code == 200
    assert "LangGraph Agent" in response.json()["message"]


def test_health():
    # 健康检查应返回 Result 包装与基本运行信息
    response = client.get(f"/health?session_id={TEST_SESSION_ID}")
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    assert body["msg"] == "success"
    data = body["data"]
    assert data["status"] == "ok"
    assert isinstance(data["model"], str)
    assert data["model"]


def test_chat_basic():
    # 聊天接口应返回 SSE 流，包含分片事件与结束标记（含 session_id）
    payload = {"message": "这是一条测试消息，收到请回复", "session_id": TEST_SESSION_ID}
    response = client.post("/chat", json=payload)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    body = response.text
    assert "data: " in body
    assert "\n\ndata: [DONE]" in body or body.strip().endswith("data: [DONE]")


def test_chat_settings_crud_flow():
    session_id = f"test-{uuid.uuid4()}"
    add_payload = {
        "session_id": session_id,
        "model_name": "gpt-4o-mini",
        "openai_api_key": "sk-test-key",
        "openai_base_url": "https://api.example.com/v1",
        "temperature": 0.3,
        "system_prompt": "你是一个测试助手",
        "tools_list": ["multiply"],
    }

    add_resp = client.post("/chat_settings", json=add_payload)
    assert add_resp.status_code == 200
    add_body = add_resp.json()
    assert add_body["code"] == 200
    assert add_body["msg"] == "success"
    assert add_body["data"] is None

    get_resp = client.get(f"/chat_settings/{session_id}")
    assert get_resp.status_code == 200
    get_body = get_resp.json()
    assert get_body["code"] == 200
    assert get_body["msg"] == "success"
    assert get_body["data"]["session_id"] == session_id
    assert get_body["data"]["openai_api_key"] == add_payload["openai_api_key"]
    assert get_body["data"]["system_prompt"] == add_payload["system_prompt"]
    assert get_body["data"]["tools_list"] == add_payload["tools_list"]

    update_payload = {
        "session_id": session_id,
        "model_name": "gpt-4.1-mini",
        "openai_api_key": "sk-updated-key",
        "openai_base_url": "https://api.example.com/v1",
        "temperature": 0.6,
        "system_prompt": "你是一个更新后的测试助手",
        "tools_list": ["get_current_utc_time"],
    }
    update_resp = client.put("/chat_settings", json=update_payload)
    assert update_resp.status_code == 200
    update_body = update_resp.json()
    assert update_body["code"] == 200
    assert update_body["msg"] == "success"
    assert update_body["data"] is None

    delete_resp = client.delete(f"/chat_settings/{session_id}")
    assert delete_resp.status_code == 200
    delete_body = delete_resp.json()
    assert delete_body["code"] == 200
    assert delete_body["msg"] == "success"
    assert delete_body["data"] is None

    missing_resp = client.get(f"/chat_settings/{session_id}")
    assert missing_resp.status_code == 404


def test_chat_history_timezone_and_result_wrapper():
    chat_history_dao = ChatHistoryDao()
    session_id = f"history-{uuid.uuid4()}"
    chat_history_dao.save_chat_message(session_id, "Human", "history test user")
    chat_history_dao.save_chat_message(session_id, "AI", "history test ai")

    response = client.get(f"/chat_history/{session_id}?start=0&limit=2")
    assert response.status_code == 200

    body = response.json()
    assert body["code"] == 200
    assert body["msg"] == "success"
    assert isinstance(body["data"], list)
    assert len(body["data"]) == 2

    for item in body["data"]:
        assert item["role"] in {"Human", "AI"}
        assert isinstance(item["content"], str)
        assert isinstance(item["timestamp"], str)
        assert "T" in item["timestamp"]
        assert re.search(r"[+-]\d{2}:\d{2}$", item["timestamp"]) is not None

    paged_response = client.get(f"/chat_history/{session_id}?start=1&limit=1")
    assert paged_response.status_code == 200
    paged_body = paged_response.json()
    assert len(paged_body["data"]) == 1
    assert paged_body["data"][0]["role"] == "AI"
