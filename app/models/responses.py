from uuid import UUID

from pydantic import BaseModel


class ConversationData(BaseModel):
    conversation_id: UUID


class CreateConversationResponse(BaseModel):
    success: bool = True
    data: ConversationData


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    success: bool = False
    error: ErrorDetail
