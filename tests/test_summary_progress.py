import asyncio
import sqlite3
from datetime import date

import pytest

from app.agent.memory.config import MemoryConfig
from app.agent.memory.memories.summary import SummaryMemory
from app.agent.memory.store.diary_sqlite_store import DiarySqliteStore


def test_summary_progress_is_persisted_with_summary(tmp_path) -> None:
    async def scenario() -> tuple[str | None, int]:
        store = DiarySqliteStore(str(tmp_path / "memory.sqlite3"))
        target_date = date(2026, 7, 10)
        await store.add_summary_with_progress(
            session_id="session",
            date_obj=target_date,
            content="summary",
            summarized_human_count=11,
        )
        return (
            await store.get("session", target_date, is_diary=False),
            await store.get_summary_progress("session", target_date),
        )

    assert asyncio.run(scenario()) == ("summary", 11)


def test_summary_and_progress_roll_back_together(tmp_path) -> None:
    async def scenario() -> tuple[str | None, int]:
        db_path = tmp_path / "memory.sqlite3"
        store = DiarySqliteStore(str(db_path))
        target_date = date(2026, 7, 10)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                CREATE TRIGGER reject_summary_progress
                BEFORE INSERT ON summary_progress
                BEGIN
                    SELECT RAISE(ABORT, 'reject progress');
                END
                """
            )

        with pytest.raises(sqlite3.IntegrityError, match="reject progress"):
            await store.add_summary_with_progress(
                session_id="session",
                date_obj=target_date,
                content="must roll back",
                summarized_human_count=10,
            )

        return (
            await store.get("session", target_date, is_diary=False),
            await store.get_summary_progress("session", target_date),
        )

    assert asyncio.run(scenario()) == (None, 0)


def test_summary_catches_up_after_exact_threshold_was_missed(tmp_path) -> None:
    class FakeChatHistoryStore:
        def __init__(self) -> None:
            self.human_count = 11

        async def get_message_count_by_date(self, *args, **kwargs):
            return self.human_count

        async def get_messages_by_date(self, *args, **kwargs):
            return [{"role": "Human", "content": "hello"}]

    class FakeResponse:
        content = "generated summary"

    class FakeLlm:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, *args, **kwargs):
            self.calls += 1
            return FakeResponse()

    async def scenario() -> tuple[int, int]:
        memory = SummaryMemory.__new__(SummaryMemory)
        memory.session_id = "session"
        memory.config = MemoryConfig(
            sqlite_path=str(tmp_path / "memory.sqlite3"),
            summary_every_messages=10,
        )
        memory.chat_history_store = FakeChatHistoryStore()
        memory.store = DiarySqliteStore(memory.config.sqlite_path)
        memory.llm = FakeLlm()
        memory._summary_lock = asyncio.Lock()

        async def build_prompt(*args, **kwargs):
            return "prompt"

        memory._build_system_prompt = build_prompt
        target_date = date(2026, 7, 10)

        await memory._check_and_generate_summary(target_date)
        first_progress = await memory.store.get_summary_progress("session", target_date)

        memory.chat_history_store.human_count = 19
        await memory._check_and_generate_summary(target_date)
        memory.chat_history_store.human_count = 20
        await memory._check_and_generate_summary(target_date)

        return memory.llm.calls, first_progress

    calls, first_progress = asyncio.run(scenario())
    assert first_progress == 11
    assert calls == 2


def test_failed_summary_does_not_advance_progress(tmp_path) -> None:
    class FakeHistory:
        async def get_message_count_by_date(self, *args, **kwargs):
            return 10

        async def get_messages_by_date(self, *args, **kwargs):
            return [{"role": "Human", "content": "hello"}]

    class FailingLlm:
        async def ainvoke(self, *args, **kwargs):
            raise RuntimeError("summary failed")

    async def scenario() -> int:
        memory = SummaryMemory.__new__(SummaryMemory)
        memory.session_id = "session"
        memory.config = MemoryConfig(
            sqlite_path=str(tmp_path / "memory.sqlite3"),
            summary_every_messages=10,
        )
        memory.chat_history_store = FakeHistory()
        memory.store = DiarySqliteStore(memory.config.sqlite_path)
        memory.llm = FailingLlm()
        memory._summary_lock = asyncio.Lock()

        async def build_prompt(*args, **kwargs):
            return "prompt"

        memory._build_system_prompt = build_prompt
        target_date = date(2026, 7, 10)
        await memory._check_and_generate_summary(target_date)
        return await memory.store.get_summary_progress("session", target_date)

    assert asyncio.run(scenario()) == 0


def test_concurrent_summary_checks_generate_once(tmp_path) -> None:
    class FakeHistory:
        async def get_message_count_by_date(self, *args, **kwargs):
            return 10

        async def get_messages_by_date(self, *args, **kwargs):
            return [{"role": "Human", "content": "hello"}]

    class SlowLlm:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, *args, **kwargs):
            self.calls += 1
            await asyncio.sleep(0)
            return type("Response", (), {"content": "summary"})()

    async def scenario() -> int:
        memory = SummaryMemory.__new__(SummaryMemory)
        memory.session_id = "session"
        memory.config = MemoryConfig(
            sqlite_path=str(tmp_path / "memory.sqlite3"),
            summary_every_messages=10,
        )
        memory.chat_history_store = FakeHistory()
        memory.store = DiarySqliteStore(memory.config.sqlite_path)
        memory.llm = SlowLlm()
        memory._summary_lock = asyncio.Lock()

        async def build_prompt(*args, **kwargs):
            return "prompt"

        memory._build_system_prompt = build_prompt
        target_date = date(2026, 7, 10)
        await asyncio.gather(
            memory._check_and_generate_summary(target_date),
            memory._check_and_generate_summary(target_date),
        )
        return memory.llm.calls

    assert asyncio.run(scenario()) == 1
