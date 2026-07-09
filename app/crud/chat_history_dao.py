from pathlib import Path
import json
import logging
import aiosqlite
from datetime import datetime, timezone

from app.runtime import get_chat_history_db

logger = logging.getLogger(__name__)
class ChatHistoryDao:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or get_chat_history_db()

    @staticmethod
    def _to_local_time_text(utc_timestamp_value: object) -> str:
        """把多种 UTC 时间格式转换为系统本地时区文本。"""
        try:
            utc_dt: datetime
            if isinstance(utc_timestamp_value, datetime):
                utc_dt = utc_timestamp_value
            elif isinstance(utc_timestamp_value, (int, float)):
                epoch = float(utc_timestamp_value)
                # 13 位时间戳通常是毫秒，先换算为秒。
                if abs(epoch) >= 1e12:
                    epoch /= 1000.0
                utc_dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
            elif isinstance(utc_timestamp_value, str):
                text = utc_timestamp_value.strip()
                if not text:
                    raise ValueError("empty timestamp string")
                try:
                    utc_dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                except ValueError:
                    normalized = text.replace("Z", "+00:00")
                    try:
                        utc_dt = datetime.fromisoformat(normalized)
                    except ValueError:
                        epoch = float(text)
                        if abs(epoch) >= 1e12:
                            epoch /= 1000.0
                        utc_dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
            else:
                raise TypeError(f"unsupported timestamp type: {type(utc_timestamp_value).__name__}")

            if utc_dt.tzinfo is None:
                utc_dt = utc_dt.replace(tzinfo=timezone.utc)
            else:
                utc_dt = utc_dt.astimezone(timezone.utc)
            return utc_dt.astimezone().isoformat(timespec="seconds")
        except Exception:
            logger.warning("[ChatHistory] 无法解析 timestamp=%r", utc_timestamp_value)
            return str(utc_timestamp_value)

    @staticmethod
    def _remove_timestamp(text: str) -> str:
        """
        移除聊天记录字符串开头方括号内的内容（时间戳等），返回剩余的消息文本。
        """

        # 直接取第一个 ']' 之后的内容
        if ']' in text:
            # 分割一次，取后半部分，并去除左侧空格
            return text.split(']', 1)[-1].lstrip()
        return text

    async def list_chat_history_async(self, session_id: str, start: int = 0, limit: int = 200) -> list[dict[str, str]]:
        """查询会话历史，并把 UTC 时间转换为系统本地时区。"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                cursor = await conn.execute(
                    """
                    SELECT id, source_message_id, role, content, timestamp, image_filenames
                    FROM chat_history
                    WHERE thread_id = ?
                    ORDER BY timestamp ASC, id ASC
                    LIMIT ? OFFSET ?
                    """,
                    (session_id, limit, start),
                )
                rows = await cursor.fetchall()

            return [
                {
                    "id": source_message_id or str(row_id),
                    "role": role,
                    "content": self._remove_timestamp(content),
                    "timestamp": self._to_local_time_text(timestamp_text),
                    "images": json.loads(image_filenames) if image_filenames else None,
                }
                for row_id, source_message_id, role, content, timestamp_text, image_filenames in rows
            ]
        except Exception:
            logger.exception("[ChatHistory][session=%s] 查询聊天记录失败", session_id)
            return []

    async def list_chat_history_last_n_async(self, session_id: str, n: int = 100) -> list[dict[str, str]]:
        """查询会话最后 N 条历史记录，按时间升序返回。"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                cursor = await conn.execute(
                    """
                    SELECT id, source_message_id, role, content, timestamp, image_filenames
                    FROM chat_history
                    WHERE thread_id = ?
                    ORDER BY timestamp DESC, id DESC
                    LIMIT ?
                    """,
                    (session_id, n),
                )
                rows = await cursor.fetchall()

            # 反转顺序，使其按时间升序返回
            rows = list(reversed(rows))

            return [
                {
                    "id": source_message_id or str(row_id),
                    "role": role,
                    "content": self._remove_timestamp(content),
                    "timestamp": self._to_local_time_text(timestamp_text),
                    "images": json.loads(image_filenames) if image_filenames else None,
                }
                for row_id, source_message_id, role, content, timestamp_text, image_filenames in rows
            ]
        except Exception:
            logger.exception("[ChatHistory][session=%s] 查询最后聊天记录失败", session_id)
            return []
