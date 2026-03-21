from typing import Optional
from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    """前端对话请求载荷 (符合前后端 API 契约)"""
    message: str
    conversation_id: Optional[str] = Field(default=None, alias="conversationId")

class Message(BaseModel):
    """标准消息结构定义"""
    role: str
    content: str
