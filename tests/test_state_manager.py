import asyncio
import json
from pathlib import Path

import aiosqlite
import pytest

from app.agent.core.state_manager import StateManager
from app.agent.state import AgentState


async def checkpoint_rows(manager: StateManager) -> list[tuple[int, str, str]]:
    db = await manager._get_db()
    async with db.execute(
        """
        SELECT id, checkpoint_type, state_json FROM checkpoints
        WHERE session_id = ? ORDER BY id
        """,
        (manager.session_id,),
    ) as cursor:
        return await cursor.fetchall()


def test_intermediate_checkpoint_replaces_previous_one_atomically(tmp_path: Path) -> None:
    async def scenario() -> None:
        manager = StateManager("test-session", db_path=str(tmp_path / "checkpoints.sqlite3"))
        try:
            first = AgentState.create_new("test-session")
            first.add_assistant_message("第一个中间态")
            first_id = await manager.save(first, checkpoint_type="intermediate")

            db = await manager._get_db()
            await db.execute("""
                CREATE TRIGGER prevent_intermediate_delete
                BEFORE DELETE ON checkpoints
                WHEN OLD.checkpoint_type = 'intermediate'
                BEGIN
                    SELECT RAISE(ABORT, '模拟删除旧中间态失败');
                END
            """)
            await db.commit()

            failed = AgentState.from_checkpoint(first.to_checkpoint())
            failed.add_assistant_message("不应提交的中间态")
            with pytest.raises(aiosqlite.IntegrityError, match="模拟删除旧中间态失败"):
                await manager.save(failed, checkpoint_type="intermediate")

            rows_after_failure = await checkpoint_rows(manager)
            assert [row[0] for row in rows_after_failure] == [first_id]

            await db.execute("DROP TRIGGER prevent_intermediate_delete")
            await db.commit()
            second = AgentState.from_checkpoint(first.to_checkpoint())
            second.add_assistant_message("第二个中间态")
            second_id = await manager.save(second, checkpoint_type="intermediate")

            rows = await checkpoint_rows(manager)
            assert [(row[0], row[1]) for row in rows] == [(second_id, "intermediate")]
        finally:
            await manager.close()

    asyncio.run(scenario())

def test_completed_checkpoint_removes_intermediate_and_keeps_latest_thirty(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        manager = StateManager("test-session", db_path=str(tmp_path / "checkpoints.sqlite3"))
        try:
            state = AgentState.create_new("test-session")
            await manager.save(state, checkpoint_type="intermediate")

            total = StateManager.MAX_COMPLETED_CHECKPOINTS_PER_SESSION + 5
            for index in range(total):
                state = AgentState.create_new("test-session")
                state.add_assistant_message(f"完成态 {index}")
                await manager.save(state, checkpoint_type="completed")

            rows = await checkpoint_rows(manager)
            assert len(rows) == StateManager.MAX_COMPLETED_CHECKPOINTS_PER_SESSION
            assert {row[1] for row in rows} == {"completed"}
            first_retained = AgentState.from_checkpoint(json.loads(rows[0][2]))
            assert first_retained.messages[-1]["content"] == "完成态 5"

            intermediate = AgentState.create_new("test-session")
            intermediate.add_assistant_message("最新中间态")
            await manager.save(intermediate, checkpoint_type="intermediate")
            rows = await checkpoint_rows(manager)
            assert len(rows) == StateManager.MAX_COMPLETED_CHECKPOINTS_PER_SESSION + 1
            assert [row[1] for row in rows].count("intermediate") == 1
            assert (await manager.load()).messages[-1]["content"] == "最新中间态"
        finally:
            await manager.close()

    asyncio.run(scenario())
