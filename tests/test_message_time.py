import asyncio
import json
import sqlite3
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app.agent.context_strategy import ContextStrategyConfig, ContextStrategyManager
from app.agent.core.state_manager import StateManager
from app.crud.chat_history_dao import ChatHistoryDao
from app.agent.message import Message, messages_from_openai_format
from app.agent.message_time import RuntimeContext, project_messages_with_time
from app.agent.memory.manager import MemoryManager
from app.agent.memory.memories.semantic_mem0 import Mem0SemanticMemory
from app.agent.state import AgentState


FIXED_TIME = datetime(2026, 7, 12, 3, 4, 5, tzinfo=timezone.utc)


def test_message_round_trip_preserves_created_at() -> None:
    message = Message.user_message("原始输入")
    message.timestamp = FIXED_TIME
    payload = message.to_openai_format()
    payload["_created_at"] = FIXED_TIME.isoformat()

    restored = messages_from_openai_format([payload])[0]

    assert restored.content == "原始输入"
    assert restored.timestamp == FIXED_TIME


def test_time_projection_covers_dialogue_and_screenshot_without_mutation() -> None:
    messages = [
        {"role": "user", "content": "你好", "_created_at": FIXED_TIME.isoformat()},
        {"role": "assistant", "content": "你好呀", "_created_at": FIXED_TIME.isoformat()},
        {
            "role": "user",
            "name": "system_screenshot",
            "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,x"}}],
            "_created_at": FIXED_TIME.isoformat(),
        },
        {"role": "tool", "content": "结果", "_created_at": FIXED_TIME.isoformat()},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c1"}],
            "_created_at": FIXED_TIME.isoformat(),
        },
    ]
    original = deepcopy(messages)

    projected = project_messages_with_time(messages)

    assert "发送时间：2026-07-12 11:04:05 +0800 星期日" in projected[0]["content"]
    assert "发送时间：2026-07-12 11:04:05 +0800 星期日" in projected[1]["content"]
    assert projected[2]["content"][0]["type"] == "text"
    assert projected[3]["content"] == "结果"
    assert projected[4]["content"] == ""
    assert messages == original


def test_context_strategy_projects_time_and_removes_internal_metadata() -> None:
    state = AgentState.create_new("time-test")
    state.messages = [
        {"role": "user", "content": "你好", "_created_at": FIXED_TIME.isoformat()}
    ]
    manager = ContextStrategyManager(ContextStrategyConfig())

    result = manager.build_model_window(state)

    assert "发送时间" in result[0]["content"]
    assert "_created_at" not in result[0]
    assert state.messages[0]["content"] == "你好"


def _create_legacy_db(path: Path) -> None:
    legacy = "[2026-07-12 11:04:05 +0800 星期日] 原始输入"
    state = AgentState.create_new("legacy")
    state.messages = [{"role": "user", "content": legacy, "_message_id": "m1"}]
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE checkpoints (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, "
            "state_json TEXT NOT NULL, checkpoint_type TEXT NOT NULL DEFAULT 'completed', created_at TIMESTAMP)"
        )
        conn.execute(
            "CREATE TABLE chat_history (id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL, "
            "timestamp DATETIME, role TEXT NOT NULL, content TEXT NOT NULL, image_description TEXT, "
            "image_filenames TEXT, source_message_id TEXT)"
        )
        conn.execute(
            "INSERT INTO checkpoints(session_id,state_json,checkpoint_type,created_at) VALUES(?,?,?,?)",
            (
                "legacy",
                json.dumps(state.to_checkpoint(), ensure_ascii=False, default=str),
                "completed",
                "2026-07-12 11:05:00",
            ),
        )
        conn.execute(
            "INSERT INTO chat_history(thread_id,timestamp,role,content,source_message_id) VALUES(?,?,?,?,?)",
            ("legacy", "2026-07-12 11:05:00", "Human", legacy, "m1:content"),
        )
        conn.execute(
            "INSERT INTO chat_history(thread_id,timestamp,role,content,source_message_id) VALUES(?,?,?,?,?)",
            ("legacy", "2026-07-12 11:06:00", "Human", "[TODO] 保留方括号", "m2:content"),
        )


def test_state_manager_startup_does_not_clean_legacy_content(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.sqlite3"
    _create_legacy_db(db_path)

    async def scenario() -> tuple[str, str, bool, str]:
        manager = StateManager("legacy", db_path=str(db_path))
        state = await manager.load()
        await manager.close()
        with sqlite3.connect(db_path) as conn:
            history_content = conn.execute(
                "SELECT content FROM chat_history WHERE source_message_id='m1:content'"
            ).fetchone()
            table_names = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            has_migration_table = "schema_" + "migrations" in table_names
        visible_history = await ChatHistoryDao(db_path=db_path).list_chat_history_async(
            "legacy"
        )
        bracket_content = next(
            item["content"] for item in visible_history if item["id"] == "m2:content"
        )
        return (
            state.messages[0]["content"],
            history_content[0],
            has_migration_table,
            bracket_content,
        )

    (
        checkpoint_content,
        history_content,
        has_migration_table,
        bracket_content,
    ) = asyncio.run(scenario())

    assert checkpoint_content.startswith("[2026-07-12 11:04:05 +0800 星期日]")
    assert history_content.startswith("[2026-07-12 11:04:05 +0800 星期日]")
    assert has_migration_table is False
    assert bracket_content == "[TODO] 保留方括号"


def test_runtime_context_formats_fixed_execution_time() -> None:
    context = RuntimeContext(started_at=FIXED_TIME)

    assert context.system_text == "当前本地日期时间：2026-07-12 11:04:05 +0800 星期日"


def test_episodic_and_semantic_inputs_include_structured_message_time() -> None:
    message = Message.user_message("我准备学习 Python")
    message.timestamp = FIXED_TIME

    manager = object.__new__(MemoryManager)
    manager.chat_settings = SimpleNamespace(address="主人", name="Ayaya")
    episodic_text = manager._format_messages([message])

    semantic = object.__new__(Mem0SemanticMemory)
    semantic_messages = semantic._convert_messages([message])

    assert "[发送时间：2026-07-12 11:04:05 +0800 星期日]" in episodic_text
    assert "[发送时间：2026-07-12 11:04:05 +0800 星期日]" in semantic_messages[0]["content"]
