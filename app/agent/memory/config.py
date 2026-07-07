"""
记忆系统配置
"""

import os
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from app.runtime import get_mem0_qdrant_dir, get_memory_base_dir


def get_system_timezone() -> ZoneInfo:
    """获取系统时区"""
    return datetime.now().astimezone().tzinfo


@dataclass
class MemoryConfig:
    """记忆系统配置"""
    # 存储路径
    sqlite_path: str = ""
    chroma_path: str = ""

    # Mem0 配置
    mem0_qdrant_path: str = ""
    mem0_collection_name: str = "Ayaya_semantic_memory"

    # 嵌入配置
    embedding_api_key: str = ""
    embedding_model: str = ""
    embedding_dimension: int = 1024
    embedding_base_url: str = ""

    # 记忆参数
    summary_every_messages: int = 10     # 每 N 条消息生成一次摘要
    recent_summaries_count: int = 2      # 获取最近 N 天摘要
    episodic_top_k: int = 3              # 情景记忆检索数量
    semantic_top_k: int = 3              # 语义记忆检索数量

    # 时区配置
    timezone: ZoneInfo = field(default_factory=get_system_timezone)
    day_boundary_hour: int = 4           # 新的一天分界点（小时）

    @classmethod
    def from_env(cls) -> "MemoryConfig":
        """从环境变量加载配置"""
        base_path = get_memory_base_dir()

        tz_name = os.getenv("MEMORY_TIMEZONE")
        if tz_name:
            timezone = ZoneInfo(tz_name)
        else:
            timezone = get_system_timezone()

        day_boundary_hour = int(os.getenv("MEMORY_DAY_BOUNDARY_HOUR", "4"))

        return cls(
            sqlite_path=str(base_path / "sqlite" / "memory.sqlite3"),
            chroma_path=str(base_path / "chroma"),
            mem0_qdrant_path=str(get_mem0_qdrant_dir(base_path)),
            mem0_collection_name=os.getenv("MEM0_COLLECTION_NAME", "Ayaya_semantic_memory"),
            embedding_api_key=os.getenv("EMBEDDING_API_KEY", ""),
            embedding_model=os.getenv("EMBEDDING_MODEL", ""),
            embedding_dimension=int(os.getenv("EMBEDDING_DIMENSION", "1024")),
            embedding_base_url=os.getenv("EMBEDDING_BASE_URL", ""),
            timezone=timezone,
            day_boundary_hour=day_boundary_hour,
        )
