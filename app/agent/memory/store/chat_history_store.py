"""
聊天记录存储 - 访问 chat_history 表
"""

import json
import logging
from datetime import date, datetime, time, timezone, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import aiosqlite

from app.runtime import get_chat_history_db

logger = logging.getLogger(__name__)

class ChatHistoryStore:
    """聊天记录存储类

    负责：
    - 保存聊天记录
    - 按本地日期查询消息数量
    - 获取指定本地日期的聊天记录
    - 获取最后一个有聊天记录的本地日期

    时间规则：
    - 数据库存储 UTC 时间
    - 查询和显示使用本地时间（配置的时区）
    - 本地日期边界：凌晨 N 点前算前一天，N 点后算当天
    """

    TABLE_NAME = "chat_history"

    def __init__(
        self,
        db_path: Path | str | None = None,
        timezone: ZoneInfo | None = None,
        day_boundary_hour: int = 4,
    ):
        self.db_path = Path(db_path) if db_path else get_chat_history_db()
        self.timezone = timezone or datetime.now().astimezone().tzinfo
        self.day_boundary_hour = day_boundary_hour
        self._ensure_table()

    def _ensure_table(self):
        """确保表存在"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        import sqlite3
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
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
            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_thread_time
                ON {self.TABLE_NAME}(thread_id, timestamp)
            """)
            try:
                conn.execute(f"ALTER TABLE {self.TABLE_NAME} ADD COLUMN image_filenames TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute(f"ALTER TABLE {self.TABLE_NAME} ADD COLUMN source_message_id TEXT")
            except sqlite3.OperationalError:
                pass
            conn.execute(f"""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_history_source_message
                ON {self.TABLE_NAME}(source_message_id)
                WHERE source_message_id IS NOT NULL
            """)
            conn.commit()

    def _local_date_to_utc_range(self, local_date: date) -> tuple[datetime, datetime]:
        """将本地日期转换为 UTC 时间范围"""
        local_start = datetime.combine(
            local_date, time(self.day_boundary_hour, 0, 0), tzinfo=self.timezone
        )
        local_end = datetime.combine(
            local_date + timedelta(days=1), time(self.day_boundary_hour, 0, 0), tzinfo=self.timezone
        )
        utc_start = local_start.astimezone(timezone.utc)
        utc_end = local_end.astimezone(timezone.utc)
        return utc_start, utc_end

    def _utc_to_local_date(self, utc_timestamp: str | datetime | int | float) -> date:
        """将 UTC 时间戳转换为本地日期"""
        dt = self._parse_timestamp(utc_timestamp)
        if dt is None:
            if isinstance(utc_timestamp, str):
                return date.fromisoformat(utc_timestamp)
            raise ValueError(f"无法解析时间戳: {utc_timestamp}")

        local_dt = dt.astimezone(self.timezone)
        if local_dt.hour < self.day_boundary_hour:
            return (local_dt - timedelta(days=1)).date()
        return local_dt.date()

    def _parse_timestamp(self, timestamp: str | datetime | int | float) -> datetime | None:
        """解析各种格式的时间戳为 UTC datetime"""
        if isinstance(timestamp, datetime):
            if timestamp.tzinfo is None:
                return timestamp.replace(tzinfo=timezone.utc)
            return timestamp.astimezone(timezone.utc)

        if isinstance(timestamp, (int, float)):
            ts = timestamp
            if ts > 1e12:
                ts = ts / 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc)

        if isinstance(timestamp, str):
            try:
                ts = float(timestamp)
                if ts > 1e12:
                    ts = ts / 1000
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except ValueError:
                pass

            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                pass

            try:
                dt_str = timestamp.split(".")[0]
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        return None

    def _format_local_time(self, timestamp: str | datetime | int | float, include_weekday: bool = True) -> str:
        """将时间戳格式化为本地时间字符串"""
        dt = self._parse_timestamp(timestamp)
        if dt is None:
            return str(timestamp)

        local_dt = dt.astimezone(self.timezone)

        if include_weekday:
            weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            weekday = weekdays[local_dt.weekday()]
            return f"{local_dt.strftime('%Y-%m-%d')} {weekday} {local_dt.strftime('%H:%M:%S')}"
        else:
            return local_dt.strftime('%Y-%m-%d %H:%M:%S')

    # ==================== 写入方法 ====================

    async def save_chat_message(
        self,
        session_id: str,
        role: str,
        content: str,
        image_description: str | None = None,
        image_filenames: list[str] | None = None,
    ) -> None:
        """保存单条聊天记录"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        filenames_json = json.dumps(image_filenames, ensure_ascii=False) if image_filenames else None
        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute("PRAGMA busy_timeout=5000")
                await conn.execute(
                    f"INSERT INTO {self.TABLE_NAME} (thread_id, role, content, image_description, image_filenames) VALUES (?, ?, ?, ?, ?)",
                    (session_id, role, content, image_description, filenames_json),
                )
                await conn.commit()
        except Exception:
            logger.exception("[ChatHistoryStore][session=%s] 保存聊天记录失败", session_id)

    # ==================== 查询方法 ====================

    async def get_message_count_by_date(
        self,
        session_id: str,
        effective_date: date,
        role: str | None = None,
    ) -> int:
        """获取指定本地日期的消息数量"""
        utc_start, utc_end = self._local_date_to_utc_range(effective_date)

        async with aiosqlite.connect(str(self.db_path)) as conn:
            await conn.execute("PRAGMA busy_timeout=5000")
            if role:
                cursor = await conn.execute(
                    f"""
                    SELECT COUNT(*) FROM {self.TABLE_NAME}
                    WHERE thread_id = ? AND timestamp >= ? AND timestamp < ? AND role = ?
                    """,
                    (session_id, utc_start.isoformat(), utc_end.isoformat(), role),
                )
            else:
                cursor = await conn.execute(
                    f"""
                    SELECT COUNT(*) FROM {self.TABLE_NAME}
                    WHERE thread_id = ? AND timestamp >= ? AND timestamp < ?
                    """,
                    (session_id, utc_start.isoformat(), utc_end.isoformat()),
                )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_last_chat_date(
        self,
        session_id: str,
        exclude_today: date | None = None,
    ) -> date | None:
        """获取最后一个有聊天记录的本地日期"""
        async with aiosqlite.connect(str(self.db_path)) as conn:
            await conn.execute("PRAGMA busy_timeout=5000")
            if exclude_today:
                utc_start, utc_end = self._local_date_to_utc_range(exclude_today)
                cursor = await conn.execute(
                    f"""
                    SELECT timestamp FROM {self.TABLE_NAME}
                    WHERE thread_id = ? AND timestamp < ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    (session_id, utc_start.isoformat()),
                )
            else:
                cursor = await conn.execute(
                    f"""
                    SELECT timestamp FROM {self.TABLE_NAME}
                    WHERE thread_id = ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    (session_id,),
                )
            row = await cursor.fetchone()
            if row:
                return self._utc_to_local_date(row[0])
            return None

    async def get_messages_by_date(
        self,
        session_id: str,
        effective_date: date,
    ) -> list[dict[str, Any]]:
        """获取指定本地日期的所有聊天记录"""
        utc_start, utc_end = self._local_date_to_utc_range(effective_date)

        async with aiosqlite.connect(str(self.db_path)) as conn:
            await conn.execute("PRAGMA busy_timeout=5000")
            cursor = await conn.execute(
                f"""
                SELECT role, content, timestamp, image_description, image_filenames
                FROM {self.TABLE_NAME}
                WHERE thread_id = ? AND timestamp >= ? AND timestamp < ?
                ORDER BY timestamp ASC, id ASC
                """,
                (session_id, utc_start.isoformat(), utc_end.isoformat()),
            )
            rows = await cursor.fetchall()
            return [
                {
                    "role": row[0],
                    "content": row[1],
                    "timestamp": self._format_local_time(row[2]),
                    "image_description": row[3],
                    "images": json.loads(row[4]) if row[4] else None,
                }
                for row in rows
            ]

    async def list_chat_history(
        self,
        session_id: str,
        start: int = 0,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """查询会话历史"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute("PRAGMA busy_timeout=5000")
                cursor = await conn.execute(
                    f"""
                    SELECT role, content, timestamp, image_filenames
                    FROM {self.TABLE_NAME}
                    WHERE thread_id = ?
                    ORDER BY timestamp ASC, id ASC
                    LIMIT ? OFFSET ?
                    """,
                    (session_id, limit, start),
                )
                rows = await cursor.fetchall()
                return [
                    {
                        "role": row[0],
                        "content": row[1],
                        "timestamp": self._format_local_time(row[2]),
                        "images": json.loads(row[3]) if row[3] else None,
                    }
                    for row in rows
                ]
        except Exception:
            logger.exception("[ChatHistoryStore][session=%s] 查询聊天记录失败", session_id)
            return []

    async def has_chat_on_date(
        self,
        session_id: str,
        effective_date: date,
    ) -> bool:
        """检查指定本地日期是否有聊天记录"""
        count = await self.get_message_count_by_date(session_id, effective_date)
        return count > 0

    async def get_messages_before_date(
        self,
        session_id: str,
        before_date: date,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """获取指定本地日期之前的最后 N 条聊天记录"""
        utc_start, utc_end = self._local_date_to_utc_range(before_date)

        async with aiosqlite.connect(str(self.db_path)) as conn:
            await conn.execute("PRAGMA busy_timeout=5000")
            cursor = await conn.execute(
                f"""
                SELECT role, content, timestamp, image_filenames FROM (
                    SELECT role, content, timestamp, image_filenames
                    FROM {self.TABLE_NAME}
                    WHERE thread_id = ? AND timestamp < ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                ) sub
                ORDER BY timestamp ASC
                """,
                (session_id, utc_start.isoformat(), limit),
            )
            rows = await cursor.fetchall()
            return [
                {
                    "role": row[0],
                    "content": row[1],
                    "timestamp": self._format_local_time(row[2]),
                    "images": json.loads(row[3]) if row[3] else None,
                }
                for row in rows
            ]
