"""
状态管理器

负责 Agent 状态的 checkpoint 持久化与分层裁剪。
"""

import json
import logging
import os
from datetime import datetime
from typing import Literal

import aiosqlite

from app.agent.state import AgentState
from app.runtime import get_checkpoint_db

logger = logging.getLogger(__name__)

CheckpointType = Literal["intermediate", "completed"]


class StateManager:
    """状态管理器 - checkpoint 和状态持久化。"""

    # 每个 session 最多保留的完成态数量；中间态另外最多保留一条。
    MAX_COMPLETED_CHECKPOINTS_PER_SESSION = 30

    def __init__(
        self,
        session_id: str,
        db_path: str | None = None,
    ):
        self.session_id = session_id
        self.db_path = str(db_path or get_checkpoint_db())
        self._db: aiosqlite.Connection | None = None

    async def _get_db(self) -> aiosqlite.Connection:
        """获取数据库连接。"""
        if self._db is None:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self._db = await aiosqlite.connect(self.db_path)
            await self._init_tables()
        return self._db

    async def _init_tables(self) -> None:
        """初始化 checkpoint 表和查询索引。"""
        db = await self._get_db()
        await db.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                state_json TEXT NOT NULL,
                checkpoint_type TEXT NOT NULL DEFAULT 'completed'
                    CHECK(checkpoint_type IN ('intermediate', 'completed')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_checkpoints_session_type_id
            ON checkpoints(session_id, checkpoint_type, id DESC)
        """)
        await db.commit()

    async def load(self) -> AgentState:
        """从最新 checkpoint 恢复状态；没有记录时创建新状态。"""
        db = await self._get_db()

        async with db.execute(
            """
            SELECT id, state_json FROM checkpoints
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (self.session_id,),
        ) as cursor:
            row = await cursor.fetchone()

        if row:
            checkpoint_id, state_json = row
            state = AgentState.from_checkpoint(json.loads(state_json))
            logger.info("从 checkpoint %s 恢复状态: %s", checkpoint_id, self.session_id)
            return state

        logger.info("创建新状态: %s", self.session_id)
        return AgentState.create_new(self.session_id)

    async def save(
        self,
        state: AgentState,
        *,
        checkpoint_type: CheckpointType,
    ) -> int:
        """原子保存指定类型的 checkpoint，并执行对应的分层裁剪。"""
        db = await self._get_db()
        state_json = json.dumps(state.to_checkpoint(), ensure_ascii=False, default=str)

        try:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                INSERT INTO checkpoints (
                    session_id, state_json, checkpoint_type, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    self.session_id,
                    state_json,
                    checkpoint_type,
                    datetime.now().isoformat(),
                ),
            )
            checkpoint_id = cursor.lastrowid
            if checkpoint_id is None:
                raise RuntimeError("数据库未返回 checkpoint ID")

            if checkpoint_type == "intermediate":
                await db.execute(
                    """
                    DELETE FROM checkpoints
                    WHERE session_id = ?
                      AND checkpoint_type = 'intermediate'
                      AND id <> ?
                    """,
                    (self.session_id, checkpoint_id),
                )
            else:
                # 完成态已包含本轮完整状态，对应中间态不再有恢复价值。
                await db.execute(
                    """
                    DELETE FROM checkpoints
                    WHERE session_id = ? AND checkpoint_type = 'intermediate'
                    """,
                    (self.session_id,),
                )
                await self._prune_completed(db)

            await db.commit()
        except BaseException:
            await db.rollback()
            raise

        logger.info(
            "保存%s checkpoint %s: %s",
            "中间态" if checkpoint_type == "intermediate" else "完成态",
            checkpoint_id,
            self.session_id,
        )
        return checkpoint_id

    async def _prune_completed(self, db: aiosqlite.Connection) -> None:
        """仅裁剪完成态，保留当前 session 最新的 30 条。"""
        await db.execute(
            """
            DELETE FROM checkpoints
            WHERE session_id = ?
              AND checkpoint_type = 'completed'
              AND id NOT IN (
                SELECT id FROM checkpoints
                WHERE session_id = ? AND checkpoint_type = 'completed'
                ORDER BY id DESC
                LIMIT ?
            )
            """,
            (
                self.session_id,
                self.session_id,
                self.MAX_COMPLETED_CHECKPOINTS_PER_SESSION,
            ),
        )

    async def clear_session(self) -> int:
        """清空指定 session 的所有 checkpoint，并返回删除数量。"""
        db = await self._get_db()

        async with db.execute(
            "SELECT COUNT(*) FROM checkpoints WHERE session_id = ?",
            (self.session_id,),
        ) as cursor:
            row = await cursor.fetchone()
            deleted_count = row[0] if row else 0

        await db.execute(
            "DELETE FROM checkpoints WHERE session_id = ?",
            (self.session_id,),
        )
        await db.commit()

        logger.info("清空 session %s: 删除了 %s 个 checkpoint", self.session_id, deleted_count)
        return deleted_count

    async def close(self) -> None:
        """关闭数据库连接。"""
        if self._db:
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> "StateManager":
        await self._get_db()
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()
