from pydantic import BaseModel, Field


# VO
class ChatRequest(BaseModel):
    # 用户输入文本
    message: str = Field(..., min_length=1, description="User input message")
    # 会话标识：同一个 session_id 可共享上下文
    session_id: str = Field(default="default", description="Conversation session id")
    # 图像列表（data URL 格式）
    images: list[str] | None = Field(default=None, description="List of images in data URL format")


# VO
class ChatResponse(BaseModel):
    # Agent 返回文本
    response: str
    # 本次使用的模型名（用于调试和观测）
    model: str


# Agent 输入数据结构，包含用户文本输入和图像信息
class AgentInput(BaseModel):
    # 用户输入文本
    message: str = Field(..., min_length=1, description="User input message")
    # 图像列表
    images: list[str] | None = Field(default=None, description="List of images in data URL format")


# DTO
class ChatHistoryItem(BaseModel):
    id: str
    role: str
    content: str
    # 已转换为系统本地时区的时间
    timestamp: str
    # 图片文件路径列表
    images: list[str] | None = Field(default=None, description="List of image file paths")
