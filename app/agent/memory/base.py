"""记忆系统基础数据类型定义"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class MemoryType(str, Enum):
    """记忆类型枚举"""
    SUMMARY = "summary"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"


@dataclass
class MemoryItem:
    """记忆项基类"""
    id: str                              # 格式: {type}_{UUID}
    session_id: str                      # 会话ID
    content: str                         # 记忆内容
    timestamp: datetime                  # 事件发生时间（LLM 提取）
    created_at: datetime                 # 记忆创建时间（系统时间）
    importance: float = 0.5              # 重要性 [0, 1]，LLM 评估
    metadata: dict[str, Any] = field(default_factory=dict)  # 扩展元数据

