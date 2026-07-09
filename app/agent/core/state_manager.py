"""
状态管理器

负责 Agent 状态的 checkpoint 持久化与分层裁剪。
"""

import json
import logging
import os
import shutil
from datetime import datetime
from typing import Literal
from uuid import uuid4

import aiosqlite

from app.agent.message import is_real_human_message
from app.agent.state import AgentState
from app.agent.utils.domain.text import extract_text
from app.runtime import get_checkpoint_db, get_legacy_chat_history_db

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
        self.last_loaded_checkpoint_type: CheckpointType | None = None

    async def _get_db(self) -> aiosqlite.Connection:
        """获取数据库连接。"""
        if self._db is None:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self._db = await aiosqlite.connect(self.db_path)
            await self._init_tables()
        return self._db

    async def _init_tables(self) -> None:
        """初始化 checkpoint、聊天记录和迁移元数据表。"""
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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                image_description TEXT,
                image_filenames TEXT,
                source_message_id TEXT
            )
        """)
        columns = {
            row[1]
            for row in await db.execute_fetchall("PRAGMA table_info(chat_history)")
        }
        if "source_message_id" not in columns:
            await db.execute(
                "ALTER TABLE chat_history ADD COLUMN source_message_id TEXT"
            )
        index_rows = await db.execute_fetchall(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'index' AND name = 'idx_chat_history_source_message'
            """
        )
        if index_rows and " WHERE " in (index_rows[0][0] or "").upper():
            await db.execute("DROP INDEX idx_chat_history_source_message")
        await db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_history_source_message
            ON chat_history(source_message_id)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_chat_history_thread_timestamp
            ON chat_history(thread_id, timestamp, id)
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS storage_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMP NOT NULL
            )
        """)
        await db.commit()
        await self._migrate_legacy_chat_history()

    async def _migrate_legacy_chat_history(self) -> None:
        """将旧聊天数据库一次性复制到统一数据库。"""
        legacy_path = get_legacy_chat_history_db()
        if os.path.abspath(self.db_path) != os.path.abspath(str(get_checkpoint_db())):
            return
        if (
            not legacy_path.exists()
            or os.path.abspath(str(legacy_path.resolve()))
            == os.path.abspath(self.db_path)
        ):
            return

        db = await self._get_db()
        version = "chat-history-unified-v1"
        if await db.execute_fetchall(
            "SELECT 1 FROM storage_migrations WHERE version = ?",
            (version,),
        ):
            return

        backup_path = legacy_path.with_suffix(f"{legacy_path.suffix}.bak")
        if not backup_path.exists():
            shutil.copy2(legacy_path, backup_path)

        attached = False
        try:
            await db.execute("ATTACH DATABASE ? AS legacy_chat", (str(legacy_path),))
            attached = True
            await db.execute("BEGIN IMMEDIATE")
            legacy_table = await db.execute_fetchall(
                """
                SELECT 1 FROM legacy_chat.sqlite_master
                WHERE type = 'table' AND name = 'chat_history'
                """
            )
            if legacy_table:
                await db.execute(
                    """
                    INSERT OR IGNORE INTO chat_history (
                        id, thread_id, timestamp, role, content,
                        image_description, image_filenames, source_message_id
                    )
                    SELECT id, thread_id, timestamp, role, content,
                           image_description, image_filenames, NULL
                    FROM legacy_chat.chat_history
                    ORDER BY id
                    """
                )
            await self._merge_latest_checkpoint_tails(db)
            await db.execute(
                """
                INSERT INTO storage_migrations(version, applied_at)
                VALUES (?, ?)
                """,
                (version, datetime.now().isoformat()),
            )
            await db.commit()
        except BaseException:
            await db.rollback()
            raise
        finally:
            if attached:
                await db.execute("DETACH DATABASE legacy_chat")

    async def _merge_latest_checkpoint_tails(
        self,
        db: aiosqlite.Connection,
    ) -> None:
        """迁移时把最新 checkpoint 中缺失的可见尾部补入聊天记录。"""
        checkpoint_rows = await db.execute_fetchall(
            """
            SELECT c.id, c.state_json
            FROM checkpoints c
            JOIN (
                SELECT session_id, MAX(id) AS latest_id
                FROM checkpoints
                GROUP BY session_id
            ) latest ON latest.latest_id = c.id
            """
        )
        for checkpoint_id, state_json in checkpoint_rows:
            state = AgentState.from_checkpoint(json.loads(state_json))
            self._ensure_message_metadata(state)
            projected = self._history_rows(state)
            existing = await db.execute_fetchall(
                """
                SELECT id, role, content
                FROM chat_history
                WHERE thread_id = ?
                ORDER BY timestamp, id
                """,
                (state.session_id,),
            )

            max_overlap = min(len(existing), len(projected))
            overlap = 0
            for size in range(max_overlap, 0, -1):
                existing_tail = [
                    (row[1], row[2]) for row in existing[-size:]
                ]
                projected_head = [
                    (row[2], row[3]) for row in projected[:size]
                ]
                if existing_tail == projected_head:
                    overlap = size
                    break

            if overlap:
                for existing_row, projected_row in zip(
                    existing[-overlap:],
                    projected[:overlap],
                ):
                    await db.execute(
                        """
                        UPDATE chat_history
                        SET source_message_id = COALESCE(source_message_id, ?)
                        WHERE id = ?
                        """,
                        (projected_row[6], existing_row[0]),
                    )

            if projected[overlap:]:
                await db.executemany(
                    """
                    INSERT OR IGNORE INTO chat_history (
                        thread_id, timestamp, role, content,
                        image_description, image_filenames, source_message_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    projected[overlap:],
                )
            await db.execute(
                "UPDATE checkpoints SET state_json = ? WHERE id = ?",
                (
                    json.dumps(
                        state.to_checkpoint(),
                        ensure_ascii=False,
                        default=str,
                    ),
                    checkpoint_id,
                ),
            )

    @staticmethod
    def _ensure_message_metadata(state: AgentState) -> None:
        for message in state.messages:
            message.setdefault("_message_id", uuid4().hex)
            message.setdefault("_created_at", state.updated_at.isoformat())

    @staticmethod
    def _history_rows(state: AgentState) -> list[tuple]:
        rows: list[tuple] = []
        for message in state.messages:
            message_id = message["_message_id"]
            created_at = message["_created_at"]
            role = message.get("role")
            content = extract_text(message.get("content"))
            filenames = message.get("image_filenames")
            filenames_json = (
                json.dumps(filenames, ensure_ascii=False) if filenames else None
            )

            if role == "user" and is_real_human_message(message):
                rows.append(
                    (
                        state.session_id,
                        created_at,
                        "Human",
                        content,
                        message.get("image_description"),
                        filenames_json,
                        f"{message_id}:content",
                    )
                )
                continue

            if role != "assistant":
                continue
            if content:
                rows.append(
                    (
                        state.session_id,
                        created_at,
                        "AI",
                        content,
                        None,
                        None,
                        f"{message_id}:content",
                    )
                )
            tool_calls = message.get("tool_calls") or []
            if tool_calls:
                tool_names = [
                    (tool_call.get("function") or {}).get("name", "未知工具")
                    for tool_call in tool_calls
                ]
                rows.append(
                    (
                        state.session_id,
                        created_at,
                        "AI_Tool_Calling",
                        f"调用了工具: {', '.join(tool_names)}",
                        None,
                        None,
                        f"{message_id}:tools",
                    )
                )
        return rows

    async def load(self) -> AgentState:
        """从最新 checkpoint 恢复状态；没有记录时创建新状态。"""
        db = await self._get_db()

        async with db.execute(
            """
            SELECT id, state_json, checkpoint_type FROM checkpoints
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (self.session_id,),
        ) as cursor:
            row = await cursor.fetchone()

        if row:
            checkpoint_id, state_json, checkpoint_type = row
            self.last_loaded_checkpoint_type = checkpoint_type
            state = AgentState.from_checkpoint(json.loads(state_json))
            logger.info("从 checkpoint %s 恢复状态: %s", checkpoint_id, self.session_id)
            return state

        logger.info("创建新状态: %s", self.session_id)
        self.last_loaded_checkpoint_type = None
        return AgentState.create_new(self.session_id)

    async def save(
        self,
        state: AgentState,
        *,
        checkpoint_type: CheckpointType,
    ) -> int:
        """原子保存指定类型的 checkpoint，并执行对应的分层裁剪。"""
        db = await self._get_db()
        self._ensure_message_metadata(state)
        state_json = json.dumps(state.to_checkpoint(), ensure_ascii=False, default=str)
        history_rows = self._history_rows(state)

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

            if history_rows:
                await db.executemany(
                    """
                    INSERT INTO chat_history (
                        thread_id, timestamp, role, content,
                        image_description, image_filenames, source_message_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_message_id) DO UPDATE SET
                        image_description = COALESCE(
                            excluded.image_description,
                            chat_history.image_description
                        ),
                        image_filenames = COALESCE(
                            excluded.image_filenames,
                            chat_history.image_filenames
                        )
                    """,
                    history_rows,
                )

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
