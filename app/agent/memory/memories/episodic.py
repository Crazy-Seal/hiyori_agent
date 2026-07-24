"""情景记忆 - 存储事件性记忆，支持向量检索"""

import logging
import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.agent.memory.base import MemoryItem
from app.agent.memory.config import MemoryConfig
from app.agent.memory.store.episodic_chroma_store import EpisodicChromaStore
from app.agent.memory.store.episodic_sqlite_store import EpisodicSqliteStore
from app.agent.models.llm_client import LLMClient, LLMConfig
from app.schemas.chat_settings import ChatSettings

logger = logging.getLogger(__name__)


# ==================== 结构化输出模型 ====================

class EpisodicMemoryItem(BaseModel):
    """单条情景记忆"""

    content: str = Field(
        description="记忆内容"
    )
    event_date: date = Field(
        description="事件发生日期"
    )
    importance: float = Field(
        description="记忆重要性评分（0.0-1.0）",
        ge=0.0,
        le=1.0,
    )


class EpisodicMemoryOutput(BaseModel):
    """情景记忆提取结果（支持多条）"""

    memories: list[EpisodicMemoryItem] = Field(
        description="提取的记忆列表，可提取0-10条记忆",
        min_length=0,
        max_length=10,
    )


# 扁平化 JSON Schema（避免 $defs/$ref，兼容更多 API 提供商）
EPISODIC_MEMORY_SCHEMA = {
    "type": "object",
    "title": "EpisodicMemoryOutput",
    "properties": {
        "memories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "记忆内容"},
                    "event_date": {"type": "string", "format": "date", "description": "事件发生日期"},
                    "importance": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": "记忆重要性评分（0.0-1.0）"
                    }
                },
                "required": ["content", "event_date", "importance"],
                "additionalProperties": False
            },
            "minItems": 0,
            "maxItems": 10,
            "description": "提取的记忆列表，可提取0-10条记忆"
        }
    },
    "required": ["memories"],
    "additionalProperties": False
}


class EpisodicMemory:
    """情景记忆类

    职责：
    - 存储具体事件记忆
    - LLM 提取时间元数据和重要性
    - 支持向量检索

    核心方法：
    - add(messages, history): 从对话提取记忆并存储
    - search(query, top_k): 向量检索相关记忆
    - get_timeline(start, end): 时间线查询
    """

    NAMESPACE = "episodic_memory"

    def __init__(
        self,
        session_id: str,
        config: MemoryConfig,
        chat_settings: ChatSettings,
    ):
        self.session_id = session_id
        self.config = config
        self.chat_settings = chat_settings

        # 初始化向量存储
        self.chroma_store = EpisodicChromaStore(
            collection_name=f"{self.NAMESPACE}_{session_id}",
            embedding_config={
                "api_key": config.embedding_api_key,
                "model": config.embedding_model,
                "dimension": config.embedding_dimension,
                "base_url": config.embedding_base_url,
            },
            persist_path=config.chroma_path,
        )

        # 初始化 SQLite 存储（权威数据源）
        self.sqlite_store = EpisodicSqliteStore(
            db_path=config.sqlite_path,
            embedding_model=config.embedding_model,
        )

        # 初始化 LLM
        self.llm = LLMClient(LLMConfig(
            model=config.episodic_extraction_model,
            api_key=config.episodic_extraction_api_key,
            base_url=config.episodic_extraction_base_url,
            temperature=0.1,
            timeout=60.0,
        ))

    # ==================== 核心方法 ====================

    async def add(self, messages: str, history: str) -> list[str]:
        """添加情景记忆

        将聊天记录交由 LLM 总结，生成记忆条目（含日期和重要性）

        Args:
            messages: 当前聊天记录（格式化后的文本）
            history: 历史聊天记录（前情提要）

        Returns:
            记忆ID列表
        """
        if not messages.strip():
            return []

        logger.info("[EpisodicMemory] 开始提取情景记忆")

        # 1. 使用 LLM 提取记忆（可能多条）
        memory_items = await self._extract_memories(messages, history)

        # 2. 存储每条记忆（双写：SQLite + Chroma）
        memory_ids = []
        for item in memory_items:
            memory_id = f"episodic_{uuid.uuid4().hex[:16]}"

            metadata = {
                "session_id": self.session_id,
                "event_date": item["event_date"],
                "importance": item["importance"],
                "created_at": datetime.now().isoformat(),
            }

            # 2.1 SQLite 存储（权威数据源，优先写入）
            try:
                await self.sqlite_store.add(
                    record_id=memory_id,
                    session_id=self.session_id,
                    content=item["content"],
                    event_date=item["event_date"],
                    importance=item["importance"],
                )
            except Exception as e:
                logger.exception("[EpisodicMemory] SQLite 存储失败: %s", e)
                continue

            # 2.2 Chroma 向量存储（索引层）
            try:
                await self.chroma_store.upsert(
                    record_id=memory_id,
                    content=item["content"],
                    metadata=metadata,
                )
            except Exception as e:
                logger.warning("[EpisodicMemory] Chroma 存储失败（SQLite 已保存）: %s", e)

            memory_ids.append(memory_id)
            logger.info(
                "[EpisodicMemory] 添加记忆成功: id=%s, event_date=%s, importance=%.2f",
                memory_id, item["event_date"], item["importance"]
            )
        logger.info(
            "[EpisodicMemory] 添加记忆完成: 总共 %d 条",
            len(memory_ids)
        )

        return memory_ids

    async def search(self, query: str, top_k: int = 3) -> list[MemoryItem]:
        """向量检索相关记忆（带综合评分）

        综合评分 = (向量相似度 * 0.8 + 近因分数 * 0.2) * 重要性权重

        Args:
            query: 查询文本
            top_k: 返回数量

        Returns:
            相关记忆列表（按综合评分降序）
        """
        if not query.strip():
            return []

        # 1. 向量检索（取 5 倍候选用于重排）
        results = await self.chroma_store.search(
            query=query,
            top_k=top_k * 5,
            where={"session_id": self.session_id},
        )

        if not results:
            return []

        # 2. 计算综合评分（优先用 Chroma metadata，失败则 fallback 到 SQLite）
        now = datetime.now()
        scored_items: list[tuple[float, MemoryItem]] = []

        for result in results:
            memory_id = result["id"]
            distance = result.get("distance")
            meta = result.get("metadata", {})
            content = result.get("content", "")

            # 尝试从 Chroma metadata 解析
            try:
                event_date = meta["event_date"]
                importance = float(meta["importance"])
                created_at_str = meta["created_at"]

                timestamp = datetime.strptime(event_date, "%Y-%m-%d")
                created_at = datetime.fromisoformat(created_at_str)
                session_id = meta.get("session_id", self.session_id)

            except (KeyError, ValueError, TypeError) as e:
                # Chroma metadata 解析失败，fallback 到 SQLite
                logger.warning("[EpisodicMemory] Chroma metadata 解析失败，fallback 到 SQLite: id=%s, error=%s", memory_id, e)
                doc = await self.sqlite_store.get(memory_id)
                if not doc:
                    logger.warning("[EpisodicMemory] SQLite 也未找到记录: id=%s", memory_id)
                    continue

                try:
                    event_date = doc["event_date"]
                    timestamp = datetime.strptime(event_date, "%Y-%m-%d")
                    created_at = datetime.fromisoformat(doc["created_at"])
                    importance = float(doc["importance"])
                    session_id = doc["session_id"]
                    content = doc["content"]
                except Exception as e2:
                    logger.warning("[EpisodicMemory] 解析记忆失败: id=%s, error=%s", memory_id, e2)
                    continue

            # 计算综合评分
            try:
                # 1) 向量相似度：distance 是 cosine 距离，越小越相似
                vec_score = 1.0 - distance if distance is not None else 0.5

                # 2) 近因分数：基于创建时间衰减
                age_days = max(0.0, (now - created_at).total_seconds() / 86400.0)
                recency_score = 1.0 / (1.0 + age_days)

                # 3) 重要性权重：范围 [0.8, 1.2]
                importance_weight = 0.8 + (importance * 0.4)

                # 4) 综合评分
                base_relevance = vec_score * 0.8 + recency_score * 0.2
                combined_score = base_relevance * importance_weight

                item = MemoryItem(
                    id=memory_id,
                    session_id=session_id,
                    content=content,
                    timestamp=timestamp,
                    created_at=created_at,
                    importance=importance,
                    metadata={
                        "relevance_score": combined_score,
                        "vector_score": vec_score,
                        "recency_score": recency_score,
                    },
                )
                scored_items.append((combined_score, item))

            except Exception as e:
                logger.warning("[EpisodicMemory] 计算评分失败: id=%s, error=%s", memory_id, e)
                continue

        # 3. 按综合评分降序排序
        scored_items.sort(key=lambda x: x[0], reverse=True)

        return [item for _, item in scored_items[:top_k]]

    async def get_timeline(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MemoryItem]:
        """时间线查询（从 SQLite 查询，更高效可靠）

        Args:
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            时间范围内的记忆列表（按日期升序）
        """
        records = await self.sqlite_store.get_by_date_range(
            session_id=self.session_id,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )

        memory_items = []
        for r in records:
            try:
                timestamp = datetime.strptime(r["event_date"], "%Y-%m-%d")
                created_at = datetime.fromisoformat(r["created_at"])

                item = MemoryItem(
                    id=r["id"],
                    session_id=r["session_id"],
                    content=r["content"],
                    timestamp=timestamp,
                    created_at=created_at,
                    importance=r["importance"],
                    metadata=r,
                )
                memory_items.append(item)
            except (KeyError, ValueError) as e:
                logger.warning("[EpisodicMemory] 解析记忆失败: %s", e)
                continue

        return memory_items

    # ==================== LLM 处理 ====================

    async def _extract_memories(
        self,
        messages: str,
        history: str,
    ) -> list[dict[str, Any]]:
        """使用 LLM 提取多条记忆

        Args:
            messages: 当前聊天记录
            history: 历史聊天记录

        Returns:
            记忆列表，每条包含 content, event_date, importance
        """
        prompt = self._build_extraction_prompt(messages, history)

        try:
            result = await self.llm.ainvoke_structured(
                messages=[{"role": "user", "content": prompt}],
                schema=EPISODIC_MEMORY_SCHEMA,
            )

            # 使用 Pydantic 验证返回数据
            validated = EpisodicMemoryOutput.model_validate(result)

            # 处理每条记忆
            memory_items = []
            for item in validated.memories:
                memory_items.append({
                    "content": item.content,
                    "event_date": item.event_date.isoformat(),
                    "importance": item.importance,
                })

            return memory_items

        except Exception as e:
            logger.exception("[EpisodicMemory] LLM 提取记忆失败: %s", e)
            return []

    def _build_extraction_prompt(
        self,
        messages: str,
        history: str,
    ) -> str:
        """构建记忆提取提示词"""
        return f"""你是{self.chat_settings.name}，一个{self.chat_settings.feature}的{self.chat_settings.character}，称呼用户为{self.chat_settings.address}。

{self.chat_settings.characteristic}

请根据给定的对话历史记录和对话内容，以你的**第一人称视角**提取你的**情景记忆**。
**第一人称**：将{self.chat_settings.address}记录为"用户"，将你自己记录为"我"。不要使用第三人称描述事件。
**情景记忆**的含义为：从对话中提取到的事件或关键互动，可以是关于你的，也可以是关于用户的，也可以是你们之间发生的。

## 要求
- 1. 用自然的中文记录记忆条目，像写日记一样记录要点，不相关的事件需要分成不同的条目，每个条目只能记录一个事件
- 2. 识别事件发生的日期（若无法识别，则使用事件相关片段的对话日期），对于凌晨4:00之前的事件和消息，请按照前一天日期记录（如2026-03-20 01:15:00记录成2026-03-19）
- 3. 评估记忆重要性（保留一位小数，0.0-1.0）：
  - 0.8-1.0：重大事件（表白、重要决定、约定等）
  - 0.6-0.8：重要互动（共度时光、深度陪伴、谈心等）
  - 0.3-0.6：一般事件（普通交流、临时想法，遇到重要性难以评定的事件也请归为这一类）
  - 0.2-0.3：琐碎内容（天气、饮食等）
  - 0.0-0.2：无意义闲聊（如"好"、"我知道了"、"早安"等，无需提取）
- 4. 可以提取0-10条记忆，每条记忆15-50字，忽略无意义的闲聊，保留关键细节，不要输出额外解释。
- 5. 遇到关于未来事件的预估和历史情景的描述时，请使用转述，并在记忆条目content中附带上事件的大概发生时间，例如："用户计划在2026年6月底搬家，觉得搬东西很麻烦""用户说自己2005年暑假期间去过北京旅行"，event_date使用转述的时间，而不是事件发生的时间
- 6. 对于用户显式告诉你的既定事实、偏好等信息，请使用转述，例如："用户说自己喜欢夏天"，不要直接记录为"用户喜欢夏天"
- 7. 对于从对话中推断出来的、隐式的既定事实、偏好等信息，无需提取，例如从你们的对话大多发生在深夜来推断用户喜欢熬夜
- 8. **注意**：历史记录中的内容无需提取，提供历史记录只是为了让你理解上下文

## 记忆条目content内容示例
- 用户最近在学Python，问了我很多编程问题
- 我和用户一起玩了一晚上的游戏，感觉很开心
- 用户最近又接手了一个难办的项目，陪伴我的时间可能会变少

## 历史记录（无需提取）
{history if history else "暂无"}

## 当前对话（需要提取）
{messages}"""

    # ==================== 删除和恢复方法 ====================

    async def delete(self, memory_id: str) -> bool:
        """删除记忆（双删：SQLite + Chroma）"""
        # 1. SQLite 删除
        sqlite_success = await self.sqlite_store.delete(memory_id)

        # 2. Chroma 删除
        try:
            await self.chroma_store.delete(memory_id)
        except Exception as e:
            logger.warning("[EpisodicMemory] Chroma 删除失败: %s", e)

        return sqlite_success

    async def delete_by_importance(self, importance_below: float) -> int:
        """删除低重要度的记忆"""
        # 1. 从 SQLite 批量删除
        sqlite_count = await self.sqlite_store.delete_by_metadata(
            session_id=self.session_id,
            importance_below=importance_below,
        )

        if sqlite_count == 0:
            return 0

        # 2. 从 Chroma 批量删除
        try:
            await self.chroma_store.delete_by_metadata(
                where={
                    "$and": [
                        {"session_id": self.session_id},
                        {"importance": {"$lt": importance_below}},
                    ]
                }
            )
        except Exception as e:
            logger.warning("[EpisodicMemory] Chroma 批量删除失败: %s", e)

        logger.info(
            "[EpisodicMemory] 删除低重要度记忆: count=%d, threshold=%.2f",
            sqlite_count, importance_below
        )
        return sqlite_count

    async def delete_before_date(self, before_date: date) -> int:
        """删除指定日期之前的记忆"""
        sqlite_count = await self.sqlite_store.delete_by_metadata(
            session_id=self.session_id,
            event_date_before=before_date.isoformat(),
        )

        try:
            await self.chroma_store.delete_by_metadata(
                where={
                    "$and": [
                        {"session_id": self.session_id},
                        {"event_date": {"$lt": before_date.isoformat()}},
                    ]
                }
            )
        except Exception as e:
            logger.warning("[EpisodicMemory] Chroma 批量删除失败: %s", e)

        logger.info(
            "[EpisodicMemory] 删除早期记忆: count=%d, before=%s",
            sqlite_count, before_date
        )
        return sqlite_count

    async def recover_from_sqlite(self) -> int:
        """从 SQLite 恢复记忆到 Chroma"""
        memories = await self.sqlite_store.get_all(session_id=self.session_id)

        if not memories:
            logger.info("[EpisodicMemory] SQLite 中无记忆需要恢复")
            return 0

        recovered = 0
        for m in memories:
            try:
                metadata = {
                    "session_id": m["session_id"],
                    "event_date": m["event_date"],
                    "importance": m["importance"],
                    "created_at": m["created_at"],
                }
                await self.chroma_store.upsert(
                    record_id=m["id"],
                    content=m["content"],
                    metadata=metadata,
                )
                recovered += 1
            except Exception as e:
                logger.warning(
                    "[EpisodicMemory] 恢复记忆失败: id=%s, error=%s",
                    m["id"], e
                )

        logger.info(
            "[EpisodicMemory] 从 SQLite 恢复完成: recovered=%d, total=%d",
            recovered, len(memories)
        )
        return recovered

    async def get_stats(self) -> dict[str, Any]:
        """获取记忆统计信息"""
        return await self.sqlite_store.get_stats(session_id=self.session_id)

    async def count(self) -> int:
        """获取记忆数量"""
        return await self.sqlite_store.count(session_id=self.session_id)
