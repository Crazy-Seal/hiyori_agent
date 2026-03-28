from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    # 用户输入文本
    message: str = Field(..., min_length=1, description="User input message")
    # 会话标识：同一个 session_id 可共享上下文
    session_id: str = Field(default="default", description="Conversation session id")


class ChatResponse(BaseModel):
    # Agent 返回文本
    response: str
    # 本次使用的模型名（用于调试和观测）
    model: str


class ChatHistoryItem(BaseModel):
    role: str
    content: str
    # 已转换为系统本地时区的时间
    timestamp: str
