from pathlib import Path
import logging
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
DB_PATH = Path(__file__).resolve().parents[2] / "memory" / "sqlite" / "checkpoints.sqlite3"


class ChatHistoryDao:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path

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

    def save_chat_message(self, session_id: str, role: str, content: str) -> None:
        """保存单条聊天消息到 chat_history 表。"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    "INSERT INTO chat_history (thread_id, role, content) VALUES (?, ?, ?)",
                    (session_id, role, content),
                )
                conn.commit()
        except Exception:
            logger.exception("[ChatHistory][session=%s] 保存聊天记录失败", session_id)

    def save_chat_pair(self, session_id: str, user_message: str, ai_message: str) -> None:
        """兼容旧调用：保存一轮用户与助手对话到 chat_history 表。"""
        self.save_chat_message(session_id, "Human", user_message)
        self.save_chat_message(session_id, "AI", ai_message)

    def list_chat_history(self, session_id: str, start: int = 0, limit: int = 200) -> list[dict[str, str]]:
        """查询会话历史，并把 UTC 时间转换为系统本地时区。"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                rows = conn.execute(
                    """
                    SELECT role, content, timestamp
                    FROM chat_history
                    WHERE thread_id = ?
                    ORDER BY timestamp ASC, id ASC
                    LIMIT ? OFFSET ?
                    """,
                    (session_id, limit, start),
                ).fetchall()

            return [
                {
                    "role": role,
                    "content": content,
                    "timestamp": self._to_local_time_text(timestamp_text),
                }
                for role, content, timestamp_text in rows
            ]
        except Exception:
            logger.exception("[ChatHistory][session=%s] 查询聊天记录失败", session_id)
            return []