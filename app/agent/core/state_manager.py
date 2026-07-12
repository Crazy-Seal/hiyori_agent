"""
状态管理器

负责 Agent 状态的 checkpoint 持久化与分层裁剪。
"""

import json
import logging
import os
from datetime import datetime
from typing import Literal
from uuid import uuid4

import aiosqlite

from app.agent.message import is_real_human_message
from app.agent.state import AgentState
from app.agent.utils.domain.text import extract_text
from app.agent.message_time import normalize_utc, strip_legacy_time_prefix, utc_now
from app.runtime import get_checkpoint_db

logger = logging.getLogger(__name__)

CheckpointType = Literal["intermediate", "completed"]


class StateManager:
    """状态管理器 - checkpoint 和状态持久化。"""

    # 每个 session 最多保留的完成态数量；中间态另外最多保留一条。
    MAX_COMPLETED_CHECKPOINTS_PER_SESSION = 30
    MESSAGE_TIME_MIGRATION = "message_time_metadata_v1"

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
        """初始化 checkpoint 与聊天记录表。"""
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
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name TEXT PRIMARY KEY,
                applied_at TIMESTAMP NOT NULL
            )
        """)
        await db.commit()
        await self._migrate_message_time_metadata(db)

    @staticmethod
    def _normalize_timestamp(value: object) -> str | None:
        if not isinstance(value, (str, datetime)) or not value:
            return None
        try:
            return normalize_utc(value).isoformat()
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clean_legacy_message_content(message: dict) -> datetime | None:
        content = message.get("content")
        if isinstance(content, str):
            cleaned, timestamp = strip_legacy_time_prefix(content)
            message["content"] = cleaned
            return timestamp
        if not isinstance(content, list):
            return None
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "text":
                continue
            cleaned, timestamp = strip_legacy_time_prefix(str(part.get("text", "")))
            if timestamp is not None:
                part["text"] = cleaned
                return timestamp
        return None

    async def _migrate_message_time_metadata(
        self,
        db: aiosqlite.Connection,
    ) -> None:
        applied = await db.execute_fetchall(
            "SELECT 1 FROM schema_migrations WHERE name = ?",
            (self.MESSAGE_TIME_MIGRATION,),
        )
        if applied:
            return

        try:
            await db.execute("BEGIN IMMEDIATE")
            applied_after_lock = await db.execute_fetchall(
                "SELECT 1 FROM schema_migrations WHERE name = ?",
                (self.MESSAGE_TIME_MIGRATION,),
            )
            if applied_after_lock:
                await db.commit()
                return
            history_times: dict[str, str] = {}
            history_rows = await db.execute_fetchall(
                "SELECT id, source_message_id, timestamp, content FROM chat_history"
            )
            for row_id, source_message_id, timestamp, content in history_rows:
                cleaned, embedded_time = strip_legacy_time_prefix(content or "")
                normalized = (
                    embedded_time.isoformat()
                    if embedded_time is not None
                    else self._normalize_timestamp(timestamp)
                )
                if normalized is None:
                    continue
                await db.execute(
                    "UPDATE chat_history SET content = ?, timestamp = ? WHERE id = ?",
                    (cleaned, normalized, row_id),
                )
                if source_message_id:
                    history_times[source_message_id] = normalized

            checkpoint_rows = await db.execute_fetchall(
                "SELECT id, state_json, created_at FROM checkpoints"
            )
            for checkpoint_id, state_json, checkpoint_created_at in checkpoint_rows:
                data = json.loads(state_json)
                messages = data.get("messages") or []
                resolved_times: list[str | None] = []
                fallback = (
                    self._normalize_timestamp(data.get("updated_at"))
                    or self._normalize_timestamp(checkpoint_created_at)
                    or utc_now().isoformat()
                )
                for message in messages:
                    embedded_time = self._clean_legacy_message_content(message)
                    message_id = message.get("_message_id")
                    history_time = (
                        history_times.get(f"{message_id}:content")
                        if message_id
                        else None
                    )
                    resolved = (
                        embedded_time.isoformat()
                        if embedded_time is not None
                        else self._normalize_timestamp(message.get("_created_at"))
                        or history_time
                    )
                    resolved_times.append(resolved)

                nearest: str | None = None
                for index, resolved in enumerate(resolved_times):
                    if resolved:
                        nearest = resolved
                    elif nearest:
                        resolved_times[index] = nearest
                nearest = None
                for index in range(len(resolved_times) - 1, -1, -1):
                    if resolved_times[index]:
                        nearest = resolved_times[index]
                    elif nearest:
                        resolved_times[index] = nearest

                for message, resolved in zip(messages, resolved_times):
                    if message.get("role") in {"user", "assistant"}:
                        message["_created_at"] = resolved or fallback

                await db.execute(
                    "UPDATE checkpoints SET state_json = ? WHERE id = ?",
                    (json.dumps(data, ensure_ascii=False, default=str), checkpoint_id),
                )

            await db.execute(
                "INSERT INTO schema_migrations(name, applied_at) VALUES (?, ?)",
                (self.MESSAGE_TIME_MIGRATION, utc_now().isoformat()),
            )
            await db.commit()
        except BaseException:
            await db.rollback()
            raise

    @staticmethod
    def _ensure_message_metadata(state: AgentState) -> None:
        for message in state.messages:
            message.setdefault("_message_id", uuid4().hex)
            created_at = message.get("_created_at") or state.updated_at
            message["_created_at"] = normalize_utc(created_at).isoformat()

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
                    utc_now().isoformat(),
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
