from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class ConversationData(BaseModel):
    conversation_id: UUID


class CreateConversationResponse(BaseModel):
    success: bool = True
    data: ConversationData


class MessageData(BaseModel):
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class MessageHistoryData(BaseModel):
    conversation_id: UUID
    messages: list[MessageData]


class MessageHistoryResponse(BaseModel):
    success: bool = True
    data: MessageHistoryData


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    success: bool = False
    error: ErrorDetail
